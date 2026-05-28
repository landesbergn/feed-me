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
