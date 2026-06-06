import json
import time as _time
from pathlib import Path

import pytest

import storage


def test_create_user_generates_secret_and_writes_settings(tmp_path):
    secret = storage.create_user(tmp_path)

    assert isinstance(secret, str)
    assert len(secret) >= 32

    user_dir = tmp_path / secret
    assert user_dir.is_dir()

    settings = json.loads((user_dir / "settings.json").read_text())
    assert settings["voice"] == "shimmer"
    assert isinstance(settings["created_at"], int)


def test_user_exists_true_after_create(tmp_path):
    secret = storage.create_user(tmp_path)
    assert storage.user_exists(tmp_path, secret) is True


def test_user_exists_false_for_unknown_secret(tmp_path):
    assert storage.user_exists(tmp_path, "nonexistent") is False


def test_user_exists_rejects_path_traversal(tmp_path):
    assert storage.user_exists(tmp_path, "../etc") is False
    assert storage.user_exists(tmp_path, "..") is False
    assert storage.user_exists(tmp_path, "foo/bar") is False


def test_write_episode_creates_mp3_and_json(tmp_path):
    secret = storage.create_user(tmp_path)

    slug = storage.write_episode(
        tmp_path, secret,
        title="On Time",
        source_url="https://example.com/a",
        audio=b"FAKEMP3",
    )

    assert (tmp_path / secret / f"{slug}.mp3").read_bytes() == b"FAKEMP3"
    meta = json.loads((tmp_path / secret / f"{slug}.json").read_text())
    assert meta["title"] == "On Time"
    assert meta["url"] == "https://example.com/a"
    assert isinstance(meta["ts"], int)
    assert "error" not in meta


def test_write_failed_episode_writes_json_only(tmp_path):
    secret = storage.create_user(tmp_path)

    slug = storage.write_failed_episode(
        tmp_path, secret,
        source_url="https://example.com/b",
        error="paywalled",
    )

    assert not (tmp_path / secret / f"{slug}.mp3").exists()
    meta = json.loads((tmp_path / secret / f"{slug}.json").read_text())
    assert meta["error"] == "paywalled"
    assert meta["url"] == "https://example.com/b"
    assert meta.get("title") is None


def test_list_episodes_returns_newest_first(tmp_path):
    secret = storage.create_user(tmp_path)

    storage.write_episode(tmp_path, secret, title="A",
                          source_url="https://a", audio=b"X")
    _time.sleep(0.01)
    storage.write_episode(tmp_path, secret, title="B",
                          source_url="https://b", audio=b"Y")

    eps = storage.list_episodes(tmp_path, secret)

    assert len(eps) == 2
    assert eps[0]["title"] == "B"
    assert eps[1]["title"] == "A"


def test_list_episodes_includes_failures(tmp_path):
    secret = storage.create_user(tmp_path)
    storage.write_episode(tmp_path, secret, title="ok",
                          source_url="https://a", audio=b"X")
    storage.write_failed_episode(tmp_path, secret,
                                  source_url="https://b", error="boom")

    eps = storage.list_episodes(tmp_path, secret)

    assert len(eps) == 2
    err = [e for e in eps if e.get("error")]
    assert len(err) == 1
    assert err[0]["error"] == "boom"


def test_list_episodes_excludes_settings(tmp_path):
    secret = storage.create_user(tmp_path)
    eps = storage.list_episodes(tmp_path, secret)
    assert eps == []


def test_get_settings_returns_defaults(tmp_path):
    secret = storage.create_user(tmp_path)
    s = storage.get_settings(tmp_path, secret)
    assert s["voice"] == "shimmer"


def test_set_voice_persists(tmp_path):
    secret = storage.create_user(tmp_path)
    storage.set_voice(tmp_path, secret, "alloy")
    assert storage.get_settings(tmp_path, secret)["voice"] == "alloy"


def test_set_voice_rejects_unknown_voice(tmp_path):
    secret = storage.create_user(tmp_path)
    import pytest
    with pytest.raises(ValueError):
        storage.set_voice(tmp_path, secret, "evil_voice")
    assert storage.get_settings(tmp_path, secret)["voice"] == "shimmer"


