import json
import os
import secrets as _secrets
import time
from pathlib import Path

DEFAULT_VOICE = "shimmer"
ALLOWED_VOICES = {"shimmer", "alloy", "nova", "echo"}
WELCOME_DESCRIPTION = "Share an article from your phone — it'll show up here a minute later."


def create_user(data_dir: Path) -> str:
    secret = _secrets.token_urlsafe(32)
    user_dir = data_dir / secret
    user_dir.mkdir(parents=True, exist_ok=False)
    settings = {"voice": DEFAULT_VOICE, "created_at": int(time.time())}
    (user_dir / "settings.json").write_text(json.dumps(settings))
    return secret


def user_exists(data_dir: Path, secret: str) -> bool:
    if not secret or "/" in secret or ".." in secret:
        return False
    return (data_dir / secret).is_dir()


def _new_slug() -> str:
    return _secrets.token_urlsafe(12)


def _pending_via(data_dir: Path, secret: str, slug: str) -> str | None:
    """Read the via tag off an existing (pending) record before finalization
    overwrites it. write_episode / write_failed_episode rebuild the record
    from scratch; the agent daily cap counts via == "agent" episodes, so
    dropping the tag would silently turn the daily cap into a concurrency cap.
    """
    try:
        record = json.loads((data_dir / secret / f"{slug}.json").read_text())
    except (OSError, json.JSONDecodeError):
        return None
    via = record.get("via")
    return via if isinstance(via, str) else None


def write_episode(
    data_dir: Path, secret: str, *,
    title: str, source_url: str,
    audio: bytes | None = None,
    audio_path: Path | None = None,
    slug: str | None = None,
    description: str | None = None,
    chars: int | None = None,
) -> str:
    """Audio comes as bytes (audio=) or as a file to rename into place
    (audio_path=, used by ingest so a long synthesis streams to disk and never
    holds the full MP3 in memory; rename is atomic on the same filesystem).
    Exactly one of the two is required. `chars` is the synthesized character
    count, recorded so the per-feed narration budget can meter TTS cost."""
    if (audio is None) == (audio_path is None):
        raise ValueError("exactly one of audio / audio_path is required")
    if slug is None:
        slug = _new_slug()
    via = _pending_via(data_dir, secret, slug)
    user_dir = data_dir / secret
    if audio_path is not None:
        os.replace(audio_path, user_dir / f"{slug}.mp3")
    else:
        (user_dir / f"{slug}.mp3").write_bytes(audio)
    record = {
        "title": title,
        "url": source_url,
        "ts": int(time.time()),
    }
    if description is not None:
        record["description"] = description
    if via is not None:
        record["via"] = via
    if chars is not None:
        record["chars"] = chars
    (user_dir / f"{slug}.json").write_text(json.dumps(record))
    return slug


def write_failed_episode(
    data_dir: Path, secret: str, *,
    source_url: str, error: str,
    slug: str | None = None,
    description: str | None = None,
    chars: int | None = None,
) -> str:
    if slug is None:
        slug = _new_slug()
    via = _pending_via(data_dir, secret, slug)
    record = {
        "title": None,
        "url": source_url,
        "ts": int(time.time()),
        "error": error,
    }
    if description is not None:
        record["description"] = description
    if via is not None:
        record["via"] = via
    if chars is not None:
        record["chars"] = chars
    (data_dir / secret / f"{slug}.json").write_text(json.dumps(record))
    return slug


def write_pending_episode(
    data_dir: Path, secret: str, *,
    source_url: str,
    title: str | None = None,
    description: str | None = None,
    via: str | None = None,
    chars: int | None = None,
) -> str:
    slug = _new_slug()
    record = {
        "title": title,
        "url": source_url,
        "ts": int(time.time()),
        "pending": True,
    }
    if description is not None:
        record["description"] = description
    if via is not None:
        record["via"] = via
    if chars is not None:
        record["chars"] = chars
    (data_dir / secret / f"{slug}.json").write_text(json.dumps(record))
    return slug


