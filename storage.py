import json
import secrets as _secrets
import time
from pathlib import Path

DEFAULT_VOICE = "shimmer"


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
) -> str:
    slug = _new_slug()
    user_dir = data_dir / secret
    (user_dir / f"{slug}.mp3").write_bytes(audio)
    (user_dir / f"{slug}.json").write_text(json.dumps({
        "title": title,
        "url": source_url,
        "ts": int(time.time()),
    }))
    return slug


def write_failed_episode(
    data_dir: Path, secret: str, *,
    source_url: str, error: str,
) -> str:
    slug = _new_slug()
    (data_dir / secret / f"{slug}.json").write_text(json.dumps({
        "title": None,
        "url": source_url,
        "ts": int(time.time()),
        "error": error,
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
            data["has_audio"] = (user_dir / f"{p.stem}.mp3").exists()
            records.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    records.sort(key=lambda r: r["mtime"], reverse=True)
    return records
