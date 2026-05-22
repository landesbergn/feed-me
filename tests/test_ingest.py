import pytest

import ingest
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


def test_synthesize_truncates_long_text(monkeypatch, fake_openai):
    monkeypatch.setattr(ingest, "openai_client", fake_openai)
    long = "x" * 10_000

    ingest.synthesize(long, "alloy")

    sent = fake_openai.calls[0]["input"]
    assert len(sent) <= ingest.TTS_CHAR_LIMIT
