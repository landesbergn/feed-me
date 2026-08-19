import json
from pathlib import Path

import pytest

import ingest
import storage
from tests.conftest import FakeResponse


HTML_SAMPLE = """<!doctype html><html><head><title>Sample</title></head>
<body><article><h1>On Time</h1>
<p>The first paragraph of a long piece about time.</p>
<p>Another paragraph here, with more substantive content to satisfy
Readability's minimum-content heuristics for extraction.</p>
<p>A third paragraph pads the body past the minimum-extraction guard
(MIN_BODY_CHARS) so fixture-driven tests exercise the happy path rather
than the too-short failure.</p>
<p>Clocks divide the day into hours, the hours into minutes, and the
minutes into seconds, each division more arbitrary than the last.</p>
<p>Calendars do the same to years, charting months and weeks against the
slow drift of seasons that ignore them entirely.</p>
<p>And yet the piece keeps returning to the same question: who decided
that time should be counted at all, and what was lost when we agreed?</p>
</article></body></html>"""


def test_http_client_sends_browser_accept_headers():
    """Some sites (verified: nytimes.com) 403 any request missing the Accept /
    Accept-Language headers a real browser always sends, regardless of UA."""
    headers = ingest.http_client.headers
    assert "text/html" in headers.get("accept", "")
    assert headers.get("accept-language", "").startswith("en-US")
    assert "Safari" in headers.get("user-agent", "")


def test_openai_client_has_retry_headroom():
    """max_retries=5 (SDK default: 2). The bounded TTS pool can still exceed
    the per-minute rate limit when calls return quickly; 429 retries with
    backoff are the rate-limit correctness guarantee, so give them headroom."""
    assert ingest.openai_client.max_retries == 5


def test_openai_client_has_explicit_timeout():
    """A TTS call must give up quickly when the connection stalls, not ride the
    SDK's 600s default (a single stalled chunk blocked a 12-chunk article for
    ~21 min in prod, with max_retries masking the stall instead of recovering
    fast). read=60s caps the per-call stall; connect stays at the SDK default
    5s. Retries then re-attempt the bounded call."""
    timeout = ingest.openai_client.timeout
    assert timeout.read == 60
    assert timeout.connect == 5


def test_fetch_article_returns_title_and_body(monkeypatch, fake_http):
    fake_http.responses["https://example.com/x"] = FakeResponse(
        status_code=200, text=HTML_SAMPLE,
    )
    monkeypatch.setattr(ingest, "http_client", fake_http)

    title, body = ingest.fetch_article("https://example.com/x")

    assert "On Time" in title
    assert "first paragraph" in body
    assert "more substantive" in body


def test_fetch_article_takes_longer_extraction(monkeypatch, fake_http):
    """When trafilatura recovers more text than readability, its body wins.
    (Verified on newyorker.com: readability kept only the first half of the
    article; trafilatura extracted it to the end.)"""
    fake_http.responses["https://example.com/x"] = FakeResponse(
        status_code=200, text=HTML_SAMPLE,
    )
    monkeypatch.setattr(ingest, "http_client", fake_http)
    longer = "A recovered paragraph readability missed. " * 40
    monkeypatch.setattr(ingest, "_trafilatura_extract", lambda html: longer)

    title, body = ingest.fetch_article("https://example.com/x")

    assert "On Time" in title  # title still comes from the readability path
    assert "recovered paragraph" in body
    assert "first paragraph" not in body  # the shorter readability body lost


def test_fetch_article_keeps_readability_when_trafilatura_shorter(
    monkeypatch, fake_http,
):
    fake_http.responses["https://example.com/x"] = FakeResponse(
        status_code=200, text=HTML_SAMPLE,
    )
    monkeypatch.setattr(ingest, "http_client", fake_http)
    monkeypatch.setattr(ingest, "_trafilatura_extract", lambda html: "tiny")

    title, body = ingest.fetch_article("https://example.com/x")

    assert "first paragraph" in body
    assert body != "tiny"


