def test_healthz(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.text == "ok"


def test_landing_page_renders(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Get my feed" in response.text
    assert "feed me" in response.text.lower()
    # v1.1 regression guards
    assert "private" in response.text.lower()
    assert "Create your private podcast feed" in response.text


def test_post_create_redirects_to_user_settings(client):
    response = client.post("/create", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/u/")
    secret = response.headers["location"].split("/u/")[1]
    assert len(secret) >= 32


def test_post_create_makes_user_dir(client, tmp_path):
    response = client.post("/create", follow_redirects=False)
    secret = response.headers["location"].split("/u/")[1]

    # Settings file exists
    assert (tmp_path / secret / "settings.json").exists()

    # Welcome episode seeded: exactly one mp3 + one episode json
    user_dir = tmp_path / secret
    mp3s = list(user_dir.glob("*.mp3"))
    episode_jsons = [p for p in user_dir.glob("*.json") if p.name != "settings.json"]
    assert len(mp3s) == 1, f"expected 1 welcome mp3, found {len(mp3s)}"
    assert len(episode_jsons) == 1, f"expected 1 welcome json, found {len(episode_jsons)}"

    import json
    meta = json.loads(episode_jsons[0].read_text())
    assert meta["title"] == "Welcome to Feed Me"


def test_settings_404_for_unknown_user(client):
    response = client.get("/u/unknown_secret")
    assert response.status_code == 404


def test_pages_have_footer_credit(client):
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]
    for body in (client.get("/").text, client.get(f"/u/{secret}").text):
        assert "Built by" in body
        assert "noahlandesberg.com" in body


def test_og_image_serves(client):
    r = client.get("/og.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"


def test_landing_has_open_graph_tags(client):
    r = client.get("/")
    assert 'property="og:title"' in r.text
    assert 'property="og:image"' in r.text
    assert "/og.png" in r.text
    assert 'name="twitter:card"' in r.text


def test_share_status_reports_pending(client, tmp_path):
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]
    client.get(f"/u/{secret}")  # links this browser (sets fm_session)

    import storage
    slug = storage.write_pending_episode(
        tmp_path, secret, source_url="https://x.com/a", title="X",
    )
    r = client.get(f"/share/status?slug={slug}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "pending"
    assert body["ts"] is not None


def test_share_status_unknown_without_cookie(client):
    r = client.get("/share/status?slug=anything")
    assert r.status_code == 200
    assert r.json()["status"] == "unknown"


def test_settings_fresh_feed_shows_listen_card_before_episodes(client):
    # v3.34 (one-page merge): a brand-new feed leads with the subscribe-first
    # Listen card; iOS setup is always folded, even before the first share.
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]

    body = client.get(f"/u/{secret}").text
    assert "Set up" in body
    assert "Setup &amp; sharing" in body  # always folded now
    assert body.index("Put your feed in your podcast app") < body.index("Recent episodes")


def test_settings_prioritizes_episodes_once_real_article_shared(client, tmp_path):
    # After a real (non-welcome) episode exists, episodes lead and the Listen
    # card follows; setup stays folded under "Setup & sharing".
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]

    import storage
    storage.write_episode(
        tmp_path, secret, slug="real1", title="A Real Article",
        source_url="https://example.com/a", audio=b"MP3", description="x",
    )

    body = client.get(f"/u/{secret}").text
    assert "Setup &amp; sharing" in body  # instructions are folded
    assert body.index("Recent episodes") < body.index("Put your feed in your podcast app")
    # Episodes table also comes before the folded setup instructions.
    assert body.index("Recent episodes") < body.index("Install the iOS Shortcut")


def test_icon_routes_serve(client):
    # These all 404'd before v3.x — favicon + apple-touch icons now exist.
    for path in (
        "/favicon.ico",
        "/favicon-32.png",
        "/apple-touch-icon.png",
        "/apple-touch-icon-precomposed.png",
    ):
        r = client.get(path)
        assert r.status_code == 200, path


def test_settings_renders_for_known_user(client):
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]

    response = client.get(f"/u/{secret}")
    assert response.status_code == 200
    # v1.3 structure: three-phase layout
    assert "Set up" in response.text
    assert "Install Shortcut" in response.text
    assert "Add to Apple Podcasts" in response.text
    assert "Copy feed URL" in response.text
    assert "Share an article" in response.text
    assert "Feed Me" in response.text
    # Episode table headers
    assert "Recent episodes" in response.text
    # Settings drawer
    assert "Settings" in response.text
    # v3.0: no more paste flow — the ingest URL must NOT leak into the page
    assert f"/u/{secret}/ingest" not in response.text
    # v1.5: welcome episode pre-seeded on /create
    assert "Welcome to Feed Me" in response.text
    # v1.9: revised share sheet onboarding
    assert "More" in response.text  # the "Tap More ▼" instruction
    assert "Pin Feed Me" in response.text  # the new tip callout


