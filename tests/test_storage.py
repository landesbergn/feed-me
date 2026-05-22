import json
import time as _time
from pathlib import Path

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
