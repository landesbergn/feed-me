def test_healthz(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.text == "ok"


def test_landing_page_renders(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Get my feed" in response.text
    assert "feed-me" in response.text.lower()
    # v1.1 regression guards
    assert "private" in response.text.lower()
    assert "Create your feed" in response.text


def test_post_create_redirects_to_user_settings(client):
    response = client.post("/create", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/u/")
    secret = response.headers["location"].split("/u/")[1]
    assert len(secret) >= 32


def test_post_create_makes_user_dir(client, tmp_path):
    response = client.post("/create", follow_redirects=False)
    secret = response.headers["location"].split("/u/")[1]
    assert (tmp_path / secret / "settings.json").exists()


def test_settings_404_for_unknown_user(client):
    response = client.get("/u/unknown_secret")
    assert response.status_code == 404


def test_settings_renders_for_known_user(client):
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]

    response = client.get(f"/u/{secret}")
    assert response.status_code == 200
    assert "Install Shortcut" in response.text
    assert "Add to Apple Podcasts" in response.text
    assert "Copy ingest URL" in response.text
    # Ingest URL must appear so the page can copy it
    assert f"/u/{secret}/ingest" in response.text


def test_settings_lists_recent_episodes(client, tmp_path):
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]

    import storage
    storage.write_episode(tmp_path, secret, title="My Article",
                          source_url="https://example.com/a", audio=b"X")

    response = client.get(f"/u/{secret}")
    assert "My Article" in response.text


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


def test_ingest_returns_ok_quickly(client, monkeypatch):
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]

    calls = []

    def fake_spawn(url, secret_, data_dir):
        calls.append((url, secret_, str(data_dir)))

    import app as app_module
    monkeypatch.setattr(app_module, "spawn_ingest", fake_spawn)

    response = client.get(
        f"/u/{secret}/ingest?url=https://example.com/x",
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert len(calls) == 1
    assert calls[0][0] == "https://example.com/x"
    assert calls[0][1] == secret


def test_ingest_rejects_invalid_url(client, monkeypatch):
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]

    response = client.get(f"/u/{secret}/ingest?url=not-a-url")
    assert response.status_code == 400


def test_ingest_404_for_unknown_user(client):
    response = client.get("/u/nope/ingest?url=https://example.com")
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