def test_rotate_secret_moves_data_and_returns_new_secret(tmp_path):
    old = storage.create_user(tmp_path)
    storage.write_episode(tmp_path, old, title="A",
                          source_url="https://a", audio=b"X")

    new = storage.rotate_secret(tmp_path, old)

    assert new != old
    assert not (tmp_path / old).exists()
    assert (tmp_path / new).is_dir()
    eps = storage.list_episodes(tmp_path, new)
    assert len(eps) == 1
    assert eps[0]["title"] == "A"


def test_write_pending_episode_writes_json_only(tmp_path):
    secret = storage.create_user(tmp_path)

    slug = storage.write_pending_episode(
        tmp_path, secret, source_url="https://example.com/x",
    )

    assert not (tmp_path / secret / f"{slug}.mp3").exists()
    meta = json.loads((tmp_path / secret / f"{slug}.json").read_text())
    assert meta["pending"] is True
    assert meta["url"] == "https://example.com/x"
    assert meta.get("title") is None
    assert "error" not in meta


def test_list_episodes_status_field_pending(tmp_path):
    secret = storage.create_user(tmp_path)
    storage.write_pending_episode(tmp_path, secret, source_url="https://a")

    eps = storage.list_episodes(tmp_path, secret)

    assert len(eps) == 1
    assert eps[0]["status"] == "pending"


def test_list_episodes_status_field_ready(tmp_path):
    secret = storage.create_user(tmp_path)
    storage.write_episode(tmp_path, secret, title="Hi",
                          source_url="https://a", audio=b"X")

    eps = storage.list_episodes(tmp_path, secret)

    assert eps[0]["status"] == "ready"


def test_list_episodes_status_field_failed(tmp_path):
    secret = storage.create_user(tmp_path)
    storage.write_failed_episode(tmp_path, secret,
                                  source_url="https://b", error="boom")

    eps = storage.list_episodes(tmp_path, secret)

    assert eps[0]["status"] == "failed"


def test_write_episode_promotes_pending(tmp_path):
    secret = storage.create_user(tmp_path)
    slug = storage.write_pending_episode(
        tmp_path, secret, source_url="https://example.com/x",
    )

    returned = storage.write_episode(
        tmp_path, secret,
        title="On Time", source_url="https://example.com/x",
        audio=b"FAKEMP3", slug=slug,
    )

    # Same slug returned, same file updated, no second file created
    assert returned == slug
    eps = storage.list_episodes(tmp_path, secret)
    assert len(eps) == 1
    assert eps[0]["status"] == "ready"
    assert eps[0]["title"] == "On Time"
    assert "pending" not in eps[0] or eps[0].get("pending") is None


def test_write_failed_episode_promotes_pending(tmp_path):
    secret = storage.create_user(tmp_path)
    slug = storage.write_pending_episode(
        tmp_path, secret, source_url="https://example.com/y",
    )

    returned = storage.write_failed_episode(
        tmp_path, secret,
        source_url="https://example.com/y", error="paywalled", slug=slug,
    )

    assert returned == slug
    eps = storage.list_episodes(tmp_path, secret)
    assert len(eps) == 1
    assert eps[0]["status"] == "failed"
    assert eps[0]["error"] == "paywalled"


def test_seed_welcome_episode_writes_mp3_and_json(tmp_path):
    secret = storage.create_user(tmp_path)

    slug = storage.seed_welcome_episode(
        tmp_path, secret, welcome_audio=b"FAKEMP3",
    )

    assert (tmp_path / secret / f"{slug}.mp3").read_bytes() == b"FAKEMP3"
    meta = json.loads((tmp_path / secret / f"{slug}.json").read_text())
    assert meta["title"] == "Welcome to Feed Me"
    assert meta["url"] == "https://feed-me.xyz"
    assert isinstance(meta["ts"], int)
    assert "error" not in meta
    assert "pending" not in meta


def test_seed_welcome_episode_appears_in_list_as_ready(tmp_path):
    secret = storage.create_user(tmp_path)
    storage.seed_welcome_episode(tmp_path, secret, welcome_audio=b"X")

    eps = storage.list_episodes(tmp_path, secret)

    assert len(eps) == 1
    assert eps[0]["title"] == "Welcome to Feed Me"
    assert eps[0]["status"] == "ready"


