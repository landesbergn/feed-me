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


def test_settings_page_inlines_agent_prompt(client):
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]

    resp = client.get(f"/u/{secret}")

    assert resp.status_code == 200
    # The agent prompt is inline in the "For your agent" tab, not a separate page.
    assert "I have a Feed Me podcast feed" in resp.text
    assert f"My feed page: https://test.local/u/{secret}." in resp.text
    assert "https://test.local/AGENTS.md" in resp.text
    assert "click to copy" in resp.text
    # The cap detail and privacy line stay out of the prompt (cap is in AGENTS.md).
    assert "5 episodes" not in resp.text
    assert "Keep this private" not in resp.text


def test_settings_page_agent_prompt_shows_after_setup(client, monkeypatch, fake_http, fake_openai):
    """The inline prompt renders in BOTH page states; this covers the
    episodes-leading (setup_done) state, the other test covers fresh-feed."""
    secret = make_feed(client)
    fake_http.responses["https://example.com/a"] = FakeResponse(
        status_code=200, text=ARTICLE_HTML,
    )
    wire_fake_pipeline(monkeypatch, fake_http, fake_openai)
    client.post(f"/u/{secret}/episodes", json={"url": "https://example.com/a"})

    resp = client.get(f"/u/{secret}")

    assert "I have a Feed Me podcast feed" in resp.text
    assert "click to copy" in resp.text


def test_agents_page_route_removed(client):
    """The standalone agents page was folded into the feed page's toggle."""
    secret = make_feed(client)
    assert client.get(f"/u/{secret}/agents").status_code == 404


def test_landing_page_advertises_agents(client):
    resp = client.get("/")

    assert resp.status_code == 200
    assert "or have your agent send things" in resp.text
    # The landing bubble is decorative now: no link to AGENTS.md.
    assert "/AGENTS.md" not in resp.text


def test_settings_page_has_share_toggle(client):
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]

    resp = client.get(f"/u/{secret}")

    assert resp.status_code == 200
    assert "For you" in resp.text
    assert "For your agent" in resp.text
    # The agent prompt is inline inside the "For your agent" tab.
    assert "I have a Feed Me podcast feed" in resp.text


# --- GET /u/{secret}/episodes : list / confirm -------------------------------

def test_list_episodes_returns_feed_info_and_episodes(
    client, monkeypatch, fake_http, fake_openai,
):
    secret = make_feed(client)
    fake_http.responses["https://example.com/a"] = FakeResponse(
        status_code=200, text=ARTICLE_HTML,
    )
    wire_fake_pipeline(monkeypatch, fake_http, fake_openai)
    slug = client.post(
        f"/u/{secret}/episodes", json={"url": "https://example.com/a"},
    ).json()["slug"]

    resp = client.get(f"/u/{secret}/episodes")

    assert resp.status_code == 200
    assert "set-cookie" not in resp.headers          # path-secret auth, no cookie
    body = resp.json()
    assert body["feed_page"] == f"https://test.local/u/{secret}"
    assert body["feed_url"] == f"https://test.local/u/{secret}/feed.xml"
    assert body["voice"] in storage.ALLOWED_VOICES
    assert body["remaining"] == 4                    # one agent share used
    shared = next(e for e in body["episodes"] if e["slug"] == slug)
    assert shared["status"] == "ready"
    assert shared["title"] == "On Time"
    assert shared["ts"]
    assert shared["audio_url"] == f"https://test.local/u/{secret}/audio/{slug}.mp3"


def test_list_episodes_failed_has_error_and_no_audio(
    client, monkeypatch, fake_http, fake_openai,
):
    secret = make_feed(client)
    fake_http.responses["https://example.com/dead"] = FakeResponse(status_code=500)
    wire_fake_pipeline(monkeypatch, fake_http, fake_openai)
    slug = client.post(
        f"/u/{secret}/episodes", json={"url": "https://example.com/dead"},
    ).json()["slug"]

    body = client.get(f"/u/{secret}/episodes").json()
    failed = next(e for e in body["episodes"] if e["slug"] == slug)
    assert failed["status"] == "failed"
    assert failed["error"]
    assert "audio_url" not in failed


def test_list_episodes_hides_internal_fields(
    client, monkeypatch, fake_http, fake_openai,
):
    secret = make_feed(client)
    fake_http.responses["https://example.com/a"] = FakeResponse(
        status_code=200, text=ARTICLE_HTML,
    )
    wire_fake_pipeline(monkeypatch, fake_http, fake_openai)
    client.post(f"/u/{secret}/episodes", json={"url": "https://example.com/a"})

    body = client.get(f"/u/{secret}/episodes").json()
    assert body["episodes"]
    for ep in body["episodes"]:
        # "url" is the real source-URL key in stored records (storage writes
        # it there; source_url is the kwarg name, not the stored key).
        for leaked in ("mtime", "audio_bytes", "has_audio", "url", "source_url", "via"):
            assert leaked not in ep


def test_list_episodes_unknown_feed_404(client):
    resp = client.get("/u/nope/episodes")
    assert resp.status_code == 404
    assert resp.json()["error"] == "not_found"


def test_list_episodes_remaining_tracks_cap(
    client, monkeypatch, fake_http, fake_openai,
):
    secret = make_feed(client)
    wire_fake_pipeline(monkeypatch, fake_http, fake_openai)
    for i in range(3):
        url = f"https://example.com/a{i}"
        fake_http.responses[url] = FakeResponse(status_code=200, text=ARTICLE_HTML)
        client.post(f"/u/{secret}/episodes", json={"url": url})

    body = client.get(f"/u/{secret}/episodes").json()
    assert body["remaining"] == 2                    # 5 cap - 3 used


def test_list_episodes_caps_at_twenty(client, tmp_path):
    secret = make_feed(client)
    # Welcome already seeded; add 25 more so the feed exceeds the cap.
    for i in range(25):
        storage.write_pending_episode(
            tmp_path, secret, source_url=f"https://ex.com/{i}", title=f"E{i}",
        )

    body = client.get(f"/u/{secret}/episodes").json()
    assert len(body["episodes"]) == 20


def test_agents_md_tells_agent_to_persist_feed(client):
    text = client.get("/AGENTS.md").text
    assert "Remember this feed" in text
    assert "durable memory" in text


def test_agents_md_forbids_guessing_the_feed(client):
    text = client.get("/AGENTS.md").text
    assert "ask the user" in text
    assert "Never guess" in text


def test_agents_md_documents_list_endpoint(client):
    text = client.get("/AGENTS.md").text
    assert "List the feed" in text
    # The list endpoint line, base substituted, terminated by newline so it
    # does not match the POST line or the per-slug poll line.
    assert "GET https://test.local/u/<secret>/episodes\n" in text


def test_settings_prompt_tells_agent_to_save_feed(client):
    secret = make_feed(client)
    resp = client.get(f"/u/{secret}")
    assert "Save my feed page so you don't have to ask again" in resp.text
