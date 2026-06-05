"""Agent API tests: POST/GET /u/{secret}/episodes*, the daily cap, and the
agent-facing docs routes. See docs/superpowers/specs/2026-06-05-for-agents.html."""
import json
import time

import analytics
import storage
from tests.conftest import FakeResponse

# Long enough to clear ingest's MIN_BODY_CHARS teaser guard.
ARTICLE_HTML = """<!doctype html><html><head><title>On Time</title></head>
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


def make_feed(client) -> str:
    """Create a feed WITHOUT linking the client's cookie jar to it.
    (POST /create sets no cookie; only GET /u/{secret} does.)"""
    create = client.post("/create", follow_redirects=False)
    return create.headers["location"].split("/u/")[1]


def wire_fake_pipeline(monkeypatch, fake_http, fake_openai):
    """Run the (faked) ingest pipeline synchronously inside the request, so
    tests observe finished episodes: a via-drop at finalization fails here."""
    import app as app_module
    import ingest
    monkeypatch.setattr(ingest, "http_client", fake_http)
    monkeypatch.setattr(ingest, "openai_client", fake_openai)
    monkeypatch.setattr(
        app_module, "spawn_ingest",
        lambda url, secret, data_dir, slug: ingest.process(
            url, secret, data_dir, slug=slug
        ),
    )


def test_post_episode_happy_path(client, monkeypatch, fake_http, fake_openai, tmp_path):
    secret = make_feed(client)
    fake_http.responses["https://example.com/a"] = FakeResponse(
        status_code=200, text=ARTICLE_HTML,
    )
    wire_fake_pipeline(monkeypatch, fake_http, fake_openai)

    resp = client.post(
        f"/u/{secret}/episodes", json={"url": "https://example.com/a"},
    )

    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "pending"
    assert body["title"] == "On Time"
    assert body["status_url"] == f"https://test.local/u/{secret}/episodes/{body['slug']}"
    assert body["feed_page"] == f"https://test.local/u/{secret}"
    assert body["remaining"] == 4

    # The pipeline ran synchronously, so the episode is already finished;
    # via must survive finalization (pins the Task 1 carry-over end to end).
    record = json.loads((tmp_path / secret / f"{body['slug']}.json").read_text())
    assert "pending" not in record and "error" not in record   # it IS ready
    assert record["via"] == "agent"
    assert (tmp_path / secret / f"{body['slug']}.mp3").exists()


def test_post_episode_sets_no_cookie(client, monkeypatch, fake_http, fake_openai):
    secret = make_feed(client)
    fake_http.responses["https://example.com/a"] = FakeResponse(
        status_code=200, text=ARTICLE_HTML,
    )
    wire_fake_pipeline(monkeypatch, fake_http, fake_openai)

    resp = client.post(f"/u/{secret}/episodes", json={"url": "https://example.com/a"})

    assert resp.status_code == 202
    assert "set-cookie" not in resp.headers


def test_post_episode_ignores_session_cookie(
    client, monkeypatch, fake_http, fake_openai, tmp_path,
):
    """No ambient authority: the path secret decides the target feed; the
    fm_session cookie must be ignored entirely."""
    secret_a = make_feed(client)
    secret_b = make_feed(client)
    client.get(f"/u/{secret_b}")          # cookie now points at feed B
    fake_http.responses["https://example.com/a"] = FakeResponse(
        status_code=200, text=ARTICLE_HTML,
    )
    wire_fake_pipeline(monkeypatch, fake_http, fake_openai)

    client.post(f"/u/{secret_a}/episodes", json={"url": "https://example.com/a"})

    in_a = [e for e in storage.list_episodes(tmp_path, secret_a) if e.get("via") == "agent"]
    in_b = [e for e in storage.list_episodes(tmp_path, secret_b) if e.get("via") == "agent"]
    assert len(in_a) == 1
    assert len(in_b) == 0


def test_post_episode_unknown_feed_404(client):
    resp = client.post("/u/nope/episodes", json={"url": "https://example.com/a"})
    assert resp.status_code == 404
    assert resp.json()["error"] == "not_found"


def test_post_episode_invalid_json_400(client, tmp_path):
    secret = make_feed(client)
    resp = client.post(
        f"/u/{secret}/episodes",
        content=b"not json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_request"
    assert len(storage.list_episodes(tmp_path, secret)) == 1   # welcome only


def test_post_episode_missing_url_field_400(client, tmp_path):
    secret = make_feed(client)
    resp = client.post(f"/u/{secret}/episodes", json={"link": "https://example.com/a"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_request"
    assert len(storage.list_episodes(tmp_path, secret)) == 1   # welcome only


def test_post_episode_bad_scheme_400(client, tmp_path):
    secret = make_feed(client)
    resp = client.post(f"/u/{secret}/episodes", json={"url": "ftp://example.com/a"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_url"
    assert len(storage.list_episodes(tmp_path, secret)) == 1   # welcome only


def test_post_episode_records_agent_analytics(
    client, monkeypatch, fake_http, fake_openai, tmp_path,
):
    secret = make_feed(client)
    fake_http.responses["https://example.com/a"] = FakeResponse(
        status_code=200, text=ARTICLE_HTML,
    )
    wire_fake_pipeline(monkeypatch, fake_http, fake_openai)

    client.post(f"/u/{secret}/episodes", json={"url": "https://example.com/a"})

    db = tmp_path / "_analytics" / "analytics.db"
    shared = [e for e in analytics.all_events(db) if e["event"] == "article_shared"]
    assert len(shared) == 1
    props = json.loads(shared[0]["props"])
    assert props["via"] == "agent"
    assert props["url"] == "https://example.com/a"
    assert shared[0]["feed_hash"] == analytics.feed_hash(secret)


def test_agent_cap_blocks_sixth_share(client, monkeypatch, fake_http, fake_openai):
    """Five COMPLETED agent shares block the sixth with 429. Episodes run to
    completion via the fake pipeline, so this validates daily semantics
    (via surviving finalization), not concurrent-pending counting."""
    secret = make_feed(client)
    wire_fake_pipeline(monkeypatch, fake_http, fake_openai)

    remaining_seen = []
    for i in range(5):
        url = f"https://example.com/a{i}"
        fake_http.responses[url] = FakeResponse(status_code=200, text=ARTICLE_HTML)
        resp = client.post(f"/u/{secret}/episodes", json={"url": url})
        assert resp.status_code == 202
        remaining_seen.append(resp.json()["remaining"])
    assert remaining_seen == [4, 3, 2, 1, 0]

    resp = client.post(f"/u/{secret}/episodes", json={"url": "https://example.com/a5"})
    assert resp.status_code == 429
    assert resp.json()["error"] == "rate_limited"
    assert int(resp.headers["Retry-After"]) > 0


def test_agent_cap_ignores_episodes_older_than_window(
    client, monkeypatch, fake_http, fake_openai, tmp_path,
):
    secret = make_feed(client)
    wire_fake_pipeline(monkeypatch, fake_http, fake_openai)

    # Five agent episodes, all outside the 24h window (ts rewritten on disk).
    old_ts = int(time.time()) - 90000
    for i in range(5):
        slug = storage.write_pending_episode(
            tmp_path, secret, source_url=f"https://ex.com/old{i}", via="agent",
        )
        path = tmp_path / secret / f"{slug}.json"
        record = json.loads(path.read_text())
        record["ts"] = old_ts
        path.write_text(json.dumps(record))

    fake_http.responses["https://example.com/new"] = FakeResponse(
        status_code=200, text=ARTICLE_HTML,
    )
    resp = client.post(f"/u/{secret}/episodes", json={"url": "https://example.com/new"})
    assert resp.status_code == 202


def test_shortcut_shares_do_not_count_toward_cap(
    client, monkeypatch, fake_http, fake_openai,
):
    secret = make_feed(client)
    client.get(f"/u/{secret}")     # link cookie for the Shortcut path
    wire_fake_pipeline(monkeypatch, fake_http, fake_openai)

    # A human share first...
    fake_http.responses["https://example.com/human"] = FakeResponse(
        status_code=200, text=ARTICLE_HTML,
    )
    assert client.get("/share?url=https://example.com/human").status_code == 200

    # ...leaves all five agent slots available.
    for i in range(5):
        url = f"https://example.com/a{i}"
        fake_http.responses[url] = FakeResponse(status_code=200, text=ARTICLE_HTML)
        assert client.post(f"/u/{secret}/episodes", json={"url": url}).status_code == 202


def test_agent_cap_does_not_block_shortcut(client, monkeypatch, fake_http, fake_openai):
    """Human sharing stays uncapped: with the agent window full, GET /share
    (cookie path) still works."""
    secret = make_feed(client)
    client.get(f"/u/{secret}")     # link cookie for the Shortcut path
    wire_fake_pipeline(monkeypatch, fake_http, fake_openai)

    for i in range(5):
        url = f"https://example.com/a{i}"
        fake_http.responses[url] = FakeResponse(status_code=200, text=ARTICLE_HTML)
        assert client.post(f"/u/{secret}/episodes", json={"url": url}).status_code == 202

    fake_http.responses["https://example.com/human"] = FakeResponse(
        status_code=200, text=ARTICLE_HTML,
    )
    resp = client.get("/share?url=https://example.com/human")
    assert resp.status_code == 200
    assert "Added" in resp.text


def test_failed_agent_episodes_count_toward_cap(
    client, monkeypatch, fake_http, fake_openai,
):
    """Failed ingests consumed work; an error-looping agent must still hit
    the cap."""
    secret = make_feed(client)
    wire_fake_pipeline(monkeypatch, fake_http, fake_openai)

    for i in range(5):
        url = f"https://example.com/dead{i}"
        fake_http.responses[url] = FakeResponse(status_code=500)
        resp = client.post(f"/u/{secret}/episodes", json={"url": url})
        assert resp.status_code == 202     # accepted; ingest then fails

    resp = client.post(f"/u/{secret}/episodes", json={"url": "https://example.com/ok"})
    assert resp.status_code == 429


def test_episode_status_ready(client, monkeypatch, fake_http, fake_openai):
    secret = make_feed(client)
    fake_http.responses["https://example.com/a"] = FakeResponse(
        status_code=200, text=ARTICLE_HTML,
    )
    wire_fake_pipeline(monkeypatch, fake_http, fake_openai)
    slug = client.post(
        f"/u/{secret}/episodes", json={"url": "https://example.com/a"},
    ).json()["slug"]

    resp = client.get(f"/u/{secret}/episodes/{slug}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["slug"] == slug
    assert body["status"] == "ready"
    assert body["audio_url"] == f"https://test.local/u/{secret}/audio/{slug}.mp3"
    assert body["error"] is None
    assert "set-cookie" not in resp.headers


def test_episode_status_pending(client, monkeypatch, fake_http):
    import app as app_module
    import ingest
    secret = make_feed(client)
    monkeypatch.setattr(ingest, "http_client", fake_http)            # title fetch
    monkeypatch.setattr(app_module, "spawn_ingest", lambda *a, **k: None)
    fake_http.responses["https://example.com/a"] = FakeResponse(
        status_code=200, text=ARTICLE_HTML,
    )
    slug = client.post(
        f"/u/{secret}/episodes", json={"url": "https://example.com/a"},
    ).json()["slug"]

    body = client.get(f"/u/{secret}/episodes/{slug}").json()
    assert body["status"] == "pending"
    assert "audio_url" not in body


def test_episode_status_failed(client, monkeypatch, fake_http, fake_openai):
    secret = make_feed(client)
    fake_http.responses["https://example.com/dead"] = FakeResponse(status_code=500)
    wire_fake_pipeline(monkeypatch, fake_http, fake_openai)
    slug = client.post(
        f"/u/{secret}/episodes", json={"url": "https://example.com/dead"},
    ).json()["slug"]

    body = client.get(f"/u/{secret}/episodes/{slug}").json()
    assert body["status"] == "failed"
    assert body["error"]


def test_episode_status_unknown_slug_404(client):
    secret = make_feed(client)
    resp = client.get(f"/u/{secret}/episodes/zzzzzzzzzzz")
    assert resp.status_code == 404
    assert resp.json()["error"] == "not_found"


def test_episode_status_malformed_slug_404(client):
    secret = make_feed(client)
    resp = client.get(f"/u/{secret}/episodes/bad.slug")   # '.' fails SLUG_RE
    assert resp.status_code == 404


def test_episode_status_unknown_feed_404(client):
    resp = client.get("/u/nope/episodes/abc123")
    assert resp.status_code == 404


def test_agents_md_served_as_markdown(client):
    resp = client.get("/AGENTS.md")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    assert "https://test.local/u/" in resp.text       # APP_BASE_URL substituted
    assert "{base}" not in resp.text                  # nothing left unsubstituted
    assert "5 episodes" in resp.text                  # the cap is documented
    assert "Retry-After" in resp.text
    assert "—" not in resp.text                       # house style: no em-dashes


def test_llms_txt_points_at_agents_md(client):
    resp = client.get("/llms.txt")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert "https://test.local/AGENTS.md" in resp.text