def test_settings_lists_recent_episodes(client, tmp_path):
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]

    import storage
    storage.write_episode(tmp_path, secret, title="My Article",
                          source_url="https://example.com/a", audio=b"X")

    response = client.get(f"/u/{secret}")
    assert "My Article" in response.text
    assert "Ready" in response.text  # status chip


def test_settings_shows_pending_episode(client, tmp_path):
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]

    import storage
    storage.write_pending_episode(tmp_path, secret,
                                   source_url="https://example.com/p")

    response = client.get(f"/u/{secret}")
    assert "Pending" in response.text


def test_post_voice_updates_setting(client, tmp_path):
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]

    response = client.post(f"/u/{secret}/voice",
                           data={"voice": "alloy"},
                           follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == f"/u/{secret}"

    import storage
    assert storage.get_settings(tmp_path, secret)["voice"] == "alloy"


def test_post_voice_rejects_unknown(client):
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]

    response = client.post(f"/u/{secret}/voice",
                           data={"voice": "evil"},
                           follow_redirects=False)
    assert response.status_code == 400


def test_post_voice_404_for_unknown_user(client):
    response = client.post("/u/nonexistent/voice",
                           data={"voice": "alloy"},
                           follow_redirects=False)
    assert response.status_code == 404


def test_post_rotate_returns_new_secret_url(client, tmp_path):
    create = client.post("/create", follow_redirects=False)
    old = create.headers["location"].split("/u/")[1]

    response = client.post(f"/u/{old}/rotate", follow_redirects=False)
    assert response.status_code == 303
    new_path = response.headers["location"]
    assert new_path.startswith("/u/")
    new = new_path.split("/u/")[1]
    assert new != old

    import storage
    assert not storage.user_exists(tmp_path, old)
    assert storage.user_exists(tmp_path, new)


def test_old_ingest_route_gone(client):
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]
    # The per-user ingest route is deleted; the path no longer matches.
    response = client.get(f"/u/{secret}/ingest?url=")
    assert response.status_code == 404


def test_feed_xml_returns_valid_rss(client, tmp_path):
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]

    import storage
    storage.write_episode(tmp_path, secret, title="Test",
                          source_url="https://a", audio=b"X")

    response = client.get(f"/u/{secret}/feed.xml")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/rss+xml") \
        or response.headers["content-type"].startswith("application/xml")
    assert "<rss" in response.text
    assert "Test" in response.text


def test_feed_xml_404_for_unknown_user(client):
    response = client.get("/u/unknown/feed.xml")
    assert response.status_code == 404


def test_audio_streams_file(client, tmp_path):
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]

    import storage
    slug = storage.write_episode(tmp_path, secret, title="A",
                                  source_url="https://a", audio=b"MP3DATA")

    response = client.get(f"/u/{secret}/audio/{slug}.mp3")
    assert response.status_code == 200
    assert response.content == b"MP3DATA"
    assert response.headers["content-type"] == "audio/mpeg"


def test_audio_404_for_unknown_slug(client):
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]

    response = client.get(f"/u/{secret}/audio/missing.mp3")
    assert response.status_code == 404


