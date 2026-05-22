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