def test_write_pending_episode_accepts_title(tmp_path):
    secret = storage.create_user(tmp_path)

    slug = storage.write_pending_episode(
        tmp_path, secret,
        source_url="https://example.com/x",
        title="My Cool Article",
    )

    eps = storage.list_episodes(tmp_path, secret)
    assert len(eps) == 1
    assert eps[0]["title"] == "My Cool Article"
    assert eps[0]["status"] == "pending"


def test_write_episode_accepts_description(tmp_path):
    secret = storage.create_user(tmp_path)

    slug = storage.write_episode(
        tmp_path, secret,
        title="My Article", source_url="https://a", audio=b"X",
        description="The first paragraph or so of the article body...",
    )

    eps = storage.list_episodes(tmp_path, secret)
    assert eps[0]["description"] == "The first paragraph or so of the article body..."


def test_write_failed_episode_accepts_description(tmp_path):
    secret = storage.create_user(tmp_path)

    storage.write_failed_episode(
        tmp_path, secret,
        source_url="https://b", error="boom",
        description="paywall: nytimes.com/...",
    )

    eps = storage.list_episodes(tmp_path, secret)
    assert eps[0]["description"] == "paywall: nytimes.com/..."


def test_list_episodes_exposes_audio_bytes(tmp_path):
    secret = storage.create_user(tmp_path)
    storage.write_episode(
        tmp_path, secret,
        title="A", source_url="https://a", audio=b"FAKEMP3DATA",
    )

    eps = storage.list_episodes(tmp_path, secret)
    assert eps[0]["audio_bytes"] == len(b"FAKEMP3DATA")


def test_list_episodes_audio_bytes_is_none_when_no_mp3(tmp_path):
    """Pending and failed episodes have no .mp3, so audio_bytes should be None."""
    secret = storage.create_user(tmp_path)
    storage.write_pending_episode(tmp_path, secret, source_url="https://p")

    eps = storage.list_episodes(tmp_path, secret)
    assert eps[0]["audio_bytes"] is None


def test_seed_welcome_episode_writes_description(tmp_path):
    """The welcome episode should always carry the hard-coded description."""
    secret = storage.create_user(tmp_path)
    storage.seed_welcome_episode(tmp_path, secret, welcome_audio=b"X")

    eps = storage.list_episodes(tmp_path, secret)
    assert eps[0]["description"] == "Share an article from your phone — it'll show up here a minute later."


def test_update_pending_episode_sets_total_chunks(tmp_path):
    """Updating total_chunks on an existing pending record preserves other fields."""
    secret = storage.create_user(tmp_path)
    slug = storage.write_pending_episode(
        tmp_path, secret,
        source_url="https://example.com/x",
        title="Some Article",
    )

    storage.update_pending_episode(tmp_path, secret, slug, total_chunks=13)

    eps = storage.list_episodes(tmp_path, secret)
    assert len(eps) == 1
    assert eps[0]["status"] == "pending"
    assert eps[0]["title"] == "Some Article"  # preserved
    assert eps[0]["url"] == "https://example.com/x"  # preserved
    assert eps[0]["total_chunks"] == 13


def test_update_pending_episode_noop_when_missing(tmp_path):
    """Updating a non-existent slug returns without raising and doesn't create a file."""
    secret = storage.create_user(tmp_path)

    # Should not raise
    storage.update_pending_episode(tmp_path, secret, "missing_slug", total_chunks=5)

    eps = storage.list_episodes(tmp_path, secret)
    assert eps == []
    # No phantom files created
    assert not (tmp_path / secret / "missing_slug.json").exists()


def test_list_feeds_returns_one_entry_per_feed(tmp_path):
    s1 = storage.create_user(tmp_path)
    s2 = storage.create_user(tmp_path)
    feeds = storage.list_feeds(tmp_path)
    secrets = {f["secret"] for f in feeds}
    assert secrets == {s1, s2}
    assert all(isinstance(f["created_at"], int) for f in feeds)


def test_list_feeds_skips_analytics_dir(tmp_path):
    storage.create_user(tmp_path)
    (tmp_path / "_analytics").mkdir()
    (tmp_path / "_analytics" / "analytics.db").write_text("x")
    names = {f["secret"] for f in storage.list_feeds(tmp_path)}
    assert "_analytics" not in names