def test_audio_404_for_unknown_user(client):
    response = client.get("/u/nope/audio/x.mp3")
    assert response.status_code == 404


def test_audio_rejects_path_traversal(client):
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]

    response = client.get(f"/u/{secret}/audio/..%2Fsettings.json")
    # The slug regex should reject this; either 404 or 422 is acceptable
    assert response.status_code in (404, 422)


def test_relative_time_just_now():
    import app
    assert app.relative_time(1_000_000, now=1_000_000) == "just now"
    assert app.relative_time(1_000_000, now=1_000_059) == "just now"


def test_relative_time_minutes():
    import app
    assert app.relative_time(1_000_000, now=1_000_060) == "1 min ago"
    assert app.relative_time(1_000_000, now=1_000_000 + 30 * 60) == "30 min ago"


def test_relative_time_hours():
    import app
    assert app.relative_time(1_000_000, now=1_000_000 + 3600) == "1 h ago"
    assert app.relative_time(1_000_000, now=1_000_000 + 5 * 3600) == "5 h ago"


def test_relative_time_days():
    import app
    assert app.relative_time(1_000_000, now=1_000_000 + 86400) == "1 d ago"
    assert app.relative_time(1_000_000, now=1_000_000 + 3 * 86400) == "3 d ago"


def test_relative_time_absolute_after_week():
    import app
    # 2001-09-09 01:46:40 UTC (the famous 1_000_000_000 epoch)
    result = app.relative_time(1_000_000_000, now=1_000_000_000 + 8 * 86400)
    assert result == "2001-09-09"


def test_cover_route_returns_jpeg(client):
    response = client.get("/cover.jpg")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    # Sanity: real JPEG starts with the magic bytes FF D8
    assert response.content[:2] == b"\xff\xd8"
    # Long-cache header present
    assert "max-age" in response.headers.get("cache-control", "")


def test_episodes_partial_returns_html(client):
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]

    response = client.get(f"/u/{secret}/episodes_partial")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    # Welcome was seeded on /create, so partial shows it
    assert "Welcome to Feed Me" in response.text
    # Outer section structure (h2 header + table or empty state)
    assert "Recent episodes" in response.text


def test_episodes_partial_404_for_unknown_user(client):
    response = client.get("/u/nope/episodes_partial")
    assert response.status_code == 404


def test_episodes_partial_reflects_new_pending_episode(client, tmp_path):
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]

    import storage
    storage.write_pending_episode(tmp_path, secret,
                                   source_url="https://example.com/p")

    response = client.get(f"/u/{secret}/episodes_partial")
    # Partial picks up the newly-written pending episode
    assert "Pending" in response.text
    assert "example.com/p" in response.text


def test_hostname_filter_strips_scheme_and_path():
    import app
    assert app.hostname("https://colossus.com/article/inside-notion/") == "colossus.com"
    assert app.hostname("http://example.com") == "example.com"
    assert app.hostname("https://www.feed-me.xyz/u/abc/feed.xml") == "www.feed-me.xyz"


def test_hostname_filter_handles_unparseable_input():
    import app
    assert app.hostname("not a url") == "not a url"
    assert app.hostname("") == ""


def test_settings_page_shows_loading_for_pending_with_no_title(client, tmp_path):
    """When a pending episode has no title, the row shows 'Loading from <hostname>...'"""
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]

    import storage
    storage.write_pending_episode(
        tmp_path, secret, source_url="https://colossus.com/article/inside-notion/"
    )

    response = client.get(f"/u/{secret}")
    assert "Loading from colossus.com" in response.text


def test_settings_page_shows_pending_title_when_set(client, tmp_path):
    """When fetch_title succeeded, the row shows the real title, not 'Loading from'."""
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]

    import storage
    storage.write_pending_episode(
        tmp_path, secret,
        source_url="https://example.com/x",
        title="Real Article Title",
    )

    response = client.get(f"/u/{secret}")
    assert "Real Article Title" in response.text
    assert "Loading from" not in response.text


