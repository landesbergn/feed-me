import hmac
import json
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
from starlette.concurrency import run_in_threadpool

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


def _fmt_utc(ts: int) -> str:
    """Format a unix timestamp as 'YYYY-MM-DD HH:MM' UTC (matches recent_shares)."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


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


def spawn_ingest(url: str, secret: str, data_dir: Path, slug: str, *, text=None, title=None) -> None:
    t = threading.Thread(
        target=ingest.process,
        args=(url, secret, data_dir),
        kwargs={"slug": slug, "text": text, "title": title},
        daemon=True,
    )
    t.start()

DATA_DIR = Path(os.environ.get("FEED_ME_DATA_DIR", "/data"))
STATIC_DIR = Path(__file__).parent / "static"
TEMPLATES_DIR = Path(__file__).parent / "templates"
WELCOME_AUDIO_BYTES = (STATIC_DIR / "welcome.mp3").read_bytes()
APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:8000")
SHORTCUT_ICLOUD_URL = os.environ.get(
    "SHORTCUT_ICLOUD_URL",
    "https://www.icloud.com/shortcuts/PLACEHOLDER",
)
# Second, optional Shortcut: extracts article text on-device (Safari's
# rendered page, subscriber session included) and posts it to
# /u/<secret>/share-text. Unset until the Shortcut is published, which hides
# its row on the settings page.
SHORTCUT_TEXT_ICLOUD_URL = os.environ.get("SHORTCUT_TEXT_ICLOUD_URL", "")
STATS_TOKEN = os.environ.get("STATS_TOKEN")

COOKIE_NAME = "fm_session"
COOKIE_MAX_AGE = 60 * 60 * 24 * 365  # 1 year

AGENT_DAILY_CAP = 5            # agent-created episodes per feed, rolling 24h
# Per-feed character budget over the same rolling window. Characters map to TTS
# cost (tts-1 is $15 / 1M chars), so this caps narration spend per feed at
# ~$4.50/day independent of how the episodes are split. Tune this literal.
AGENT_FEED_CHAR_BUDGET = 300_000
AGENT_CAP_WINDOW_S = 86400

# The Shortcut's on-device-extraction path (POST /u/<secret>/share-text) is a
# person sharing what they read, not an automation, so the agent cap of 5/day
# would cut them off mid-morning. Same rolling window and same per-feed
# character budget (the real cost guard); only the episode count differs.
SHORTCUT_DAILY_CAP = 30

# Feed hashes (analytics.feed_hash of the secret) hard-blocked from generating
# new audio. Matching on the one-way hash means the raw secret never appears in
# source or logs. A blocked feed still serves its existing episodes and RSS;
# only new TTS (agent API + share) is refused, with a 403 so the caller knows
# the block is deliberate. Reversible: drop the hash and redeploy. Add a feed
# here after confirming its cost via /admin/stats.
BLOCKED_FEED_HASHES = frozenset({"dd8d9ed021f8"})


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
        analytics.track(_analytics_db(), event, feed_hash_val=fh, path=path, props=props)
    except Exception:
        pass  # analytics must never affect the request


def _is_blocked(secret: str) -> bool:
    """True if this feed is hard-blocked from new TTS (see BLOCKED_FEED_HASHES).
    Compares the one-way feed hash so the raw secret is never matched here."""
    return analytics.feed_hash(secret) in BLOCKED_FEED_HASHES


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


@app.get("/AGENTS.md")
def agents_md_route():
    # Plain .replace, not Jinja (autoescape would mangle the JSON examples)
    # and not str.format (the JSON braces would break it). Read at request
    # time so tests that monkeypatch APP_BASE_URL see the right base.
    text = (TEMPLATES_DIR / "agents.md").read_text().replace(
        "{base}", APP_BASE_URL,
    )
    return PlainTextResponse(text, media_type="text/markdown")


@app.get("/llms.txt")
def llms_txt_route():
    return PlainTextResponse(
        "Feed Me turns shared articles into narrated episodes in a private "
        "podcast feed.\n"
        f"API documentation for agents: {APP_BASE_URL}/AGENTS.md\n"
        "Browsing with WebMCP? The landing page and feed pages register "
        "their own tools; see the 'In a browser' section of AGENTS.md.\n"
    )


# Share sheets are inconsistent: some apps (the NYT / Athletic app among them)
# hand the Shortcut the article's headline or dek as text instead of the link,
# sometimes with the link tacked on. Pull the first http(s) URL out of whatever
# arrives so a text share still works when a link is in there anywhere.
_URL_IN_TEXT = re.compile(r"https?://[^\s<>\"'`]+")


def extract_shared_url(raw: str) -> str:
    """Return a usable http(s) URL from a share payload, or "" if there is none."""
    raw = (raw or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme in ("http", "https") and parsed.netloc:
        return raw
    match = _URL_IN_TEXT.search(raw)
    if not match:
        return ""
    candidate = match.group(0).rstrip(".,;:!?)]}")
    return candidate if urlparse(candidate).netloc else ""


@app.get("/share", response_class=HTMLResponse)
def share_route(request: Request, url: str = ""):
    secret = request.cookies.get(COOKIE_NAME)
    if not secret or not storage.user_exists(DATA_DIR, secret):
        return templates.TemplateResponse(request, "share.html", {"state": "connect"})

    home_url = f"{APP_BASE_URL}/u/{secret}"
    if _is_blocked(secret):
        return templates.TemplateResponse(
            request, "share.html", {"state": "blocked", "home_url": home_url},
        )
    shared = extract_shared_url(url)
    if not shared:
        if not url.strip():
            error_msg = "No article added. Open an article, tap Share, then tap Feed Me."
        elif re.match(r"[a-zA-Z][a-zA-Z0-9+.\-]*://", url.strip()):
            error_msg = f"Invalid URL: {url[:200]!r} (must be http or https)."
        else:
            # The app shared text with no link in it at all (v3.19: the NYT app
            # hands over the article dek). Tell her how to get a link instead.
            error_msg = (
                "That share didn't include a link, just text: "
                f"{url[:100]!r}. Open the article in Safari and share from "
                "there, or use the app's Copy Link and share the link."
            )
        storage.write_failed_episode(
            DATA_DIR, secret,
            source_url=(url[:120] or "(empty share)"), error=error_msg,
        )
        return templates.TemplateResponse(
            request, "share.html",
            {"state": "error", "error": error_msg, "home_url": home_url},
        )

    # Quick title fetch so the confirmation page + pending row show the real
    # title (mirrors the old ingest route). On failure fetch_title returns None
    # and we fall back to the hostname.
    title = ingest.fetch_title(shared)
    slug = storage.write_pending_episode(
        DATA_DIR, secret, source_url=shared, title=title,
    )
    spawn_ingest(shared, secret, DATA_DIR, slug)
    _track("page_view", secret=secret, path="share")    # the share confirmation page rendered
    _track("article_shared", secret=secret, path="share",
           props={"url": shared, "title": title, "via": "shortcut"})
    return templates.TemplateResponse(
        request, "share.html",
        {"state": "added", "title": title or hostname(shared),
         "slug": slug, "home_url": home_url},
    )


@app.get("/share/text", response_class=HTMLResponse)
def share_text_page(request: Request):
    """Landing page for the Full Text Shortcut.

    The Shortcut opens this URL in Safari with the article text in the
    fragment (#t=...&title=...&u=...), so the browser's fm_session cookie
    identifies the feed and the Shortcut stays identical for every user. The
    fragment is never sent to the server: the page's JS reads it and posts it
    back here as a form. A share with no fragment (a very long article, where
    the URL didn't survive) falls back to a paste box.
    """
    secret = request.cookies.get(COOKIE_NAME)
    if not secret or not storage.user_exists(DATA_DIR, secret):
        return templates.TemplateResponse(request, "share.html", {"state": "connect"})
    home_url = f"{APP_BASE_URL}/u/{secret}"
    if _is_blocked(secret):
        return templates.TemplateResponse(
            request, "share.html", {"state": "blocked", "home_url": home_url},
        )
    return templates.TemplateResponse(
        request, "share_text.html",
        {"home_url": home_url, "base_url": APP_BASE_URL},
    )


@app.post("/share/text", response_class=HTMLResponse)
async def share_text_submit(request: Request):
    """Cookie-authed twin of POST /u/<secret>/share-text: the form the
    /share/text page submits with the text it read out of the fragment."""
    secret = request.cookies.get(COOKIE_NAME)
    if not secret or not storage.user_exists(DATA_DIR, secret):
        return templates.TemplateResponse(request, "share.html", {"state": "connect"})
    home_url = f"{APP_BASE_URL}/u/{secret}"
    if _is_blocked(secret):
        return templates.TemplateResponse(
            request, "share.html", {"state": "blocked", "home_url": home_url},
        )

    form = await request.form()
    url = form.get("url") or ""
    text = form.get("text")
    try:
        slug, title, chars = _create_text_episode(
            secret, text, form.get("title"), url,
        )
    except TextShareError as err:
        # Keep what actually arrived. A link preview and a truncated article
        # are the same length; only the content tells them apart.
        received = (
            f"Shortcut sent: {str(text)[:160]}" if isinstance(text, str) and text.strip()
            else None
        )
        storage.write_failed_episode(
            DATA_DIR, secret, source_url=url or "(shared text)",
            error=err.message, description=received,
        )
        return templates.TemplateResponse(
            request, "share.html",
            {"state": "error", "error": err.message, "home_url": home_url},
        )

    _track("page_view", secret=secret, path="share-text")
    _track("article_shared", secret=secret, path="share-text",
           props={"url": url, "title": title, "via": "shortcut"})
    return templates.TemplateResponse(
        request, "share.html",
        {"state": "added", "title": title, "slug": slug, "home_url": home_url,
         "chars": chars},
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


def _agent_error(status: int, code: str, message: str,
                 headers: dict | None = None) -> JSONResponse:
    """Stable JSON error shape for the agent API: {"error", "message"}."""
    return JSONResponse(
        {"error": code, "message": message},
        status_code=status, headers=headers,
    )


def _episodes_in_window(secret: str, via: str, now: int) -> list[dict]:
    """Episodes (any status) created through one entry point inside the rolling
    cap window. Each entry point meters itself: an agent push must not spend a
    person's allowance, or the reverse."""
    return [
        ep for ep in storage.list_episodes(DATA_DIR, secret)
        if ep.get("via") == via and ep["ts"] > now - AGENT_CAP_WINDOW_S
    ]


def _agent_episodes_in_window(secret: str, now: int) -> list[dict]:
    """Agent-created episodes (any status) inside the rolling cap window."""
    return _episodes_in_window(secret, "agent", now)


@app.post("/u/{secret}/episodes")
async def create_episode_api(request: Request, secret: str):
    """Agent-facing episode creation (documented at /AGENTS.md).

    Two modes. URL mode: {"url": "..."} fetches and narrates the article.
    Text mode: {"text": "...", "title": "..."} narrates the supplied text
    directly (no fetch), with an optional {"url": "..."} as the source link.
    Authenticates solely by the path secret; the fm_session cookie is never
    read or set. Parses the body manually so malformed JSON is the documented
    400, not FastAPI's 422.
    """
    if not storage.user_exists(DATA_DIR, secret):
        return _agent_error(404, "not_found", "No feed at this URL.")
    if _is_blocked(secret):
        return _agent_error(
            403, "suspended",
            "This feed is suspended due to unusually high narration volume. "
            "Contact Noah at https://noahlandesberg.com to restore access.",
        )
    try:
        payload = json.loads(await request.body())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _agent_error(
            400, "invalid_request",
            'Body must be JSON: {"url": "https://..."} or {"text": "...", "title": "..."}.',
        )
    if not isinstance(payload, dict):
        return _agent_error(
            400, "invalid_request",
            'Body must include a string "url" or "text" field.',
        )

    note = payload.get("note")
    if note is not None:
        if not isinstance(note, str):
            return _agent_error(
                400, "invalid_request", 'Optional "note" must be a string.',
            )
        if len(note) > 300:
            return _agent_error(
                400, "invalid_request",
                f"Note too long: {len(note):,} characters (limit 300).",
            )
        note = note.strip() or None

    text = payload.get("text")
    text_mode = isinstance(text, str) and bool(text.strip())

    if text_mode:
        title = payload.get("title")
        if not isinstance(title, str) or not title.strip():
            return _agent_error(
                400, "invalid_request", "Text requires a non-empty title.",
            )
        if len(text) > ingest.MAX_BODY_CHARS:
            return _agent_error(
                400, "invalid_request",
                f"Text too long: {len(text):,} characters "
                f"(limit {ingest.MAX_BODY_CHARS:,}).",
            )
        url = payload.get("url")
        if url is not None:
            parsed = urlparse(url) if isinstance(url, str) else None
            if parsed is None or parsed.scheme not in ("http", "https") or not parsed.netloc:
                return _agent_error(
                    400, "invalid_url",
                    f"Invalid URL: {str(url)[:200]!r} (must be http or https).",
                )
        source_url = url or ""
        episode_title = title.strip()
    else:
        url = payload.get("url")
        if not isinstance(url, str) or not url:
            return _agent_error(
                400, "invalid_request",
                'Body must include a string "url" or "text" field.',
            )
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return _agent_error(
                400, "invalid_url",
                f"Invalid URL: {url[:200]!r} (must be http or https).",
            )
        source_url = url
        episode_title = None

    now = int(_time.time())
    in_window = _agent_episodes_in_window(secret, now)
    if len(in_window) >= AGENT_DAILY_CAP:
        retry_after = max(
            1, min(ep["ts"] for ep in in_window) + AGENT_CAP_WINDOW_S - now,
        )
        return _agent_error(
            429, "rate_limited",
            f"Agent cap reached: {AGENT_DAILY_CAP} episodes per feed per "
            "rolling 24 hours. Do not retry before Retry-After elapses; "
            "tell the user.",
            headers={"Retry-After": str(retry_after)},
        )

    # Per-feed character budget (TTS cost). Text mode knows its length up front,
    # so it is checked exactly; URL mode has no confirmed length until the fetch,
    # so it is blocked only once the feed is already at/over budget.
    spent = sum(int(ep.get("chars") or 0) for ep in in_window)
    remaining_budget = AGENT_FEED_CHAR_BUDGET - spent
    incoming = len(text) if text_mode else 0
    over_budget = incoming > remaining_budget if text_mode else remaining_budget <= 0
    if over_budget:
        retry_after = max(
            1, min(ep["ts"] for ep in in_window) + AGENT_CAP_WINDOW_S - now,
        ) if in_window else AGENT_CAP_WINDOW_S
        detail = (
            f"; this {incoming:,}-character request would exceed the budget."
            if text_mode else " and is at its budget."
        )
        return _agent_error(
            429, "budget_exceeded",
            f"Feed narration budget reached: {AGENT_FEED_CHAR_BUDGET:,} "
            "characters per feed per rolling 24 hours (a total-volume cap that "
            f"limits narration cost). This feed has narrated {spent:,} of "
            f"{AGENT_FEED_CHAR_BUDGET:,} characters in the last 24 hours"
            f"{detail} The budget frees as older episodes age out; do not retry "
            "before Retry-After elapses. Splitting the text into smaller pieces "
            "or opening more requests will not raise the cap (it is a per-feed "
            "total, not per-episode) and will stay blocked. Tell the user their "
            "feed hit its 24-hour narration budget.",
            headers={"Retry-After": str(retry_after)},
        )

    if text_mode:
        record_title = episode_title
        spawn_text, spawn_title = text, episode_title
    else:
        # fetch_title blocks on the network; run it off the event loop.
        record_title = await run_in_threadpool(ingest.fetch_title, url)
        spawn_text, spawn_title = None, None

    slug = storage.write_pending_episode(
        DATA_DIR, secret, source_url=source_url, title=record_title, via="agent",
        chars=incoming if text_mode else None, note=note,
    )
    spawn_ingest(source_url, secret, DATA_DIR, slug, text=spawn_text, title=spawn_title)
    _track("article_shared", secret=secret, path="agent",
           props={"url": source_url, "title": record_title, "via": "agent"})
    return JSONResponse({
        "slug": slug,
        "status": "pending",
        "title": record_title,
        "status_url": f"{APP_BASE_URL}/u/{secret}/episodes/{slug}",
        "feed_page": f"{APP_BASE_URL}/u/{secret}",
        "remaining": AGENT_DAILY_CAP - len(in_window) - 1,
        "budget_remaining_chars": max(0, remaining_budget - incoming),
    }, status_code=202)


class TextShareError(Exception):
    """A text share that can't become an episode. `code` is the agent API's
    error code; `message` is user-facing copy (it lands on the share page and
    in the failed-episode row), so keep it friendly."""

    def __init__(self, code: str, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.code, self.message, self.retry_after = code, message, retry_after


def _create_text_episode(secret: str, text, title, url) -> tuple[str, str, int]:
    """Validate, meter and start narration of text extracted on the user's
    phone. Shared by the secret-authed API route and the cookie-authed page.
    Returns (slug, title, chars); raises TextShareError."""
    if not isinstance(text, str) or not text.strip():
        raise TextShareError(
            "invalid_request",
            "No article text arrived. Open the article in Safari, then share "
            "it to Feed Me Full Text.",
        )
    if len(text) > ingest.MAX_BODY_CHARS:
        raise TextShareError(
            "invalid_request",
            f"That article is too long to narrate: {len(text):,} characters "
            f"(limit {ingest.MAX_BODY_CHARS:,}).",
        )
    if len(text.strip()) < ingest.MIN_BODY_CHARS:
        # Same threshold the fetch path uses to spot a teaser. Here it catches
        # a share that lost its article in transit (unencoded text in the URL
        # fragment breaks at the first space), which otherwise becomes an
        # 8-second episode of the headline.
        raise TextShareError(
            "invalid_request",
            f"Only {len(text.strip()):,} characters of text arrived, too "
            "little to be the article. In the Shortcut, check that Open URLs "
            "uses the URL Encoded Text variable, not the raw article text.",
        )
    url = url or ""
    if url:
        parsed = urlparse(url) if isinstance(url, str) else None
        if parsed is None or parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise TextShareError(
                "invalid_url",
                f"Invalid URL: {str(url)[:200]!r} (must be http or https).",
            )
    title = title.strip() if isinstance(title, str) else ""
    if not title:
        # Get Details of Article can hand back an empty name; the first line of
        # the extracted text is the headline often enough to beat failing.
        first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
        title = first_line[:120] or hostname(url) or "Shared article"

    now = int(_time.time())
    in_window = _episodes_in_window(secret, "shortcut", now)
    oldest_expiry = (
        max(1, min(ep["ts"] for ep in in_window) + AGENT_CAP_WINDOW_S - now)
        if in_window else AGENT_CAP_WINDOW_S
    )
    if len(in_window) >= SHORTCUT_DAILY_CAP:
        raise TextShareError(
            "rate_limited",
            f"Daily cap reached: {SHORTCUT_DAILY_CAP} shared articles per feed "
            "per rolling 24 hours. Older shares age out of the window.",
            retry_after=oldest_expiry,
        )
    spent = sum(int(ep.get("chars") or 0) for ep in in_window)
    remaining_budget = AGENT_FEED_CHAR_BUDGET - spent
    if len(text) > remaining_budget:
        raise TextShareError(
            "budget_exceeded",
            f"Feed narration budget reached: {AGENT_FEED_CHAR_BUDGET:,} "
            "characters per feed per rolling 24 hours (this caps narration "
            f"cost). This feed has narrated {spent:,} characters in the last "
            f"24 hours; this {len(text):,}-character share would exceed it. "
            "The budget frees as older episodes age out.",
            retry_after=oldest_expiry,
        )

    slug = storage.write_pending_episode(
        DATA_DIR, secret, source_url=url, title=title, via="shortcut",
        chars=len(text),
    )
    spawn_ingest(url, secret, DATA_DIR, slug, text=text, title=title)
    return slug, title, len(text)


@app.post("/u/{secret}/share-text")
async def share_text_route(request: Request, secret: str):
    """Narrate article text extracted on the user's phone.

    The iOS Shortcut runs Get Article from Web Page on the page Safari has
    already rendered, so a subscriber's session does the unlocking on-device
    and Feed Me never fetches the URL. This is the only path that works for
    sites that refuse server fetches outright (verified: nytimes.com article
    pages 403 every non-browser client, gift links included).

    Authenticates by the path secret alone, like the agent API: never read or
    set the session cookie here. Accepts JSON or a form body, because
    Shortcuts' Get Contents of URL posts a form by default. Errors keep the
    agent API's {"error", "message"} shape.
    """
    if not storage.user_exists(DATA_DIR, secret):
        return _agent_error(404, "not_found", "No feed at this URL.")
    if _is_blocked(secret):
        return _agent_error(
            403, "suspended",
            "This feed is suspended due to unusually high narration volume. "
            "Contact Noah at https://noahlandesberg.com to restore access.",
        )

    body = await request.body()
    payload: dict = {}
    try:
        parsed_json = json.loads(body)
        if isinstance(parsed_json, dict):
            payload = parsed_json
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = dict(await request.form())

    try:
        slug, title, _chars = _create_text_episode(
            secret, payload.get("text"), payload.get("title"), payload.get("url"),
        )
    except TextShareError as err:
        status = {
            "invalid_request": 400, "invalid_url": 400,
            "rate_limited": 429, "budget_exceeded": 429,
        }[err.code]
        headers = (
            {"Retry-After": str(err.retry_after)} if err.retry_after else None
        )
        return _agent_error(status, err.code, err.message, headers=headers)

    _track("article_shared", secret=secret, path="share-text",
           props={"url": payload.get("url") or "", "title": title,
                  "via": "shortcut"})
    return JSONResponse({
        "slug": slug,
        "status": "pending",
        "title": title,
        "feed_page": f"{APP_BASE_URL}/u/{secret}",
    }, status_code=202)


@app.get("/u/{secret}/episodes")
def list_episodes_api(secret: str):
    """Agent-facing feed listing + confirmation (documented at /AGENTS.md).

    Path-secret auth, JSON only, no cookies. Returns the 20 most recent
    episodes (newest first) plus the feed voice and the agent's remaining
    24h quota. Doubles as the cheap feed-exists check: a 404 means the
    secret is wrong or was rotated. The per-episode poll twin is
    GET /u/{secret}/episodes/{slug}.
    """
    if not storage.user_exists(DATA_DIR, secret):
        return _agent_error(404, "not_found", "No feed at this URL.")
    now = int(_time.time())
    in_window = _agent_episodes_in_window(secret, now)
    remaining = max(0, AGENT_DAILY_CAP - len(in_window))
    spent = sum(int(ep.get("chars") or 0) for ep in in_window)
    budget_remaining = max(0, AGENT_FEED_CHAR_BUDGET - spent)
    episodes = []
    for ep in storage.list_episodes(DATA_DIR, secret)[:20]:
        slug = ep["slug"]
        item = {
            "slug": slug,
            "title": ep.get("title"),
            "status": ep["status"],
            "ts": ep["ts"],
        }
        if ep["status"] == "ready":
            item["audio_url"] = f"{APP_BASE_URL}/u/{secret}/audio/{slug}.mp3"
        elif ep["status"] == "failed":
            item["error"] = ep.get("error")
        episodes.append(item)
    return JSONResponse({
        "feed_page": f"{APP_BASE_URL}/u/{secret}",
        "feed_url": f"{APP_BASE_URL}/u/{secret}/feed.xml",
        "voice": storage.get_settings(DATA_DIR, secret)["voice"],
        "remaining": remaining,
        "budget_remaining_chars": budget_remaining,
        "episodes": episodes,
    })


@app.get("/u/{secret}/episodes/{slug}")
def episode_status_api(secret: str, slug: str):
    """Agent-facing episode status (documented at /AGENTS.md). Path-secret
    auth, JSON only, no cookies; the cookie-authed twin is /share/status."""
    if not storage.user_exists(DATA_DIR, secret):
        return _agent_error(404, "not_found", "No feed at this URL.")
    if not SLUG_RE.match(slug):
        return _agent_error(404, "not_found", "No such episode.")
    for ep in storage.list_episodes(DATA_DIR, secret):
        if ep["slug"] == slug:
            payload = {
                "slug": slug,
                "status": ep["status"],
                "title": ep.get("title"),
                "ts": ep["ts"],
                "total_chunks": ep.get("total_chunks"),
                "error": ep.get("error"),
            }
            if ep["status"] == "ready":
                payload["audio_url"] = (
                    f"{APP_BASE_URL}/u/{secret}/audio/{slug}.mp3"
                )
            return JSONResponse(payload)
    return _agent_error(404, "not_found", "No such episode.")


@app.delete("/u/{secret}/episodes/{slug}")
def delete_episode_api(secret: str, slug: str):
    """Agent-facing episode delete (documented at /AGENTS.md). Lets an agent
    undo a share it created (wrong link, duplicate). Path-secret auth, JSON
    only, no cookies; mirrors the status route's auth and error shape. The
    delete is idempotent from the agent's side: an already-gone slug is a 404,
    same as any unknown slug."""
    if not storage.user_exists(DATA_DIR, secret):
        return _agent_error(404, "not_found", "No feed at this URL.")
    if not SLUG_RE.match(slug):
        return _agent_error(404, "not_found", "No such episode.")
    if not storage.delete_episode(DATA_DIR, secret, slug):
        return _agent_error(404, "not_found", "No such episode.")
    return JSONResponse({"slug": slug, "status": "deleted"})


# --- the assignment desk (v3.36 The Producer) --------------------------------

def _public_request(r: dict) -> dict:
    item = {
        "id": r["id"],
        "text": r["text"],
        "ts": r["ts"],
        "status": r["status"],
        "source": r.get("source", "owner"),
    }
    if r.get("done_note"):
        item["done_note"] = r["done_note"]
    return item


def _requests_view(secret: str) -> list[dict]:
    """Open requests first (newest first), then the 5 most recent done."""
    entries = storage.list_requests(DATA_DIR, secret)
    view = ([r for r in entries if r["status"] == "open"]
            + [r for r in entries if r["status"] == "done"][:5])
    now_ts = int(_time.time())
    for r in view:
        r["when"] = relative_time(r["ts"], now=now_ts)
    return view


@app.get("/u/{secret}/requests")
def list_requests_api(secret: str):
    """Agent-facing request list (documented at /AGENTS.md). Path-secret
    auth, JSON only, no cookies. Open requests first, then recent done."""
    if not storage.user_exists(DATA_DIR, secret):
        return _agent_error(404, "not_found", "No feed at this URL.")
    return JSONResponse({
        "requests": [_public_request(r) for r in _requests_view(secret)],
    })


@app.post("/u/{secret}/requests")
async def create_request_route(request: Request, secret: str):
    """Agent-facing: record a standing request on the desk (documented at
    /AGENTS.md). The user asks in chat; the agent records it here so it
    survives the session. Path-secret auth, JSON only."""
    if not storage.user_exists(DATA_DIR, secret):
        return _agent_error(404, "not_found", "No feed at this URL.")
    try:
        payload = json.loads(await request.body())
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = None
    text = payload.get("text") if isinstance(payload, dict) else None
    if not isinstance(text, str) or not text.strip():
        return _agent_error(
            400, "invalid_request", 'Body must include a string "text".',
        )
    try:
        entry = storage.add_request(DATA_DIR, secret, text)
    except ValueError as err:
        return _agent_error(400, "invalid_request", str(err))
    _track("request_left", secret=secret, path="requests",
           props={"source": "owner"})
    return JSONResponse(_public_request(entry), status_code=201)


@app.post("/u/{secret}/requests/{rid}/complete")
async def complete_request_api(request: Request, secret: str, rid: str):
    """Agent-facing: mark a request done, optionally with a note about what
    was produced for it. Path-secret auth, JSON only."""
    if not storage.user_exists(DATA_DIR, secret):
        return _agent_error(404, "not_found", "No feed at this URL.")
    try:
        payload = json.loads(await request.body())
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = {}
    note = payload.get("note") if isinstance(payload, dict) else None
    if note is not None and not isinstance(note, str):
        return _agent_error(400, "invalid_request", '"note" must be a string.')
    if not storage.complete_request(DATA_DIR, secret, rid, note=note):
        return _agent_error(404, "not_found", "No such request.")
    return JSONResponse({"id": rid, "status": "done"})


@app.get("/u/{secret}/requests_partial", response_class=HTMLResponse)
def requests_partial(request: Request, secret: str):
    if not storage.user_exists(DATA_DIR, secret):
        raise HTTPException(404)
    return templates.TemplateResponse(request, "_requests_section.html", {
        "requests": _requests_view(secret),
        "secret": secret,
    })


@app.get("/u/{secret}/feedback", response_class=HTMLResponse)
def feedback_route(request: Request, secret: str, slug: str = "", v: str = ""):
    """The loop-back from the podcast app: show-notes links land here. Records
    a listener request on the producer's desk (deduped while open) and
    confirms quietly. No GA on this page: the URL carries the secret."""
    if not storage.user_exists(DATA_DIR, secret):
        raise HTTPException(404)
    if v not in ("more", "less"):
        raise HTTPException(404)
    ep = next(
        (e for e in storage.list_episodes(DATA_DIR, secret) if e["slug"] == slug),
        None,
    )
    if ep is None:
        raise HTTPException(404)
    title = ep.get("title") or hostname(ep.get("url") or "") or "that episode"
    text = (f'More like "{title}"' if v == "more" else f'Fewer like "{title}"')
    recorded = True
    try:
        storage.add_request(DATA_DIR, secret, text[:500], source="listener")
    except ValueError:
        recorded = False  # full desk; the tap still lands on a page
    _track("feedback_tap", secret=secret, path="feedback", props={"v": v})
    return templates.TemplateResponse(request, "feedback.html", {
        "title": title,
        "more": v == "more",
        "recorded": recorded,
        "secret": secret,
    })


@app.get("/cover.jpg")
def cover_route():
    return FileResponse(
        STATIC_DIR / "cover.jpg",
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/webmcp.js")
def webmcp_js():
    """The WebMCP tool registration script (see AGENTS.md, 'In a browser').

    Included by the landing and feed pages; a silent no-op in browsers
    without WebMCP. Committed under static/, not generated.
    """
    return FileResponse(
        STATIC_DIR / "webmcp.js",
        media_type="text/javascript",
        headers={"Cache-Control": "public, max-age=3600"},
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
    db = _analytics_db()
    last = analytics.feed_last_accessed(db)
    shares = analytics.feed_share_counts(db)
    feeds = []
    for f in storage.list_feeds(DATA_DIR):
        h = analytics.feed_hash(f["secret"])          # hash here; never render secret
        ts = last.get(h)
        feeds.append({
            "feed_hash": h,
            "created": _fmt_utc(f["created_at"]),
            "last_accessed_ts": ts,                     # for sorting (None -> 0)
            "last_accessed": _fmt_utc(ts) if ts else None,
            "shares": shares.get(h, 0),
        })
    feeds.sort(key=lambda r: r["last_accessed_ts"] or 0, reverse=True)
    return templates.TemplateResponse(
        request, "admin_stats.html",
        {"s": analytics.summary(db), "feeds": feeds},
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
        "shortcut_text_url": SHORTCUT_TEXT_ICLOUD_URL,
        "setup_done": setup_done,
        "base_url": APP_BASE_URL,
        "requests": _requests_view(secret),
    })
    set_session_cookie(response, secret)
    return response


@app.get("/u/{secret}/collab")
def collab(secret: str):
    """v3.31's separate agent-session page, merged into the feed page in
    v3.34 (spec: docs/superpowers/specs/2026-08-26-session-page-directions
    .html). Permanent redirect so agents holding the old URL land home."""
    return RedirectResponse(f"/u/{secret}", status_code=301)


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