def test_fetch_article_survives_trafilatura_none(monkeypatch, fake_http):
    """trafilatura returns None when it finds nothing; readability still wins."""
    fake_http.responses["https://example.com/x"] = FakeResponse(
        status_code=200, text=HTML_SAMPLE,
    )
    monkeypatch.setattr(ingest, "http_client", fake_http)
    monkeypatch.setattr(ingest, "_trafilatura_extract", lambda html: None)

    title, body = ingest.fetch_article("https://example.com/x")

    assert "On Time" in title
    assert "first paragraph" in body


def test_fetch_article_strips_title_from_winning_body(monkeypatch, fake_http):
    """trafilatura output often leads with the headline; it must not be
    narrated twice (title is already known)."""
    fake_http.responses["https://example.com/x"] = FakeResponse(
        status_code=200, text=HTML_SAMPLE,
    )
    monkeypatch.setattr(ingest, "http_client", fake_http)
    longer = "On Time\n" + ("A recovered paragraph readability missed. " * 40)
    monkeypatch.setattr(ingest, "_trafilatura_extract", lambda html: longer)

    title, body = ingest.fetch_article("https://example.com/x")

    assert "On Time" in title
    assert not body.startswith("On Time")


def _paywalled_html(paragraphs: int, marker: str) -> str:
    """Article HTML carrying a machine-readable paywall declaration."""
    body = "".join(
        f"<p>Paragraph {i} of the gated piece, padded with enough prose that "
        f"each one contributes a realistic amount of extracted text.</p>"
        for i in range(paragraphs)
    )
    return (
        "<!doctype html><html><head><title>Gated</title>"
        f"{marker}"
        "</head><body><article><h1>Gated</h1>"
        f"{body}</article></body></html>"
    )


JSONLD_PAYWALL = (
    '<script type="application/ld+json">'
    '{"@type":"NewsArticle","isAccessibleForFree":false}</script>'
)
META_PAYWALL = '<meta property="article:content_tier" content="locked"/>'


def test_fetch_article_fails_fast_on_declared_paywall_with_teaser_body(
    monkeypatch, fake_http,
):
    """A page that declares itself paywalled (schema.org isAccessibleForFree)
    and serves only a teaser fails with subscription copy instead of becoming
    a 2-minute episode that ends mid-article. Detection reads the page's own
    markup, never a site list. (Verified live: nytimes.com declares
    isAccessibleForFree:false and serves a 1,827-char teaser.)"""
    fake_http.responses["https://www.nytimes.com/a"] = FakeResponse(
        status_code=200, text=_paywalled_html(paragraphs=12, marker=JSONLD_PAYWALL),
    )
    monkeypatch.setattr(ingest, "http_client", fake_http)

    with pytest.raises(ingest.FetchError) as exc_info:
        ingest.fetch_article("https://www.nytimes.com/a")

    msg = str(exc_info.value)
    assert "www.nytimes.com" in msg
    assert "subscriber" in msg


def test_fetch_article_fails_fast_on_content_tier_locked(monkeypatch, fake_http):
    fake_http.responses["https://example.com/locked"] = FakeResponse(
        status_code=200, text=_paywalled_html(paragraphs=12, marker=META_PAYWALL),
    )
    monkeypatch.setattr(ingest, "http_client", fake_http)

    with pytest.raises(ingest.FetchError):
        ingest.fetch_article("https://example.com/locked")


def test_fetch_article_allows_declared_paywall_with_full_body(
    monkeypatch, fake_http,
):
    """Metered sites often serve the full text anyway (the newyorker.com
    case). A paywall declaration alone must not fail the fetch; only the
    declaration plus a teaser-sized body does."""
    fake_http.responses["https://example.com/metered"] = FakeResponse(
        status_code=200, text=_paywalled_html(paragraphs=40, marker=JSONLD_PAYWALL),
    )
    monkeypatch.setattr(ingest, "http_client", fake_http)

    title, body = ingest.fetch_article("https://example.com/metered")

    assert "Gated" in title
    assert len(body) > ingest.PAYWALL_BODY_MIN_CHARS