def test_settings_page_shows_real_error_for_failed_episodes(client, tmp_path):
    """Failed episodes surface the actual error, not a misleading generic label."""
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]

    import storage
    storage.write_failed_episode(
        tmp_path, secret, source_url="https://nyt.com/a",
        error="OpenAI quota exceeded (429)",
    )

    response = client.get(f"/u/{secret}")
    # the real error is surfaced
    assert "OpenAI quota exceeded (429)" in response.text
    # the misleading generic label is gone
    assert "(couldn't extract article)" not in response.text


def test_settings_apple_podcasts_uses_singular_podcast_scheme(client):
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]

    response = client.get(f"/u/{secret}")
    # v1.6: podcast:// (singular) is Apple's documented scheme
    assert 'href="podcast://' in response.text
    # The old plural form should not appear
    assert 'href="podcasts://' not in response.text


def test_settings_pending_row_has_data_attributes(client, tmp_path):
    """Pending rows must carry data-ts and data-chunks for the JS ticker."""
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]

    import storage
    slug = storage.write_pending_episode(
        tmp_path, secret, source_url="https://example.com/x", title="Loading",
    )
    storage.update_pending_episode(tmp_path, secret, slug, total_chunks=7)

    response = client.get(f"/u/{secret}")
    # JS ticker reads these to compute % live
    assert 'data-ts="' in response.text
    assert 'data-chunks="7"' in response.text
    # The pending-progress span exists (initially empty; JS fills it)
    assert 'pending-progress' in response.text


def test_settings_sets_session_cookie(client):
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]

    response = client.get(f"/u/{secret}")
    assert response.cookies.get("fm_session") == secret
    set_cookie = response.headers["set-cookie"]
    assert "HttpOnly" in set_cookie
    assert "Secure" in set_cookie
    assert "SameSite=lax" in set_cookie
    assert "Max-Age=" in set_cookie
    assert "Path=/" in set_cookie


def test_create_links_browser(client):
    # Following the redirect lands on GET /u/{secret}, which sets the cookie.
    response = client.post("/create")  # default: follows redirect
    assert response.status_code == 200
    assert client.cookies.get("fm_session")  # now in the client's jar


def test_rotate_updates_session_cookie(client):
    create = client.post("/create", follow_redirects=False)
    old = create.headers["location"].split("/u/")[1]
    client.get(f"/u/{old}")  # set initial cookie

    client.post(f"/u/{old}/rotate")  # follows redirect to /u/{new}
    new = client.cookies.get("fm_session")
    assert new is not None
    assert new != old


def test_share_with_cookie_spawns_ingest(client, monkeypatch, fake_http, tmp_path):
    from tests.conftest import FakeResponse

    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]
    client.get(f"/u/{secret}")  # links this browser (sets fm_session)

    fake_http.responses["https://example.com/a"] = FakeResponse(
        status_code=200, text="<html><head><title>A</title></head></html>",
    )
    import ingest
    monkeypatch.setattr(ingest, "http_client", fake_http)

    calls = []

    def fake_spawn(url, secret_, data_dir, slug):
        calls.append((url, secret_, slug))

    import app as app_module
    monkeypatch.setattr(app_module, "spawn_ingest", fake_spawn)

    response = client.get("/share?url=https://example.com/a")
    assert response.status_code == 200
    assert "Added" in response.text
    assert len(calls) == 1
    assert calls[0][1] == secret

    import storage
    eps = storage.list_episodes(tmp_path, secret)
    assert any(e["status"] == "pending" for e in eps)


def test_share_without_cookie_shows_connect(client):
    # No /u/{secret} visit in this fresh client → no cookie.
    response = client.get("/share?url=https://example.com/a")
    assert response.status_code == 200
    assert "Link this browser" in response.text


