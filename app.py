import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

DATA_DIR = Path(os.environ.get("FEED_ME_DATA_DIR", "/data"))
APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:8000")
SHORTCUT_ICLOUD_URL = os.environ.get(
    "SHORTCUT_ICLOUD_URL",
    "https://www.icloud.com/shortcuts/PLACEHOLDER",
)

app = FastAPI()


@app.get("/healthz", response_class=PlainTextResponse)
def healthz():
    return "ok"