def test_fetch_article_raises_on_http_error(monkeypatch, fake_http):
    fake_http.responses["https://example.com/y"] = FakeResponse(status_code=500)
    monkeypatch.setattr(ingest, "http_client", fake_http)

    with pytest.raises(RuntimeError):
        ingest.fetch_article("https://example.com/y")


def test_fetch_article_403_error_is_friendly(monkeypatch, fake_http):
    """Blocked fetches surface human copy, not the raw httpx exception string
    (which leaked 'For more information check: https://developer.mozilla.'
    onto the share page, truncated mid-URL)."""
    fake_http.responses["https://www.nytimes.com/article"] = FakeResponse(
        status_code=403,
    )
    monkeypatch.setattr(ingest, "http_client", fake_http)

    with pytest.raises(RuntimeError) as exc_info:
        ingest.fetch_article("https://www.nytimes.com/article")

    msg = str(exc_info.value)
    assert "www.nytimes.com" in msg
    assert "subscription" in msg
    assert "developer.mozilla" not in msg
    assert "Client error" not in msg


def test_fetch_article_404_error_is_friendly(monkeypatch, fake_http):
    fake_http.responses["https://example.com/gone"] = FakeResponse(status_code=404)
    monkeypatch.setattr(ingest, "http_client", fake_http)

    with pytest.raises(RuntimeError) as exc_info:
        ingest.fetch_article("https://example.com/gone")

    msg = str(exc_info.value)
    assert "example.com" in msg
    assert "link may be broken" in msg


def test_process_writes_friendly_error_on_blocked_fetch(
    monkeypatch, fake_http, fake_openai, tmp_path,
):
    """The failed-episode error (shown on the share page and feed page) carries
    the friendly copy."""
    monkeypatch.setattr(ingest, "http_client", fake_http)
    monkeypatch.setattr(ingest, "openai_client", fake_openai)
    fake_http.responses["https://www.nytimes.com/article"] = FakeResponse(
        status_code=403,
    )

    secret = storage.create_user(tmp_path)
    ingest.process("https://www.nytimes.com/article", secret, tmp_path)

    eps = storage.list_episodes(tmp_path, secret)
    assert len(eps) == 1
    assert eps[0]["status"] == "failed"
    assert "subscription" in eps[0]["error"]
    assert "developer.mozilla" not in eps[0]["error"]


def test_synthesize_writes_audio_file(monkeypatch, fake_openai, tmp_path):
    monkeypatch.setattr(ingest, "openai_client", fake_openai)
    out = tmp_path / "out.mp3"

    ingest.synthesize("hello world", "shimmer", out)

    assert out.read_bytes() == b"FAKEMP3"
    assert fake_openai.calls[0]["voice"] == "shimmer"
    assert fake_openai.calls[0]["input"] == "hello world"


def test_synthesize_long_text_calls_tts_for_each_chunk(
    monkeypatch, fake_openai, tmp_path,
):
    """Long input is chunked; synthesize calls TTS once per chunk and concatenates."""
    monkeypatch.setattr(ingest, "openai_client", fake_openai)
    one_sentence = "This is a sentence that takes up some text. "
    long_body = one_sentence * 200  # ~9000 chars
    out = tmp_path / "out.mp3"

    ingest.synthesize(long_body, "shimmer", out)

    # synthesize called the fake TTS multiple times
    assert len(fake_openai.calls) >= 2
    # Each call got a chunk under the limit
    for call in fake_openai.calls:
        assert len(call["input"]) <= ingest.TTS_CHAR_LIMIT
    # Written bytes are the concatenation of all the fake response bodies
    assert out.read_bytes() == fake_openai.audio_bytes * len(fake_openai.calls)


def test_synthesize_short_text_calls_tts_once(monkeypatch, fake_openai, tmp_path):
    """Body shorter than TTS_CHAR_LIMIT → single call, no chunking visible."""
    monkeypatch.setattr(ingest, "openai_client", fake_openai)
    out = tmp_path / "out.mp3"

    ingest.synthesize("Short body.", "shimmer", out)

    assert len(fake_openai.calls) == 1
    assert fake_openai.calls[0]["input"] == "Short body."
    assert out.read_bytes() == fake_openai.audio_bytes