def test_share_blocked_feed_shows_suspended(client, monkeypatch, tmp_path):
    """A blocked feed hitting the shortcut path sees a suspended page and spawns
    no ingest (defense in depth: the block covers every TTS entry point)."""
    import analytics
    import app as app_module
    import storage

    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]
    client.get(f"/u/{secret}")  # links this browser (sets fm_session)
    monkeypatch.setattr(
        app_module, "BLOCKED_FEED_HASHES",
        frozenset({analytics.feed_hash(secret)}),
    )

    calls = []
    monkeypatch.setattr(
        app_module, "spawn_ingest",
        lambda *a, **k: calls.append(a),
    )

    response = client.get("/share?url=https://example.com/a")
    assert response.status_code == 200
    assert "Feed suspended" in response.text
    assert calls == []                                         # no ingest spawned
    assert len(storage.list_episodes(tmp_path, secret)) == 1   # welcome only, no failed row


def test_share_bad_url_writes_failed(client, tmp_path):
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]
    client.get(f"/u/{secret}")  # link browser

    response = client.get("/share?url=")
    assert response.status_code == 200
    assert "Couldn't add" in response.text
    # Copy must instruct (share an article), not diagnose (v3.4: a user ran the
    # Shortcut directly from the Shortcuts app and hit a bare "no URL" error).
    assert "No article added" in response.text
    assert "tap Share, then tap Feed Me" in response.text

    import storage
    eps = storage.list_episodes(tmp_path, secret)
    failed = [e for e in eps if e["status"] == "failed"]
    assert len(failed) == 1


def test_share_invalid_scheme_shows_error(client, tmp_path):
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]
    client.get(f"/u/{secret}")  # link browser

    response = client.get("/share?url=ftp://badscheme.example.com/x")
    assert response.status_code == 200
    assert "Invalid URL" in response.text

    import storage
    eps = storage.list_episodes(tmp_path, secret)
    failed = [e for e in eps if e["status"] == "failed"]
    assert len(failed) == 1
    assert "Invalid URL" in failed[0]["error"] or "ftp" in failed[0]["error"]


def test_share_stale_secret_shows_connect(client):
    # Cookie holds a secret whose dir no longer exists (post-rotation).
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]
    client.get(f"/u/{secret}")  # cookie = old secret
    # Rotate WITHOUT following the redirect, so the cookie still holds the OLD
    # secret while the on-disk dir moves to a new one.
    client.post(f"/u/{secret}/rotate", follow_redirects=False)

    response = client.get("/share?url=https://example.com/a")
    assert response.status_code == 200
    assert "Link this browser" in response.text


def test_share_writes_pending_with_fetched_title(
    client, tmp_path, monkeypatch, fake_http,
):
    from tests.conftest import FakeResponse

    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]
    client.get(f"/u/{secret}")  # link this browser (sets fm_session)

    fake_http.responses["https://example.com/t"] = FakeResponse(
        status_code=200,
        text="<html><head><title>Inside Notion</title></head></html>",
    )
    import ingest
    monkeypatch.setattr(ingest, "http_client", fake_http)

    import app as app_module
    monkeypatch.setattr(app_module, "spawn_ingest", lambda *a, **k: None)

    response = client.get("/share?url=https://example.com/t")
    assert response.status_code == 200

    import storage
    eps = storage.list_episodes(tmp_path, secret)
    pending = [e for e in eps if e["status"] == "pending"]
    assert len(pending) == 1
    assert pending[0]["title"] == "Inside Notion"


def test_share_writes_pending_with_no_title_on_fetch_failure(
    client, tmp_path, monkeypatch, fake_http,
):
    from tests.conftest import FakeResponse

    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]
    client.get(f"/u/{secret}")  # link browser

    fake_http.responses["https://example.com/dead"] = FakeResponse(status_code=500)
    import ingest
    monkeypatch.setattr(ingest, "http_client", fake_http)

    import app as app_module
    monkeypatch.setattr(app_module, "spawn_ingest", lambda *a, **k: None)

    response = client.get("/share?url=https://example.com/dead")
    assert response.status_code == 200

    import storage
    eps = storage.list_episodes(tmp_path, secret)
    pending = [e for e in eps if e["status"] == "pending"]
    assert len(pending) == 1
    assert pending[0]["title"] is None


def test_landing_records_page_view(client, tmp_path):
    client.get("/")
    import analytics
    s = analytics.summary(tmp_path / "_analytics" / "analytics.db")
    assert s["page_views_by_path"]["landing"] >= 1


