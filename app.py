import hmac
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
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)
from fastapi.templating import Jinja2Templates

import analytics
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


def hostname(url: str) -> str:
    """Return the hostname portion of a URL (no scheme, no path).
    On unparseable input, returns the input unchanged so the template stays sane."""
    try:
        parsed = urlparse(url)
        return parsed.netloc or url
    except Exception:
        return url


WELCOME_URL = "https://feed-me.xyz"


def _is_welcome(ep: dict) -> bool:
    """The seeded welcome episode (flagged on new feeds, URL-matched on old)."""
    return bool(ep.get("welcome")) or ep.get("url") == WELCOME_URL


def spawn_ingest(url: str, secret: str, data_dir: Path, slug: str) -> None:
    t = threading.Thread(
        target=ingest.process,
        args=(url, secret, data_dir),
        kwargs={"slug": slug},
        daemon=True,
    )
    t.start()

DATA_DIR = Path(os.environ.get("FEED_ME_DATA_DIR", "/data"))
STATIC_DIR = Path(__file__).parent / "static"
WELCOME_AUDIO_BYTES = (STATIC_DIR / "welcome.mp3").read_bytes()
APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:8000")
SHORTCUT_ICLOUD_URL = os.environ.get(
    "SHORTCUT_ICLOUD_URL",
    "https://www.icloud.com/shortcuts/PLACEHOLDER",
)
STATS_TOKEN = os.environ.get("STATS_TOKEN")

COOKIE_NAME = "fm_session"
COOKIE_MAX_AGE = 60 * 60 * 24 * 365  # 1 year


def set_session_cookie(response: Response, secret: str) -> None:
    """Link this browser to a feed. The cookie value IS the secret.

    HttpOnly so JS can't read it; Secure only when serving over https
    (APP_BASE_URL is read at call time so tests/local-dev over http still
    round-trip the cookie); SameSite=Lax so it rides the top-level GET
    navigation that the Shortcut's "Open URLs" action performs.
    """
    response.set_cookie(
        COOKIE_NAME,
        secret,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        secure=APP_BASE_URL.startswith("https"),
        samesite="lax",
        path="/",
    )


def _analytics_db():
    # Built at call time (not import) so monkeypatched DATA_DIR resolves correctly.
    return DATA_DIR / "_analytics" / "analytics.db"


def _track(event, *, secret=None, path=None, props=None):
    try:
        fh = analytics.feed_hash(secret) if secret else None
        analytics.track(_analytics_db(), event, feed_hash=fh, path=path, props=props)
    except Exception:
        pass  # analytics must never affect the request


def _check_stats_token(token: str) -> None:
    # 404 (not 401/403) on any failure — reveal nothing about the route.
    if not STATS_TOKEN or not token or not hmac.compare_digest(token, STATS_TOKEN):
        raise HTTPException(404)


SLUG_RE = re.compile(r"^[A-Za-z0-9_-]+$")

app = FastAPI()
templates = Jinja2Templates(directory="templates")
templates.env.filters["hostname"] = hostname


@app.get("/healthz", response_class=PlainTextResponse)
def healthz():
    return "ok"


@app.get("/share", response_class=HTMLResponse)
def share_route(request: Request, url: str = ""):
    secret = request.cookies.get(COOKIE_NAME)
    if not secret or not storage.user_exists(DATA_DIR, secret):
        return templates.TemplateResponse(request, "share.html", {"state": "connect"})

    home_url = f"{APP_BASE_URL}/u/{secret}"
    parsed = urlparse(url)
    if not url or parsed.scheme not in ("http", "https") or not parsed.netloc:
        error_msg = (
            "Shortcut sent no article URL."
            if not url
            else f"Invalid URL: {url[:200]!r} — must be http or https."
        )
        storage.write_failed_episode(
            DATA_DIR, secret,
            source_url=(url or "(empty share)"), error=error_msg,
        )
        return templates.TemplateResponse(
            request, "share.html",
            {"state": "error", "error": error_msg, "home_url": home_url},
        )

    # Quick title fetch so the confirmation page + pending row show the real
    # title (mirrors the old ingest route). On failure fetch_title returns None
    # and we fall back to the hostname.
    title = ingest.fetch_title(url)
    slug = storage.write_pending_episode(
        DATA_DIR, secret, source_url=url, title=title,
    )
    spawn_ingest(url, secret, DATA_DIR, slug)
    _track("page_view", secret=secret, path="share")    # the share confirmation page rendered
    _track("article_shared", secret=secret, path="share")
    return templates.TemplateResponse(
        request, "share.html",
        {"state": "added", "title": title or hostname(url),
         "slug": slug, "home_url": home_url},
    )