def test_process_writes_episode_on_success(
    monkeypatch, fake_http, fake_openai, tmp_path,
):
    monkeypatch.setattr(ingest, "http_client", fake_http)
    monkeypatch.setattr(ingest, "openai_client", fake_openai)
    fake_http.responses["https://example.com/ok"] = FakeResponse(
        status_code=200, text=HTML_SAMPLE,
    )

    secret = storage.create_user(tmp_path)
    ingest.process("https://example.com/ok", secret, tmp_path)

    eps = storage.list_episodes(tmp_path, secret)
    assert len(eps) == 1
    assert eps[0]["has_audio"] is True
    assert "On Time" in eps[0]["title"]


def test_process_writes_failure_on_extraction_error(
    monkeypatch, fake_http, fake_openai, tmp_path,
):
    monkeypatch.setattr(ingest, "http_client", fake_http)
    monkeypatch.setattr(ingest, "openai_client", fake_openai)
    fake_http.responses["https://example.com/bad"] = FakeResponse(
        status_code=500,
    )

    secret = storage.create_user(tmp_path)
    ingest.process("https://example.com/bad", secret, tmp_path)

    eps = storage.list_episodes(tmp_path, secret)
    assert len(eps) == 1
    assert eps[0]["has_audio"] is False
    assert eps[0]["error"]


def test_process_writes_pending_then_ready(
    monkeypatch, fake_http, fake_openai, tmp_path,
):
    monkeypatch.setattr(ingest, "http_client", fake_http)
    monkeypatch.setattr(ingest, "openai_client", fake_openai)
    fake_http.responses["https://example.com/p"] = FakeResponse(
        status_code=200, text=HTML_SAMPLE,
    )

    secret = storage.create_user(tmp_path)

    # Observe pending state by hooking fetch_article — at the moment fetch
    # is called, the pending record must already exist.
    observed_status_during_fetch = []
    real_fetch = ingest.fetch_article
    def observing_fetch(url):
        eps = storage.list_episodes(tmp_path, secret)
        observed_status_during_fetch.append(
            [e.get("status") for e in eps]
        )
        return real_fetch(url)
    monkeypatch.setattr(ingest, "fetch_article", observing_fetch)

    ingest.process("https://example.com/p", secret, tmp_path)

    # During fetch: exactly one pending record existed.
    assert observed_status_during_fetch == [["pending"]]
    # After process: exactly one record, promoted to ready.
    eps = storage.list_episodes(tmp_path, secret)
    assert len(eps) == 1
    assert eps[0]["status"] == "ready"


def test_fetch_title_extracts_from_html(monkeypatch, fake_http):
    fake_http.responses["https://example.com/x"] = FakeResponse(
        status_code=200,
        text="<html><head><title>Hello World</title></head><body>x</body></html>",
    )
    monkeypatch.setattr(ingest, "http_client", fake_http)

    assert ingest.fetch_title("https://example.com/x") == "Hello World"


def test_fetch_title_returns_none_on_http_error(monkeypatch, fake_http):
    fake_http.responses["https://example.com/x"] = FakeResponse(status_code=500)
    monkeypatch.setattr(ingest, "http_client", fake_http)

    assert ingest.fetch_title("https://example.com/x") is None


def test_fetch_title_returns_none_when_no_title_tag(monkeypatch, fake_http):
    fake_http.responses["https://example.com/x"] = FakeResponse(
        status_code=200,
        text="<html><body>no title here</body></html>",
    )
    monkeypatch.setattr(ingest, "http_client", fake_http)

    assert ingest.fetch_title("https://example.com/x") is None


def test_fetch_title_strips_whitespace(monkeypatch, fake_http):
    fake_http.responses["https://example.com/x"] = FakeResponse(
        status_code=200,
        text="<html><head><title>  Padded Title  \n</title></head></html>",
    )
    monkeypatch.setattr(ingest, "http_client", fake_http)

    assert ingest.fetch_title("https://example.com/x") == "Padded Title"