def test_settings_records_page_view(client, tmp_path):
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]
    client.get(f"/u/{secret}")
    import analytics
    s = analytics.summary(tmp_path / "_analytics" / "analytics.db")
    assert s["page_views_by_path"]["settings"] >= 1


def test_create_records_feed_created(client, tmp_path):
    client.post("/create", follow_redirects=False)
    import analytics
    s = analytics.summary(tmp_path / "_analytics" / "analytics.db")
    assert s["feeds_created"] == 1


def test_share_records_article_shared_with_feed_hash(client, monkeypatch, tmp_path):
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]
    client.get(f"/u/{secret}")  # link browser (cookie)

    import app as app_module
    monkeypatch.setattr(app_module, "spawn_ingest", lambda *a, **k: None)
    monkeypatch.setattr(app_module.ingest, "fetch_title", lambda url: "T")

    client.get("/share?url=https://example.com/a")

    import analytics
    db = tmp_path / "_analytics" / "analytics.db"
    s = analytics.summary(db)
    assert s["articles_shared"] == 1
    assert s["top_feeds"][0]["feed_hash"] == analytics.feed_hash(secret)


def test_share_event_records_article_url_and_title(client, monkeypatch, tmp_path):
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]
    client.get(f"/u/{secret}")  # link browser (cookie)

    import app as app_module
    monkeypatch.setattr(app_module, "spawn_ingest", lambda *a, **k: None)
    monkeypatch.setattr(app_module.ingest, "fetch_title", lambda url: "My Title")

    client.get("/share?url=https://example.com/xyz")

    import analytics
    s = analytics.summary(tmp_path / "_analytics" / "analytics.db")
    assert s["recent_shares"][0]["url"] == "https://example.com/xyz"
    assert s["recent_shares"][0]["title"] == "My Title"


def test_analytics_failure_never_500s_a_page(client, monkeypatch):
    import app as app_module
    def boom(*a, **k):
        raise RuntimeError("analytics down")
    monkeypatch.setattr(app_module.analytics, "track", boom)
    assert client.get("/").status_code == 200


def test_admin_routes_404_without_token(client):
    # STATS_TOKEN unset by default in tests → both routes 404.
    assert client.get("/admin/stats").status_code == 404
    assert client.get("/admin/export").status_code == 404


def test_admin_routes_404_with_wrong_token(client, monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, "STATS_TOKEN", "right")
    assert client.get("/admin/stats?token=wrong").status_code == 404
    assert client.get("/admin/export?token=wrong").status_code == 404
    # STATS_TOKEN set but no token param → the `not token` branch → 404
    assert client.get("/admin/stats").status_code == 404
    assert client.get("/admin/export").status_code == 404


def test_admin_stats_and_export_with_correct_token(client, monkeypatch, tmp_path):
    import app as app_module
    monkeypatch.setattr(app_module, "STATS_TOKEN", "right")
    # generate some data
    client.post("/create", follow_redirects=False)
    client.get("/")

    stats = client.get("/admin/stats?token=right")
    assert stats.status_code == 200
    assert "Feeds created" in stats.text  # a label from the stats page

    export = client.get("/admin/export?token=right")
    assert export.status_code == 200
    body = export.json()
    assert "summary" in body and "events" in body
    assert body["summary"]["feeds_created"] == 1
    assert len(body["events"]) >= 2  # feed_created + at least one page_view


def test_admin_export_empty_db(client, monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, "STATS_TOKEN", "right")
    # No events generated — DB may not exist yet.
    export = client.get("/admin/export?token=right")
    assert export.status_code == 200
    body = export.json()
    assert body["events"] == []
    assert body["summary"]["feeds_created"] == 0


