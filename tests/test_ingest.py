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
</article></body></html>"""


def test_fetch_article_returns_title_and_body(monkeypatch, fake_http):
    fake_http.responses["https://example.com/x"] = FakeResponse(
        status_code=200, text=HTML_SAMPLE,
    )
    monkeypatch.setattr(ingest, "http_client", fake_http)

    title, body = ingest.fetch_article("https://example.com/x")

    assert "On Time" in title
    assert "first paragraph" in body
    assert "more substantive" in body


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


def test_synthesize_returns_audio_bytes(monkeypatch, fake_openai):
    monkeypatch.setattr(ingest, "openai_client", fake_openai)

    audio = ingest.synthesize("hello world", "shimmer")

    assert audio == b"FAKEMP3"
    assert fake_openai.calls[0]["voice"] == "shimmer"
    assert fake_openai.calls[0]["input"] == "hello world"


def test_synthesize_long_text_calls_tts_for_each_chunk(monkeypatch, fake_openai):
    """Long input is chunked; synthesize calls TTS once per chunk and concatenates."""
    monkeypatch.setattr(ingest, "openai_client", fake_openai)
    one_sentence = "This is a sentence that takes up some text. "
    long_body = one_sentence * 200  # ~9000 chars

    audio = ingest.synthesize(long_body, "shimmer")

    # synthesize called the fake TTS multiple times
    assert len(fake_openai.calls) >= 2
    # Each call got a chunk under the limit
    for call in fake_openai.calls:
        assert len(call["input"]) <= ingest.TTS_CHAR_LIMIT
    # Returned bytes are the concatenation of all the fake response bodies
    assert audio == fake_openai.audio_bytes * len(fake_openai.calls)


def test_synthesize_short_text_calls_tts_once(monkeypatch, fake_openai):
    """Body shorter than TTS_CHAR_LIMIT → single call, no chunking visible."""
    monkeypatch.setattr(ingest, "openai_client", fake_openai)

    audio = ingest.synthesize("Short body.", "shimmer")

    assert len(fake_openai.calls) == 1
    assert fake_openai.calls[0]["input"] == "Short body."
    assert audio == fake_openai.audio_bytes


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


def test_process_writes_failure_when_body_exceeds_cap(
    monkeypatch, fake_http, fake_openai, tmp_path,
):
    """Bodies > MAX_BODY_CHARS fail with a clear error, no TTS calls made."""
    monkeypatch.setattr(ingest, "http_client", fake_http)
    monkeypatch.setattr(ingest, "openai_client", fake_openai)

    # Build HTML with a body that, after Readability extraction, is > 100k chars.
    huge_paragraph = "<p>" + ("This sentence is very long and detailed and exists " * 50) + "</p>"
    huge_html = (
        "<!doctype html><html><head><title>Huge</title></head>"
        "<body><article><h1>Big</h1>"
        + (huge_paragraph * 100)
        + "</article></body></html>"
    )
    fake_http.responses["https://example.com/huge"] = FakeResponse(
        status_code=200, text=huge_html,
    )

    secret = storage.create_user(tmp_path)
    ingest.process("https://example.com/huge", secret, tmp_path)

    # No TTS calls were made (we bailed before synthesize)
    assert len(fake_openai.calls) == 0
    eps = storage.list_episodes(tmp_path, secret)
    assert len(eps) == 1
    assert eps[0]["status"] == "failed"
    assert "too long" in eps[0]["error"].lower()


def test_synthesize_preserves_chunk_order_under_parallelism(monkeypatch):
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

    audio = ingest.synthesize("any body", "shimmer")

    # Bytes must be in INPUT order (alpha, bravo, charlie), not completion order
    # (charlie finished first, alpha finished last).
    assert audio == b"alphabravocharlie"


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
    def observing_synthesize(text, voice):
        eps = storage.list_episodes(tmp_path, secret)
        # Find the pending row for our URL and capture its total_chunks
        for e in eps:
            if e.get("status") == "pending" and e.get("url") == "https://example.com/t":
                observed_total_chunks.append(e.get("total_chunks"))
                break
        return real_synthesize(text, voice)
    monkeypatch.setattr(ingest, "synthesize", observing_synthesize)

    ingest.process("https://example.com/t", secret, tmp_path)

    # synthesize was called once, and at that moment total_chunks was a positive int
    assert len(observed_total_chunks) == 1
    assert observed_total_chunks[0] is not None
    assert observed_total_chunks[0] >= 1