def test_process_writes_description_from_body(
    monkeypatch, fake_http, fake_openai, tmp_path,
):
    monkeypatch.setattr(ingest, "http_client", fake_http)
    monkeypatch.setattr(ingest, "openai_client", fake_openai)
    fake_http.responses["https://example.com/d"] = FakeResponse(
        status_code=200, text=HTML_SAMPLE,
    )

    secret = storage.create_user(tmp_path)
    ingest.process("https://example.com/d", secret, tmp_path)

    eps = storage.list_episodes(tmp_path, secret)
    assert len(eps) == 1
    desc = eps[0].get("description")
    assert desc is not None
    assert len(desc) > 0
    # Description should contain text from the body (excerpt) — not just the URL
    assert "first paragraph" in desc.lower() or "substantive" in desc.lower()


def test_chunk_text_short_body_returns_one_chunk():
    body = "Short text under the limit."
    chunks = ingest.chunk_text(body, max_chars=4000)
    assert chunks == ["Short text under the limit."]


def test_chunk_text_splits_at_sentence_boundary():
    body = (
        "First sentence here. "
        "Second sentence here. "
        "Third sentence here."
    )
    chunks = ingest.chunk_text(body, max_chars=42)
    assert len(chunks) >= 2
    for c in chunks:
        assert len(c) <= 42
    assert "First sentence" in chunks[0]
    assert "Third sentence" in chunks[-1]


def test_chunk_text_falls_back_to_word_boundary_when_no_sentences():
    body = "one two three four five six seven eight nine ten eleven twelve"
    chunks = ingest.chunk_text(body, max_chars=20)
    assert len(chunks) >= 2
    for c in chunks:
        assert len(c) <= 20
        assert not c.endswith("-")
    combined = " ".join(chunks).split()
    original = body.split()
    assert combined == original


def test_chunk_text_handles_body_longer_than_two_chunks():
    body = " ".join([f"Sentence number {i} here." for i in range(1, 10)])
    chunks = ingest.chunk_text(body, max_chars=100)
    assert len(chunks) >= 2
    for c in chunks:
        assert len(c) <= 100


def test_chunk_text_drops_empty_chunks():
    """Trailing whitespace shouldn't create an empty final chunk."""
    body = "Real content here.   "
    chunks = ingest.chunk_text(body, max_chars=4000)
    assert all(c.strip() for c in chunks)
    assert len(chunks) == 1


def test_process_fails_when_extraction_is_a_teaser(
    monkeypatch, fake_http, fake_openai, tmp_path,
):
    """A paywall shell (e.g. nytimes.com without subscriber cookies) yields a
    page where only a teaser is extractable. Fail loudly instead of narrating
    20 seconds of intro as if it were the whole article."""
    monkeypatch.setattr(ingest, "http_client", fake_http)
    monkeypatch.setattr(ingest, "openai_client", fake_openai)
    teaser_html = (
        "<!doctype html><html><head><title>Teaser</title></head>"
        "<body><article><h1>Teaser</h1>"
        "<p>The opening sentence of a gated article.</p>"
        "<p>Subscribe to keep reading.</p>"
        "</article></body></html>"
    )
    fake_http.responses["https://example.com/gated"] = FakeResponse(
        status_code=200, text=teaser_html,
    )

    secret = storage.create_user(tmp_path)
    ingest.process("https://example.com/gated", secret, tmp_path)

    # No TTS calls were made (we bailed before synthesize)
    assert len(fake_openai.calls) == 0
    eps = storage.list_episodes(tmp_path, secret)
    assert len(eps) == 1
    assert eps[0]["status"] == "failed"
    assert "paywalled" in eps[0]["error"]


def _huge_html(target_chars: int) -> str:
    """HTML whose extracted body comfortably exceeds target_chars.

    Extraction trims (readability/trafilatura drop markup and can drop
    fragments), so overshoot by ~10 paragraphs; tests that need a body
    *over* a cap must assert on the extracted length, not the HTML length.
    """
    sentence = "This sentence is very long and detailed and exists "  # 52 chars
    paragraph = "<p>" + (sentence * 50) + "</p>"  # 2,600 chars of text
    n = target_chars // 2600 + 10
    return (
        "<!doctype html><html><head><title>Huge</title></head>"
        "<body><article><h1>Big</h1>"
        + (paragraph * n)
        + "</article></body></html>"
    )