def test_admin_stats_shows_feed_hash_never_the_raw_secret(client, monkeypatch, tmp_path):
    import app as app_module
    import analytics
    import storage
    monkeypatch.setattr(app_module, "STATS_TOKEN", "right")
    secret = storage.create_user(tmp_path)  # DATA_DIR is monkeypatched to tmp_path

    stats = client.get("/admin/stats?token=right")
    assert stats.status_code == 200
    # Privacy boundary: the hash is rendered, the raw secret never is.
    assert f"<code>{analytics.feed_hash(secret)}</code>" in stats.text
    assert secret not in stats.text


def test_admin_stats_shows_never_for_feed_with_no_events(client, monkeypatch, tmp_path):
    import app as app_module
    import storage
    monkeypatch.setattr(app_module, "STATS_TOKEN", "right")
    storage.create_user(tmp_path)  # created on disk, but no analytics events tracked

    stats = client.get("/admin/stats?token=right")
    assert stats.status_code == 200
    assert "All feeds" in stats.text
    assert "never" in stats.text  # last-accessed placeholder, not an em-dash


def test_recently_shared_columns_are_feed_when_article(client, monkeypatch, tmp_path):
    import app as app_module
    monkeypatch.setattr(app_module, "STATS_TOKEN", "right")
    stats = client.get("/admin/stats?token=right")
    assert stats.status_code == 200
    # Column order is Feed, then When, then Article (header on one line).
    assert "<th>Feed</th><th>When (PT)</th><th>Article</th>" in stats.text
    # The old "Top feeds (by shares)" section is gone.
    assert "Top feeds" not in stats.text


def test_share_event_props_tag_via_shortcut(client, monkeypatch, tmp_path):
    import json as _json
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]
    client.get(f"/u/{secret}")  # link browser (cookie)

    import app as app_module
    monkeypatch.setattr(app_module, "spawn_ingest", lambda *a, **k: None)
    monkeypatch.setattr(app_module.ingest, "fetch_title", lambda url: "T")

    client.get("/share?url=https://example.com/a")

    import analytics
    db = tmp_path / "_analytics" / "analytics.db"
    shared = [e for e in analytics.all_events(db) if e["event"] == "article_shared"]
    assert len(shared) == 1
    assert _json.loads(shared[0]["props"])["via"] == "shortcut"


def test_ga_snippet_on_landing(client):
    body = client.get("/").text
    assert "googletagmanager.com/gtag/js?id=G-MQ15LHLSBF" in body
    # referrer-masking logic ships with the snippet everywhere
    assert "page_referrer" in body


def test_ga_snippet_on_settings_masks_secret(client):
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]

    body = client.get(f"/u/{secret}").text
    assert "googletagmanager.com/gtag/js?id=G-MQ15LHLSBF" in body
    # The page's own URL contains the secret, so GA must report /u/_ instead.
    assert 'gaCfg.page_location = "https://test.local/u/_"' in body
    assert "gaCfg.page_path = '/u/_'" in body
    assert "page_referrer" in body  # referrer mask ships here too
    # The secret legitimately appears elsewhere on the page (feed URL box), but
    # never on any GA-related line.
    ga_lines = [l for l in body.splitlines()
                if "gtag" in l or "gaCfg" in l or "googletagmanager" in l]
    assert ga_lines
    assert all(secret not in l for l in ga_lines)


def test_ga_snippet_on_share_page(client):
    # No cookie -> the "connect" state renders; the snippet ships on all states.
    body = client.get("/share?url=https://example.com/a").text
    assert "googletagmanager.com/gtag/js?id=G-MQ15LHLSBF" in body
    assert "page_referrer" in body


