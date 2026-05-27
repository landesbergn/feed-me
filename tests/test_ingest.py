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


def test_synthesize_truncates_long_text(monkeypatch, fake_openai):
    monkeypatch.setattr(ingest, "openai_client", fake_openai)
    long = "x" * 10_000

    ingest.synthesize(long, "alloy")

    sent = fake_openai.calls[0]["input"]
    assert len(sent) <= ingest.TTS_CHAR_LIMIT


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
