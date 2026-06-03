import json
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


def write_episode(
    data_dir: Path, secret: str, *,
    title: str, source_url: str, audio: bytes,
    slug: str | None = None,
    description: str | None = None,
) -> str:
    if slug is None:
        slug = _new_slug()
    user_dir = data_dir / secret
    (user_dir / f"{slug}.mp3").write_bytes(audio)
    record = {
        "title": title,
        "url": source_url,
        "ts": int(time.time()),
    }
    if description is not None:
        record["description"] = description
    (user_dir / f"{slug}.json").write_text(json.dumps(record))
    return slug


def write_failed_episode(
    data_dir: Path, secret: str, *,
    source_url: str, error: str,
    slug: str | None = None,
    description: str | None = None,
) -> str:
    if slug is None:
        slug = _new_slug()
    record = {
        "title": None,
        "url": source_url,
        "ts": int(time.time()),
        "error": error,
    }
    if description is not None:
        record["description"] = description
    (data_dir / secret / f"{slug}.json").write_text(json.dumps(record))
    return slug


def write_pending_episode(
    data_dir: Path, secret: str, *,
    source_url: str,
    title: str | None = None,
    description: str | None = None,
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
    for p in sorted(data_dir.iterdir()):
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
