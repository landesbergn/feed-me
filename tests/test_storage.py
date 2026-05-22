import json
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