def update_pending_episode(
    data_dir: Path, secret: str, slug: str, *,
    total_chunks: int | None = None,
) -> None:
    """Update fields on an existing pending episode record.

    Reads the JSON, updates the specified fields, writes back. Existing
    fields preserved. No-op if the record doesn't exist (caller can fire-and-forget).
    """
    path = data_dir / secret / f"{slug}.json"
    if not path.exists():
        return
    record = json.loads(path.read_text())
    if total_chunks is not None:
        record["total_chunks"] = total_chunks
    path.write_text(json.dumps(record))


def delete_episode(data_dir: Path, secret: str, slug: str) -> bool:
    """Remove an episode's record and audio from the feed.

    Returns True if the episode existed (its .json was present), False
    otherwise, so the caller can 404 on an unknown slug. Removing the .json
    is what drops the episode from the feed/RSS (both rebuild from the *.json
    files on every request); the .mp3 is best-effort (it may be absent on a
    pending or failed episode).
    """
    user_dir = data_dir / secret
    json_path = user_dir / f"{slug}.json"
    if not json_path.exists():
        return False
    json_path.unlink()
    (user_dir / f"{slug}.mp3").unlink(missing_ok=True)
    return True


def seed_welcome_episode(
    data_dir: Path, secret: str, *,
    welcome_audio: bytes,
) -> str:
    """Write a pre-rendered welcome episode (mp3 + json) into a new user's dir.

    Returns the slug. Unlike write_episode, the title, URL, and description are
    fixed since the welcome is identical for every user.
    """
    slug = _new_slug()
    user_dir = data_dir / secret
    (user_dir / f"{slug}.mp3").write_bytes(welcome_audio)
    (user_dir / f"{slug}.json").write_text(json.dumps({
        "title": "Welcome to Feed Me",
        "url": "https://feed-me.xyz",
        "ts": int(time.time()),
        "description": WELCOME_DESCRIPTION,
        "welcome": True,
    }))
    return slug


def list_episodes(data_dir: Path, secret: str) -> list[dict]:
    user_dir = data_dir / secret
    if not user_dir.is_dir():
        return []
    records = []
    for p in user_dir.glob("*.json"):
        if p.name == "settings.json":
            continue
        try:
            data = json.loads(p.read_text())
            data["slug"] = p.stem
            data["mtime"] = p.stat().st_mtime
            mp3_path = user_dir / f"{p.stem}.mp3"
            if mp3_path.exists():
                data["has_audio"] = True
                data["audio_bytes"] = mp3_path.stat().st_size
            else:
                data["has_audio"] = False
                data["audio_bytes"] = None
            if data.get("error"):
                data["status"] = "failed"
            elif data.get("pending"):
                data["status"] = "pending"
            else:
                data["status"] = "ready"
            records.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    records.sort(key=lambda r: r["mtime"], reverse=True)
    return records


def list_feeds(data_dir: Path) -> list[dict]:
    """One entry per feed dir under data_dir: {"secret", "created_at"}.

    Skips non-directories, the analytics dir, and any dir without settings.json
    (CLAUDE.md gotcha: never assume every entry under /data is a feed).
    created_at falls back to the settings.json mtime when the key is absent.
    """
    if not data_dir.is_dir():
        return []
    feeds = []
    for p in data_dir.iterdir():
        if not p.is_dir() or p.name == "_analytics":
            continue
        settings = p / "settings.json"
        if not settings.is_file():
            continue
        try:
            data = json.loads(settings.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        created = data.get("created_at")
        if created is None:
            created = int(settings.stat().st_mtime)
        feeds.append({"secret": p.name, "created_at": created})
    feeds.sort(key=lambda f: f["created_at"], reverse=True)
    return feeds


def get_settings(data_dir: Path, secret: str) -> dict:
    return json.loads((data_dir / secret / "settings.json").read_text())


def set_voice(data_dir: Path, secret: str, voice: str) -> None:
    if voice not in ALLOWED_VOICES:
        raise ValueError(f"unknown voice: {voice}")
    path = data_dir / secret / "settings.json"
    settings = json.loads(path.read_text())
    settings["voice"] = voice
    path.write_text(json.dumps(settings))


def rotate_secret(data_dir: Path, old_secret: str) -> str:
    new_secret = _secrets.token_urlsafe(32)
    (data_dir / old_secret).rename(data_dir / new_secret)
    return new_secret