def test_process_writes_failure_when_body_exceeds_cap(
    monkeypatch, fake_http, fake_openai, tmp_path,
):
    """Bodies > MAX_BODY_CHARS fail with a clear error, no TTS calls made.

    Body size derives from the constant so this keeps testing the boundary
    when the cap changes."""
    monkeypatch.setattr(ingest, "http_client", fake_http)
    monkeypatch.setattr(ingest, "openai_client", fake_openai)

    fake_http.responses["https://example.com/huge"] = FakeResponse(
        status_code=200, text=_huge_html(ingest.MAX_BODY_CHARS),
    )

    # Precondition: the *extracted* body really is over the cap.
    _, body = ingest.fetch_article("https://example.com/huge")
    assert len(body) > ingest.MAX_BODY_CHARS

    secret = storage.create_user(tmp_path)
    ingest.process("https://example.com/huge", secret, tmp_path)

    # No TTS calls were made (we bailed before synthesize)
    assert len(fake_openai.calls) == 0
    eps = storage.list_episodes(tmp_path, secret)
    assert len(eps) == 1
    assert eps[0]["status"] == "failed"
    assert "too long" in eps[0]["error"].lower()


def test_process_succeeds_at_near_cap_length(
    monkeypatch, fake_http, fake_openai, tmp_path,
):
    """A long article just under MAX_BODY_CHARS processes to a ready episode
    across multiple TTS batches. The cap was lowered from 500k to 100k to bound
    per-episode cost (see app.AGENT_FEED_CHAR_BUDGET); articles longer than that
    are now rejected by test_process_writes_failure_when_body_exceeds_cap."""
    monkeypatch.setattr(ingest, "http_client", fake_http)
    monkeypatch.setattr(ingest, "openai_client", fake_openai)

    fake_http.responses["https://example.com/long"] = FakeResponse(
        status_code=200, text=_huge_html(55_000),
    )
    _, body = ingest.fetch_article("https://example.com/long")
    assert 50_000 < len(body) < ingest.MAX_BODY_CHARS

    secret = storage.create_user(tmp_path)
    ingest.process("https://example.com/long", secret, tmp_path)

    eps = storage.list_episodes(tmp_path, secret)
    assert len(eps) == 1
    assert eps[0]["status"] == "ready"
    assert eps[0]["has_audio"]
    # Spans more than one synthesize batch (TTS_MAX_PARALLEL).
    assert len(fake_openai.calls) > ingest.TTS_MAX_PARALLEL
    # The synthesized character count is recorded for the per-feed budget.
    assert eps[0]["chars"] == len(body)


def test_synthesize_preserves_chunk_order_under_parallelism(monkeypatch, tmp_path):
    """When TTS calls complete out of order, output bytes are still in input order.

    Monkey-patches chunk_text to return a known list (bypassing chunking heuristics)
    so we can directly verify that synthesize concatenates in INPUT order even when
    later chunks finish their TTS call first.
    """
    import time

    # Force chunk_text to return three known inputs.
    known_chunks = ["alpha", "bravo", "charlie"]
    monkeypatch.setattr(ingest, "chunk_text", lambda body, max_chars: known_chunks)

    # Fake TTS: returns the input text as bytes, but sleeps inversely to chunk index
    # so the FIRST input finishes LAST (forcing out-of-order completion).
    class OrderingFake:
        def __init__(self):
            self.calls = []
        @property
        def audio(self):
            return self
        @property
        def speech(self):
            return self
        def create(self, *, model, voice, input):
            self.calls.append(input)
            idx = known_chunks.index(input)
            # Earlier chunks sleep longer → finish later
            time.sleep(0.05 * (len(known_chunks) - idx))
            return type("R", (), {"content": input.encode("utf-8")})()

    monkeypatch.setattr(ingest, "openai_client", OrderingFake())
    out = tmp_path / "out.mp3"

    ingest.synthesize("any body", "shimmer", out)

    # Bytes must be in INPUT order (alpha, bravo, charlie), not completion order
    # (charlie finished first, alpha finished last).
    assert out.read_bytes() == b"alphabravocharlie"