@app.get("/share/status")
def share_status(request: Request, slug: str = ""):
    """Cookie-authed JSON status for one episode, polled by the /share page."""
    secret = request.cookies.get(COOKIE_NAME)
    if not secret or not slug or not storage.user_exists(DATA_DIR, secret):
        return JSONResponse({"status": "unknown"})
    for ep in storage.list_episodes(DATA_DIR, secret):
        if ep["slug"] == slug:
            return JSONResponse({
                "status": ep["status"],
                "total_chunks": ep.get("total_chunks"),
                "ts": ep["ts"],
                "error": ep.get("error"),
            })
    return JSONResponse({"status": "unknown"})


@app.get("/cover.jpg")
def cover_route():
    return FileResponse(
        STATIC_DIR / "cover.jpg",
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


def _icon(name: str, media_type: str) -> FileResponse:
    return FileResponse(
        STATIC_DIR / name,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=604800"},
    )


@app.get("/favicon.ico")
def favicon_ico():
    return _icon("favicon.ico", "image/x-icon")


@app.get("/favicon-32.png")
def favicon_png():
    return _icon("favicon-32.png", "image/png")


@app.get("/apple-touch-icon.png")
@app.get("/apple-touch-icon-precomposed.png")
def apple_touch_icon():
    return _icon("apple-touch-icon.png", "image/png")


@app.get("/og.png")
def og_route():
    return _icon("og.png", "image/png")


@app.get("/admin/export")
def admin_export(token: str = ""):
    _check_stats_token(token)
    db = _analytics_db()
    return JSONResponse(
        {"summary": analytics.summary(db), "events": analytics.all_events(db)}
    )


@app.get("/admin/stats", response_class=HTMLResponse)
def admin_stats(request: Request, token: str = ""):
    _check_stats_token(token)
    return templates.TemplateResponse(
        request, "admin_stats.html", {"s": analytics.summary(_analytics_db())},
    )


@app.get("/", response_class=HTMLResponse)
def landing(request: Request):
    _track("page_view", path="landing")
    return templates.TemplateResponse(request, "landing.html", {"base_url": APP_BASE_URL})


@app.post("/create")
def create():
    secret = storage.create_user(DATA_DIR)
    storage.seed_welcome_episode(
        DATA_DIR, secret, welcome_audio=WELCOME_AUDIO_BYTES,
    )
    _track("feed_created", secret=secret)
    return RedirectResponse(f"/u/{secret}", status_code=303)


@app.get("/u/{secret}", response_class=HTMLResponse)
def settings(request: Request, secret: str):
    if not storage.user_exists(DATA_DIR, secret):
        raise HTTPException(404)
    _track("page_view", secret=secret, path="settings")
    s = storage.get_settings(DATA_DIR, secret)
    eps = storage.list_episodes(DATA_DIR, secret)[:30]
    now_ts = int(_time.time())
    for ep in eps:
        ep["when"] = relative_time(ep["ts"], now=now_ts)
    feed_url = f"{APP_BASE_URL}/u/{secret}/feed.xml"
    feed_host_and_path = feed_url.split("://", 1)[1]
    # "Setup done" once the user has shared at least one real article (any
    # episode beyond the seeded welcome). Then we lead with their episodes and
    # fold the instructions away.
    setup_done = any(not _is_welcome(ep) for ep in eps)
    response = templates.TemplateResponse(request, "settings.html", {
        "secret": secret,
        "current_voice": s["voice"],
        "voices": sorted(storage.ALLOWED_VOICES),
        "episodes": eps,
        "feed_url": feed_url,
        "feed_host_and_path": feed_host_and_path,
        "shortcut_url": SHORTCUT_ICLOUD_URL,
        "setup_done": setup_done,
    })
    set_session_cookie(response, secret)
    return response


@app.get("/u/{secret}/episodes_partial", response_class=HTMLResponse)
def episodes_partial(request: Request, secret: str):
    if not storage.user_exists(DATA_DIR, secret):
        raise HTTPException(404)
    eps = storage.list_episodes(DATA_DIR, secret)[:30]
    now_ts = int(_time.time())
    for ep in eps:
        ep["when"] = relative_time(ep["ts"], now=now_ts)
    return templates.TemplateResponse(request, "_episodes_section.html", {
        "episodes": eps,
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


@app.get("/u/{secret}/feed.xml")
def feed_route(secret: str):
    if not storage.user_exists(DATA_DIR, secret):
        raise HTTPException(404)
    eps = storage.list_episodes(DATA_DIR, secret)
    xml = rss.render_feed(
        feed_url=f"{APP_BASE_URL}/u/{secret}/feed.xml",
        audio_base=f"{APP_BASE_URL}/u/{secret}/audio",
        cover_url=f"{APP_BASE_URL}/cover.jpg",
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