def test_ga_lines_never_contain_secret_on_share_states(client, monkeypatch):
    """GA lines must never include the feed secret on any secret-bearing share state."""
    import app as app_module

    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]
    client.get(f"/u/{secret}")  # links this browser (sets fm_session)

    # --- "error" state: no url param ---
    body = client.get("/share").text
    assert "Couldn't add that" in body  # page rendered the error state; guard is not vacuous
    assert "googletagmanager.com/gtag/js?id=G-MQ15LHLSBF" in body
    ga_lines = [l for l in body.splitlines()
                if "gtag" in l or "gaCfg" in l or "googletagmanager" in l]
    assert ga_lines
    assert all(secret not in l for l in ga_lines)

    # --- "added" state: valid url param ---
    monkeypatch.setattr(app_module, "spawn_ingest", lambda *a, **k: None)
    monkeypatch.setattr(app_module.ingest, "fetch_title", lambda url: "T")

    body = client.get("/share?url=https://example.com/a").text
    assert "Adding to your feed…" in body  # page rendered the added state; guard is not vacuous
    assert "googletagmanager.com/gtag/js?id=G-MQ15LHLSBF" in body
    ga_lines = [l for l in body.splitlines()
                if "gtag" in l or "gaCfg" in l or "googletagmanager" in l]
    assert ga_lines
    assert all(secret not in l for l in ga_lines)


def test_ga_snippet_not_on_admin_stats(client, monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, "STATS_TOKEN", "right")
    body = client.get("/admin/stats?token=right").text
    assert "All feeds" in body  # page rendered; guard is not vacuous
    assert "googletagmanager" not in body


def test_share_extracts_url_from_shared_text(client, monkeypatch, fake_http, tmp_path):
    """Some apps hand the Shortcut 'Headline https://link' text, not a bare URL."""
    from tests.conftest import FakeResponse

    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]
    client.get(f"/u/{secret}")  # link browser

    fake_http.responses["https://example.com/a?x=1"] = FakeResponse(
        status_code=200, text="<html><head><title>A</title></head></html>",
    )
    import ingest
    monkeypatch.setattr(ingest, "http_client", fake_http)

    calls = []
    import app as app_module
    monkeypatch.setattr(
        app_module, "spawn_ingest",
        lambda url, secret_, data_dir, slug: calls.append(url),
    )

    response = client.get(
        "/share?url=Cycling%27s%20stakeholders%20https%3A%2F%2Fexample.com%2Fa%3Fx%3D1%20(Shared)",
    )
    assert response.status_code == 200
    assert "Added" in response.text
    assert calls == ["https://example.com/a?x=1"]


def test_share_text_without_link_explains_how_to_fix(client, tmp_path):
    """NYT/Athletic can share only the article dek: say what happened, not 'Invalid URL'."""
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]
    client.get(f"/u/{secret}")  # link browser

    prose = "By not being afforded the basics of protection in a racing situation"
    response = client.get("/share", params={"url": prose})
    assert response.status_code == 200
    assert "Invalid URL" not in response.text
    assert "include a link" in response.text        # apostrophe is HTML-escaped
    assert "Safari" in response.text

    import storage
    failed = [
        e for e in storage.list_episodes(tmp_path, secret) if e["status"] == "failed"
    ]
    assert len(failed) == 1
    assert "didn't include a link" in failed[0]["error"]


def test_settings_hides_full_text_shortcut_until_configured(client, monkeypatch):
    """The second Shortcut is optional: no iCloud link, no half-built row."""
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]

    import app as app_module
    monkeypatch.setattr(app_module, "SHORTCUT_TEXT_ICLOUD_URL", "")
    assert "Paywalled sites" not in client.get(f"/u/{secret}").text

    monkeypatch.setattr(
        app_module, "SHORTCUT_TEXT_ICLOUD_URL",
        "https://www.icloud.com/shortcuts/FULLTEXT",
    )
    page = client.get(f"/u/{secret}").text
    assert "Paywalled sites" in page
    assert "https://www.icloud.com/shortcuts/FULLTEXT" in page
    assert "Safari" in page          # the habit the shortcut depends on


def test_settings_precopies_the_feed_link_for_the_install_question(client, monkeypatch):
    """The Full Text Shortcut asks for the feed link at import; the install
    button copies it first so answering is a paste, not a hunt."""
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]

    import app as app_module
    monkeypatch.setattr(
        app_module, "SHORTCUT_TEXT_ICLOUD_URL",
        "https://www.icloud.com/shortcuts/FULLTEXT",
    )
    page = client.get(f"/u/{secret}").text

    assert "installTextShortcut()" in page
    assert f"https://test.local/u/{secret}" in page   # the page URL, not feed.xml