def test_synthesize_bounds_parallelism(monkeypatch, tmp_path):
    """With more chunks than TTS_MAX_PARALLEL, peak in-flight TTS calls stay
    at or under the bound, and output bytes stay in input order."""
    import threading
    import time

    known_chunks = [f"chunk-{i:02d}" for i in range(20)]
    monkeypatch.setattr(ingest, "chunk_text", lambda body, max_chars: known_chunks)

    class ConcurrencyFake:
        def __init__(self):
            self.lock = threading.Lock()
            self.in_flight = 0
            self.peak = 0
        @property
        def audio(self):
            return self
        @property
        def speech(self):
            return self
        def create(self, *, model, voice, input):
            with self.lock:
                self.in_flight += 1
                self.peak = max(self.peak, self.in_flight)
            time.sleep(0.05)  # hold the slot so overlap is observable
            with self.lock:
                self.in_flight -= 1
            return type("R", (), {"content": input.encode("utf-8")})()

    fake = ConcurrencyFake()
    monkeypatch.setattr(ingest, "openai_client", fake)
    out = tmp_path / "out.mp3"

    ingest.synthesize("any body", "shimmer", out)

    assert fake.peak <= ingest.TTS_MAX_PARALLEL
    assert out.read_bytes() == b"".join(c.encode("utf-8") for c in known_chunks)


def test_process_writes_total_chunks_before_synthesize(
    monkeypatch, fake_http, fake_openai, tmp_path,
):
    """process() must write total_chunks to the pending record BEFORE calling synthesize,
    so the polling endpoint can pick it up while the worker is still running."""
    monkeypatch.setattr(ingest, "http_client", fake_http)
    monkeypatch.setattr(ingest, "openai_client", fake_openai)
    fake_http.responses["https://example.com/t"] = FakeResponse(
        status_code=200, text=HTML_SAMPLE,
    )

    secret = storage.create_user(tmp_path)

    # Monkey-patch synthesize to observe storage at the moment it's called.
    # At that moment the pending record MUST have total_chunks set.
    observed_total_chunks = []
    real_synthesize = ingest.synthesize
    def observing_synthesize(text, voice, out_path):
        eps = storage.list_episodes(tmp_path, secret)
        # Find the pending row for our URL and capture its total_chunks
        for e in eps:
            if e.get("status") == "pending" and e.get("url") == "https://example.com/t":
                observed_total_chunks.append(e.get("total_chunks"))
                break
        return real_synthesize(text, voice, out_path)
    monkeypatch.setattr(ingest, "synthesize", observing_synthesize)

    ingest.process("https://example.com/t", secret, tmp_path)

    # synthesize was called once, and at that moment total_chunks was a positive int
    assert len(observed_total_chunks) == 1
    assert observed_total_chunks[0] is not None
    assert observed_total_chunks[0] >= 1


def test_process_failed_synthesis_leaves_no_audio_files(
    monkeypatch, fake_http, tmp_path,
):
    """A TTS failure mid-stream leaves no .mp3 and no .mp3.tmp; the episode
    is recorded as failed."""
    monkeypatch.setattr(ingest, "http_client", fake_http)
    fake_http.responses["https://example.com/boom"] = FakeResponse(
        status_code=200, text=HTML_SAMPLE,
    )

    class ExplodingFake:
        @property
        def audio(self):
            return self
        @property
        def speech(self):
            return self
        def create(self, **kwargs):
            raise RuntimeError("tts exploded")

    monkeypatch.setattr(ingest, "openai_client", ExplodingFake())

    secret = storage.create_user(tmp_path)
    ingest.process("https://example.com/boom", secret, tmp_path)

    eps = storage.list_episodes(tmp_path, secret)
    assert len(eps) == 1
    assert eps[0]["status"] == "failed"
    user_dir = tmp_path / secret
    assert list(user_dir.glob("*.mp3")) == []
    assert list(user_dir.glob("*.tmp")) == []


