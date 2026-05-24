import os
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import storage

DATA_DIR = Path(os.environ.get("FEED_ME_DATA_DIR", "/data"))
APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:8000")
SHORTCUT_ICLOUD_URL = os.environ.get(
    "SHORTCUT_ICLOUD_URL",
    "https://www.icloud.com/shortcuts/PLACEHOLDER",
)

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