def test_list_feeds_skips_dirs_without_settings(tmp_path):
    storage.create_user(tmp_path)
    (tmp_path / "not-a-feed").mkdir()
    names = {f["secret"] for f in storage.list_feeds(tmp_path)}
    assert "not-a-feed" not in names


def test_list_feeds_falls_back_to_mtime_when_created_at_missing(tmp_path):
    feed_dir = tmp_path / "legacy-feed"
    feed_dir.mkdir()
    settings = feed_dir / "settings.json"
    settings.write_text(json.dumps({"voice": "shimmer"}))  # no created_at
    feeds = storage.list_feeds(tmp_path)
    entry = next(f for f in feeds if f["secret"] == "legacy-feed")
    assert entry["created_at"] == int(settings.stat().st_mtime)


def test_write_pending_episode_stores_via(tmp_path):
    secret = storage.create_user(tmp_path)
    slug = storage.write_pending_episode(
        tmp_path, secret, source_url="https://ex.com/a", via="agent",
    )
    record = json.loads((tmp_path / secret / f"{slug}.json").read_text())
    assert record["via"] == "agent"


def test_write_pending_episode_omits_via_by_default(tmp_path):
    secret = storage.create_user(tmp_path)
    slug = storage.write_pending_episode(
        tmp_path, secret, source_url="https://ex.com/a",
    )
    record = json.loads((tmp_path / secret / f"{slug}.json").read_text())
    assert "via" not in record


def test_write_episode_carries_via_through_finalization(tmp_path):
    """The agent daily cap counts via == "agent" records; via must survive
    the fresh-dict rewrite that write_episode does on completion."""
    secret = storage.create_user(tmp_path)
    slug = storage.write_pending_episode(
        tmp_path, secret, source_url="https://ex.com/a", via="agent",
    )
    storage.write_episode(
        tmp_path, secret, slug=slug,
        title="T", source_url="https://ex.com/a", audio=b"MP3",
    )
    record = json.loads((tmp_path / secret / f"{slug}.json").read_text())
    assert record["via"] == "agent"
    assert "pending" not in record    # fresh-dict semantics otherwise intact


def test_write_failed_episode_carries_via_through_finalization(tmp_path):
    secret = storage.create_user(tmp_path)
    slug = storage.write_pending_episode(
        tmp_path, secret, source_url="https://ex.com/a", via="agent",
    )
    storage.write_failed_episode(
        tmp_path, secret, slug=slug,
        source_url="https://ex.com/a", error="boom",
    )
    record = json.loads((tmp_path / secret / f"{slug}.json").read_text())
    assert record["via"] == "agent"


def test_finalization_without_pending_record_has_no_via(tmp_path):
    secret = storage.create_user(tmp_path)
    slug = storage.write_episode(
        tmp_path, secret,
        title="T", source_url="https://ex.com/a", audio=b"MP3",
    )
    record = json.loads((tmp_path / secret / f"{slug}.json").read_text())
    assert "via" not in record


def test_write_episode_accepts_audio_path(tmp_path):
    """audio_path= renames the streamed temp file into place (no copy)."""
    secret = storage.create_user(tmp_path)
    tmp_audio = tmp_path / secret / "incoming.mp3.tmp"
    tmp_audio.write_bytes(b"STREAMED")

    slug = storage.write_episode(
        tmp_path, secret, title="T", source_url="https://e.com/a",
        audio_path=tmp_audio,
    )

    assert (tmp_path / secret / f"{slug}.mp3").read_bytes() == b"STREAMED"
    assert not tmp_audio.exists()


def test_write_episode_requires_exactly_one_audio_source(tmp_path):
    secret = storage.create_user(tmp_path)
    with pytest.raises(ValueError):
        storage.write_episode(
            tmp_path, secret, title="T", source_url="https://e.com/a",
        )
    with pytest.raises(ValueError):
        storage.write_episode(
            tmp_path, secret, title="T", source_url="https://e.com/a",
            audio=b"X", audio_path=tmp_path / secret / "x.tmp",
        )