def test_process_narrates_supplied_text(monkeypatch, fake_openai, tmp_path):
    monkeypatch.setattr(ingest, "openai_client", fake_openai)
    secret = storage.create_user(tmp_path)

    ingest.process(
        "", secret, tmp_path,
        text="This is the full body of an emailed newsletter, narrated as-is.",
        title="My Newsletter",
    )

    eps = storage.list_episodes(tmp_path, secret)
    assert len(eps) == 1
    assert eps[0]["status"] == "ready"
    assert eps[0]["has_audio"] is True
    assert eps[0]["title"] == "My Newsletter"
    assert eps[0]["url"] == ""          # no source link
    # The supplied text (not a fetched body) was sent to TTS.
    assert "emailed newsletter" in fake_openai.calls[0]["input"]


def test_process_text_skips_fetch_and_min_guard(monkeypatch, fake_openai, tmp_path):
    monkeypatch.setattr(ingest, "openai_client", fake_openai)
    # If text mode ever fetches, this explodes the test.
    def boom(*a, **k):
        raise AssertionError("text mode must not fetch")
    monkeypatch.setattr(ingest, "fetch_article", boom)
    secret = storage.create_user(tmp_path)

    # Body far below MIN_BODY_CHARS (600). URL mode would reject this as a
    # teaser; text mode narrates it.
    ingest.process("", secret, tmp_path, text="A short note.", title="Note")

    eps = storage.list_episodes(tmp_path, secret)
    assert eps[0]["status"] == "ready"


def test_process_text_stores_optional_source_url(monkeypatch, fake_openai, tmp_path):
    monkeypatch.setattr(ingest, "openai_client", fake_openai)
    secret = storage.create_user(tmp_path)

    ingest.process(
        "https://src.example/post", secret, tmp_path,
        text="Body text to narrate.", title="T",
    )

    eps = storage.list_episodes(tmp_path, secret)
    assert eps[0]["url"] == "https://src.example/post"


def test_process_text_over_max_fails(monkeypatch, fake_openai, tmp_path):
    monkeypatch.setattr(ingest, "openai_client", fake_openai)
    secret = storage.create_user(tmp_path)

    ingest.process(
        "", secret, tmp_path,
        text="x" * (ingest.MAX_BODY_CHARS + 1), title="Too long",
    )

    eps = storage.list_episodes(tmp_path, secret)
    assert eps[0]["status"] == "failed"
    assert "too long" in eps[0]["error"].lower()


def test_paywall_error_explains_the_limit_without_overpromising(monkeypatch, fake_http):
    """A gift link unlocks some sites but NOT nytimes.com: measured 2026-08-19,
    a main-site gift link serves the same 1,713-character preview. Say so
    rather than sending the reader to spend one."""
    fake_http.responses["https://www.nytimes.com/gated"] = FakeResponse(
        status_code=200, text=_paywalled_html(paragraphs=12, marker=JSONLD_PAYWALL),
    )
    monkeypatch.setattr(ingest, "http_client", fake_http)

    with pytest.raises(ingest.FetchError) as exc_info:
        ingest.fetch_article("https://www.nytimes.com/gated")

    msg = str(exc_info.value)
    assert "gift link" in msg
    assert "not nytimes.com" in msg


def test_subscription_http_error_points_at_gift_link():
    """A 403 can be a bot block or a subscription wall, and a gift link is the
    reader's only lever on either. It is NOT known to be futile: verified
    2026-08-19, nytimes.com/athletic articles fetch fine with or without a
    gift code, while main-site article pages 403. Don't tell people not to
    try it."""
    msg = ingest._friendly_http_error(403, "https://www.nytimes.com/gated")
    assert "gift link" in msg
    # Non-subscription failures stay unchanged.
    assert "gift link" not in ingest._friendly_http_error(404, "https://x.example/a")
    assert "gift link" not in ingest._friendly_http_error(500, "https://x.example/a")
