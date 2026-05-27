import os
import re
import threading
import time as _time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)
from fastapi.templating import Jinja2Templates

import ingest
import rss
import storage


def relative_time(ts: int, now: int | None = None) -> str:
    """Bucket a unix timestamp into a friendly relative string."""
    if now is None:
        now = int(_time.time())
    delta = now - ts
    if delta < 60:
        return "just now"
    if delta < 3600:
        return f"{delta // 60} min ago"
    if delta < 86400:
        return f"{delta // 3600} h ago"
    if delta < 604800:
        return f"{delta // 86400} d ago"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def spawn_ingest(url: str, secret: str, data_dir: Path) -> None:
    t = threading.Thread(
        target=ingest.process,
        args=(url, secret, data_dir),
        daemon=True,
    )
    t.start()

DATA_DIR = Path(os.environ.get("FEED_ME_DATA_DIR", "/data"))
APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:8000")
SHORTCUT_ICLOUD_URL = os.environ.get(
    "SHORTCUT_ICLOUD_URL",
    "https://www.icloud.com/shortcuts/PLACEHOLDER",
)

SLUG_RE = re.compile(r"^[A-Za-z0-9_-]+$")

app = FastAPI()
templates = Jinja2Templates(directory="templates")


@app.get("/healthz", response_class=PlainTextResponse)
def healthz():
    return "ok"


@app.get("/", response_class=HTMLResponse)
def landing(request: Request):
    return templates.TemplateResponse(request, "landing.html", {})


@app.post("/create")
def create():
    secret = storage.create_user(DATA_DIR)
    return RedirectResponse(f"/u/{secret}", status_code=303)


@app.get("/u/{secret}", response_class=HTMLResponse)
def settings(request: Request, secret: str):
    if not storage.user_exists(DATA_DIR, secret):
        raise HTTPException(404)
    s = storage.get_settings(DATA_DIR, secret)
    eps = storage.list_episodes(DATA_DIR, secret)[:30]
    now_ts = int(_time.time())
    for ep in eps:
        ep["when"] = relative_time(ep["ts"], now=now_ts)
    feed_url = f"{APP_BASE_URL}/u/{secret}/feed.xml"
    ingest_url = f"{APP_BASE_URL}/u/{secret}/ingest"
    feed_host_and_path = feed_url.split("://", 1)[1]
    return templates.TemplateResponse(request, "settings.html", {
        "secret": secret,
        "current_voice": s["voice"],
        "voices": sorted(storage.ALLOWED_VOICES),
        "episodes": eps,
        "feed_url": feed_url,
        "ingest_url": ingest_url,
        "feed_host_and_path": feed_host_and_path,
        "shortcut_url": SHORTCUT_ICLOUD_URL,
    })


@app.post("/u/{secret}/voice")
def set_voice_route(secret: str, voice: str = Form(...)):
    if not storage.user_exists(DATA_DIR, secret):
        raise HTTPException(404)
    try:
        storage.set_voice(DATA_DIR, secret, voice)
    except ValueError:
        raise HTTPException(400)
    return RedirectResponse(f"/u/{secret}", status_code=303)


@app.post("/u/{secret}/rotate")
def rotate_route(secret: str):
    if not storage.user_exists(DATA_DIR, secret):
        raise HTTPException(404)
    new = storage.rotate_secret(DATA_DIR, secret)
    return RedirectResponse(f"/u/{new}", status_code=303)


@app.get("/u/{secret}/ingest")
def ingest_route(secret: str, url: str):
    if not storage.user_exists(DATA_DIR, secret):
        raise HTTPException(404)
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(400, "invalid url")
    spawn_ingest(url, secret, DATA_DIR)
    return {"ok": True}


@app.get("/u/{secret}/feed.xml")
def feed_route(secret: str):
    if not storage.user_exists(DATA_DIR, secret):
        raise HTTPException(404)
    eps = storage.list_episodes(DATA_DIR, secret)
    xml = rss.render_feed(
        feed_url=f"{APP_BASE_URL}/u/{secret}/feed.xml",
        audio_base=f"{APP_BASE_URL}/u/{secret}/audio",
        episodes=eps,
    )
    return Response(
        content=xml,
        media_type="application/rss+xml",
        headers={"Cache-Control": "max-age=60"},
    )


@app.get("/u/{secret}/audio/{slug}.mp3")
def audio_route(secret: str, slug: str):
    if not storage.user_exists(DATA_DIR, secret):
        raise HTTPException(404)
    if not SLUG_RE.match(slug):
        raise HTTPException(404)
    path = DATA_DIR / secret / f"{slug}.mp3"
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, media_type="audio/mpeg")
