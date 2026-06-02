# Basic Analytics (v3.1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Self-hosted, privacy-preserving analytics for Feed Me: track site traffic, feeds created, and articles shared, attributed by a one-way hashed feed id, viewable through token-gated admin routes.

**Architecture:** A new `analytics.py` module (Python stdlib `sqlite3` only) writes events to `DATA_DIR/_analytics/analytics.db`. `app.py` calls a one-line `_track()` helper from four routes. Two token-gated routes (`/admin/stats` HTML, `/admin/export` JSON) read aggregates. `track()` swallows all exceptions so analytics can never break a page.

**Tech Stack:** Python 3.12, FastAPI, stdlib `sqlite3`/`hashlib`/`hmac`/`json`, pytest (`uv run pytest`), deploy via `~/.fly/bin/fly deploy --app feed-me-noah-willow-grove-8052`. Spec: `docs/superpowers/specs/2026-06-02-analytics.html`. **No new runtime dependency.**

---

## File Structure

```
feed-me/
  analytics.py              # NEW — sqlite event store: feed_hash, track, summary, _connect
  app.py                    # +_track/_analytics_db helpers, +4 instrumented call sites,
                            #  +STATS_TOKEN guard, +/admin/stats + /admin/export routes
  tests/test_analytics.py   # NEW — module unit tests
  tests/test_app.py         # +instrumentation tests, +admin route tests
  CHANGELOG.md              # v3.1 entry
```

`analytics.py` owns all SQLite/aggregation logic with a small interface (`feed_hash`, `track`, `summary`). `app.py` only wires events in and renders the admin views — it never touches SQL directly.

---

## Task 1: `analytics.py` — schema, `feed_hash`, `track`

**Files:**
- Create: `/Users/noah/Desktop/feed-me/analytics.py`
- Test: `/Users/noah/Desktop/feed-me/tests/test_analytics.py`

- [ ] **Step 1: Write failing tests**

Create `/Users/noah/Desktop/feed-me/tests/test_analytics.py`:

```python
import analytics


def test_feed_hash_is_stable_12_chars_and_not_the_secret():
    h1 = analytics.feed_hash("supersecret")
    h2 = analytics.feed_hash("supersecret")
    assert h1 == h2
    assert len(h1) == 12
    assert h1 != "supersecret"
    assert "supersecret" not in h1
    assert analytics.feed_hash("other") != h1


def test_track_then_summary_counts_events(tmp_path):
    db = tmp_path / "_analytics" / "analytics.db"
    analytics.track(db, "feed_created", feed_hash="aaa")
    analytics.track(db, "article_shared", feed_hash="aaa", path="share")
    analytics.track(db, "article_shared", feed_hash="bbb", path="share")
    analytics.track(db, "page_view", path="landing")

    s = analytics.summary(db)
    assert s["feeds_created"] == 1
    assert s["articles_shared"] == 2
    assert s["page_views"] == 1
    assert s["page_views_by_path"]["landing"] == 1
    assert s["active_feeds"] == 2  # distinct non-null feed_hash


def test_track_creates_parent_dir(tmp_path):
    db = tmp_path / "nested" / "_analytics" / "analytics.db"
    analytics.track(db, "page_view", path="landing")
    assert db.exists()


def test_track_never_raises_on_bad_path(tmp_path):
    # A path whose parent is a FILE (cannot mkdir) must not raise.
    bad_parent = tmp_path / "afile"
    bad_parent.write_text("x")
    analytics.track(bad_parent / "sub" / "analytics.db", "page_view")
    # no assertion needed — the test passes if track() did not raise
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd /Users/noah/Desktop/feed-me && uv run pytest tests/test_analytics.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'analytics'`.

- [ ] **Step 3: Implement `analytics.py` (feed_hash, _connect, track)**

Create `/Users/noah/Desktop/feed-me/analytics.py`:

```python
"""Self-hosted analytics for Feed Me.

A single SQLite table on the Fly volume. No third party, no runtime dependency
beyond the standard library. Per-feed identity is a one-way hash so analytics
data can never reveal a private feed URL.

The DB lives in its own subdirectory (DATA_DIR/_analytics/) so the
/data/<secret>/ feed level stays pure for any feed-enumeration code.
"""
import hashlib
import json
import sqlite3
import time
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        INTEGER NOT NULL,
    event     TEXT    NOT NULL,
    feed_hash TEXT,
    path      TEXT,
    props     TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_event ON events(event);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
"""


def feed_hash(secret: str) -> str:
    """One-way, truncated. Stable per feed, never reversible to the secret."""
    return hashlib.sha256(secret.encode()).hexdigest()[:12]


def _connect(db_path) -> sqlite3.Connection:
    """Open a short-lived connection, creating the dir + schema on first use.

    A new connection per call (not a shared module-level one): article ingest
    runs in background daemon threads, so a shared connection would be unsafe.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    return conn


def track(db_path, event, *, feed_hash=None, path=None, props=None, ts=None) -> None:
    """Insert one event. MUST never raise — analytics can't break a request."""
    try:
        conn = _connect(db_path)
        with conn:
            conn.execute(
                "INSERT INTO events (ts, event, feed_hash, path, props) "
                "VALUES (?, ?, ?, ?, ?)",
                (ts if ts is not None else int(time.time()),
                 event, feed_hash, path,
                 json.dumps(props) if props else None),
            )
        conn.close()
    except Exception:
        pass  # swallow — never propagate analytics failure to the caller
```

(`summary()` is added in Task 2; `test_track_then_summary_counts_events` stays red until then — that's expected and fine for TDD ordering. The other three tests pass now.)

- [ ] **Step 4: Run the non-summary tests to verify they pass**

Run: `cd /Users/noah/Desktop/feed-me && uv run pytest tests/test_analytics.py -v -k "not summary"`
Expected: PASS (3 tests). The `summary` test errors with `AttributeError: module 'analytics' has no attribute 'summary'` — expected until Task 2.

- [ ] **Step 5: Commit**

```bash
cd /Users/noah/Desktop/feed-me && git add analytics.py tests/test_analytics.py && git commit -m "feat(analytics): sqlite event store — feed_hash + track"
```

---

## Task 2: `analytics.summary` — aggregates

**Files:**
- Modify: `/Users/noah/Desktop/feed-me/analytics.py`
- Test: `/Users/noah/Desktop/feed-me/tests/test_analytics.py` (the summary test from Task 1 + one more)

- [ ] **Step 1: Add a by-day/top-feeds test**

Append to `/Users/noah/Desktop/feed-me/tests/test_analytics.py`:

```python
def test_summary_by_day_and_top_feeds(tmp_path):
    db = tmp_path / "_analytics" / "analytics.db"
    # Two events on a fixed day, one on the next.
    day1 = 1_750_000_000          # some fixed unix ts
    day2 = day1 + 86_400
    analytics.track(db, "article_shared", feed_hash="aaa", ts=day1)
    analytics.track(db, "article_shared", feed_hash="aaa", ts=day1)
    analytics.track(db, "page_view", path="landing", ts=day2)

    s = analytics.summary(db)
    # by_day is a list of {day, page_views, shares, feeds}, ascending by day
    days = {row["day"]: row for row in s["by_day"]}
    assert len(days) == 2
    # top_feeds ranks feeds by article_shared count
    assert s["top_feeds"][0]["feed_hash"] == "aaa"
    assert s["top_feeds"][0]["shares"] == 2


def test_summary_empty_db(tmp_path):
    db = tmp_path / "_analytics" / "analytics.db"
    s = analytics.summary(db)
    assert s["feeds_created"] == 0
    assert s["articles_shared"] == 0
    assert s["page_views"] == 0
    assert s["active_feeds"] == 0
    assert s["by_day"] == []
    assert s["top_feeds"] == []
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/noah/Desktop/feed-me && uv run pytest tests/test_analytics.py -v -k summary`
Expected: FAIL — `summary` doesn't exist yet.

- [ ] **Step 3: Implement `summary`**

Append to `/Users/noah/Desktop/feed-me/analytics.py`:

```python
def summary(db_path) -> dict:
    """Aggregate counts for the stats page / export. Read-only; never raises
    on a missing DB (creates an empty one)."""
    conn = _connect(db_path)
    try:
        cur = conn.cursor()

        def count(where: str, args=()) -> int:
            return cur.execute(
                f"SELECT COUNT(*) FROM events WHERE {where}", args
            ).fetchone()[0]

        feeds_created = count("event = 'feed_created'")
        articles_shared = count("event = 'article_shared'")
        page_views = count("event = 'page_view'")

        page_views_by_path = {"landing": 0, "settings": 0, "share": 0}
        for path, n in cur.execute(
            "SELECT path, COUNT(*) FROM events "
            "WHERE event = 'page_view' GROUP BY path"
        ).fetchall():
            if path in page_views_by_path:
                page_views_by_path[path] = n

        active_feeds = cur.execute(
            "SELECT COUNT(DISTINCT feed_hash) FROM events "
            "WHERE feed_hash IS NOT NULL"
        ).fetchone()[0]

        by_day = [
            {"day": day, "page_views": pv, "shares": sh, "feeds": fc}
            for (day, pv, sh, fc) in cur.execute(
                "SELECT strftime('%Y-%m-%d', ts, 'unixepoch') AS day, "
                "  SUM(event = 'page_view'), "
                "  SUM(event = 'article_shared'), "
                "  SUM(event = 'feed_created') "
                "FROM events GROUP BY day ORDER BY day"
            ).fetchall()
        ]

        top_feeds = [
            {"feed_hash": fh, "shares": sh}
            for (fh, sh) in cur.execute(
                "SELECT feed_hash, COUNT(*) AS shares FROM events "
                "WHERE event = 'article_shared' AND feed_hash IS NOT NULL "
                "GROUP BY feed_hash ORDER BY shares DESC LIMIT 20"
            ).fetchall()
        ]

        return {
            "feeds_created": feeds_created,
            "articles_shared": articles_shared,
            "page_views": page_views,
            "page_views_by_path": page_views_by_path,
            "active_feeds": active_feeds,
            "by_day": by_day,
            "top_feeds": top_feeds,
        }
    finally:
        conn.close()
```

- [ ] **Step 4: Run the whole analytics suite**

Run: `cd /Users/noah/Desktop/feed-me && uv run pytest tests/test_analytics.py -v`
Expected: PASS (all 6 tests, including the Task 1 summary test).

- [ ] **Step 5: Commit**

```bash
cd /Users/noah/Desktop/feed-me && git add analytics.py tests/test_analytics.py && git commit -m "feat(analytics): summary aggregates (counts, by-day, top feeds)"
```

---

## Task 3: Instrument the four routes in `app.py`

**Files:**
- Modify: `/Users/noah/Desktop/feed-me/app.py`
- Test: `/Users/noah/Desktop/feed-me/tests/test_app.py`

- [ ] **Step 1: Write failing instrumentation tests**

Append to `/Users/noah/Desktop/feed-me/tests/test_app.py`:

```python
def test_landing_records_page_view(client, tmp_path):
    client.get("/")
    import analytics
    s = analytics.summary(tmp_path / "_analytics" / "analytics.db")
    assert s["page_views_by_path"]["landing"] >= 1


def test_create_records_feed_created(client, tmp_path):
    client.post("/create", follow_redirects=False)
    import analytics
    s = analytics.summary(tmp_path / "_analytics" / "analytics.db")
    assert s["feeds_created"] == 1


def test_share_records_article_shared_with_feed_hash(client, monkeypatch, tmp_path):
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]
    client.get(f"/u/{secret}")  # link browser (cookie)

    import app as app_module
    monkeypatch.setattr(app_module, "spawn_ingest", lambda *a, **k: None)
    monkeypatch.setattr(app_module.ingest, "fetch_title", lambda url: "T")

    client.get("/share?url=https://example.com/a")

    import analytics
    db = tmp_path / "_analytics" / "analytics.db"
    s = analytics.summary(db)
    assert s["articles_shared"] == 1
    # the event carries the hashed secret, never the raw secret
    assert s["top_feeds"][0]["feed_hash"] == analytics.feed_hash(secret)


def test_analytics_failure_never_500s_a_page(client, monkeypatch):
    import app as app_module
    def boom(*a, **k):
        raise RuntimeError("analytics down")
    monkeypatch.setattr(app_module.analytics, "track", boom)
    # _track must isolate this; landing still renders.
    assert client.get("/").status_code == 200
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/noah/Desktop/feed-me && uv run pytest tests/test_app.py -v -k "page_view or feed_created or article_shared or never_500"`
Expected: FAIL — `app` has no `analytics` attribute / events not recorded.

- [ ] **Step 3: Import analytics + add the helpers in `app.py`**

In `/Users/noah/Desktop/feed-me/app.py`, add `import analytics` next to the other local imports (after `import storage` on line 22):

```python
import analytics
import ingest
import rss
import storage
```

Then add these helpers immediately after the `set_session_cookie(...)` function definition (i.e. just before the `SLUG_RE = re.compile(...)` line near line 91). The `_track` helper wraps `analytics.track` so a failure inside `track` AND inside `feed_hash` can never reach a request handler:

```python
def _analytics_db():
    # Built at call time (not import) so monkeypatched DATA_DIR resolves correctly.
    return DATA_DIR / "_analytics" / "analytics.db"


def _track(event, *, secret=None, path=None, props=None):
    try:
        fh = analytics.feed_hash(secret) if secret else None
        analytics.track(_analytics_db(), event, feed_hash=fh, path=path, props=props)
    except Exception:
        pass  # analytics must never affect the request
```

- [ ] **Step 4: Add the four call sites**

(a) In `landing()` (line ~206) — record before returning:

```python
@app.get("/", response_class=HTMLResponse)
def landing(request: Request):
    _track("page_view", path="landing")
    return templates.TemplateResponse(request, "landing.html", {"base_url": APP_BASE_URL})
```

(b) In `create()` (line ~211) — record after the user is made:

```python
@app.post("/create")
def create():
    secret = storage.create_user(DATA_DIR)
    storage.seed_welcome_episode(
        DATA_DIR, secret, welcome_audio=WELCOME_AUDIO_BYTES,
    )
    _track("feed_created", secret=secret)
    return RedirectResponse(f"/u/{secret}", status_code=303)
```

(c) In `settings()` (line ~220) — record a settings page_view right after the 404 guard:

```python
@app.get("/u/{secret}", response_class=HTMLResponse)
def settings(request: Request, secret: str):
    if not storage.user_exists(DATA_DIR, secret):
        raise HTTPException(404)
    _track("page_view", secret=secret, path="settings")
    s = storage.get_settings(DATA_DIR, secret)
    ...
```

(d) In `share_route()` — in the **success branch only** (right after `spawn_ingest(url, secret, DATA_DIR, slug)` on line ~142), record both a share page_view and the share itself:

```python
    spawn_ingest(url, secret, DATA_DIR, slug)
    _track("page_view", secret=secret, path="share")
    _track("article_shared", secret=secret, path="share")
    return templates.TemplateResponse(
        request, "share.html",
        {"state": "added", "title": title or hostname(url),
         "slug": slug, "home_url": home_url},
    )
```

(Do NOT instrument the connect/error branches of `share_route` — only a real, accepted share counts.)

- [ ] **Step 5: Run the instrumentation tests, then the full suite**

Run: `cd /Users/noah/Desktop/feed-me && uv run pytest tests/test_app.py -v -k "page_view or feed_created or article_shared or never_500"` → expect PASS.
Run: `cd /Users/noah/Desktop/feed-me && uv run pytest -q` → expect PASS (no regressions).

- [ ] **Step 6: Commit**

```bash
cd /Users/noah/Desktop/feed-me && git add app.py tests/test_app.py && git commit -m "feat(app): record page_view / feed_created / article_shared events"
```

---

## Task 4: Token-gated `/admin/stats` and `/admin/export`

**Files:**
- Modify: `/Users/noah/Desktop/feed-me/app.py`
- Test: `/Users/noah/Desktop/feed-me/tests/test_app.py`

- [ ] **Step 1: Write failing admin tests**

Append to `/Users/noah/Desktop/feed-me/tests/test_app.py`:

```python
def test_admin_routes_404_without_token(client):
    # STATS_TOKEN unset by default in tests → both routes 404.
    assert client.get("/admin/stats").status_code == 404
    assert client.get("/admin/export").status_code == 404


def test_admin_routes_404_with_wrong_token(client, monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, "STATS_TOKEN", "right")
    assert client.get("/admin/stats?token=wrong").status_code == 404
    assert client.get("/admin/export?token=wrong").status_code == 404


def test_admin_stats_and_export_with_correct_token(client, monkeypatch, tmp_path):
    import app as app_module
    monkeypatch.setattr(app_module, "STATS_TOKEN", "right")
    # generate some data
    client.post("/create", follow_redirects=False)
    client.get("/")

    stats = client.get("/admin/stats?token=right")
    assert stats.status_code == 200
    assert "Feeds created" in stats.text  # a label from the stats page

    export = client.get("/admin/export?token=right")
    assert export.status_code == 200
    body = export.json()
    assert "summary" in body and "events" in body
    assert body["summary"]["feeds_created"] == 1
    assert len(body["events"]) >= 2  # feed_created + at least one page_view
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/noah/Desktop/feed-me && uv run pytest tests/test_app.py -v -k admin`
Expected: FAIL — routes don't exist (404 tests may pass accidentally since unknown path is 404; the correct-token test fails).

- [ ] **Step 3: Add `hmac` import + `STATS_TOKEN` + guard**

In `/Users/noah/Desktop/feed-me/app.py`, add `import hmac` at the top (after `import os`):

```python
import hmac
import os
import re
```

Add the token constant next to the other env reads (after `SHORTCUT_ICLOUD_URL`, line ~72):

```python
STATS_TOKEN = os.environ.get("STATS_TOKEN")
```

Add the guard helper near `_track` (after the `_track` definition from Task 3):

```python
def _check_stats_token(token: str) -> None:
    # 404 (not 401/403) on any failure — reveal nothing about the route.
    if not STATS_TOKEN or not token or not hmac.compare_digest(token, STATS_TOKEN):
        raise HTTPException(404)
```

- [ ] **Step 4: Add the export route**

Add to `/Users/noah/Desktop/feed-me/app.py` near the other routes (e.g. just after `og_route`):

```python
@app.get("/admin/export")
def admin_export(token: str = ""):
    _check_stats_token(token)
    db = _analytics_db()
    import sqlite3
    conn = sqlite3.connect(db) if db.exists() else None
    events = []
    if conn is not None:
        try:
            rows = conn.execute(
                "SELECT ts, event, feed_hash, path, props FROM events ORDER BY ts"
            ).fetchall()
            events = [
                {"ts": ts, "event": ev, "feed_hash": fh, "path": p, "props": pr}
                for (ts, ev, fh, p, pr) in rows
            ]
        finally:
            conn.close()
    return JSONResponse({"summary": analytics.summary(db), "events": events})
```

(`JSONResponse` is already imported in `app.py`. `_analytics_db()` was added in Task 3.)

- [ ] **Step 5: Add the stats HTML route + template**

Create `/Users/noah/Desktop/feed-me/templates/admin_stats.html`:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Feed Me · stats</title>
  <style>
    body { font-family: -apple-system, system-ui, sans-serif; max-width: 720px;
           margin: 40px auto; padding: 0 20px; color: #2a1f18; background: #FFF8F2; }
    h1 { font-size: 22px; } h2 { font-size: 14px; text-transform: uppercase;
         letter-spacing: .08em; color: #8a6f5e; margin-top: 32px; }
    .nums { display: flex; gap: 24px; flex-wrap: wrap; margin: 16px 0; }
    .num { background: #fff; border-radius: 12px; padding: 14px 18px;
           box-shadow: 0 2px 8px rgba(176,74,0,.06); }
    .num b { display: block; font-size: 28px; color: #b04a00; }
    .num span { font-size: 12px; color: #8a6f5e; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 8px; }
    th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #EFE2D6; }
    th { color: #8a6f5e; font-size: 11px; text-transform: uppercase; }
    code { font-family: "SF Mono", Menlo, monospace; font-size: 12px; }
  </style>
</head>
<body>
  <h1>Feed Me · stats</h1>
  <div class="nums">
    <div class="num"><b>{{ s.feeds_created }}</b><span>Feeds created</span></div>
    <div class="num"><b>{{ s.articles_shared }}</b><span>Articles shared</span></div>
    <div class="num"><b>{{ s.page_views }}</b><span>Page views</span></div>
    <div class="num"><b>{{ s.active_feeds }}</b><span>Active feeds</span></div>
  </div>

  <h2>Page views by section</h2>
  <table>
    <tr><th>Landing</th><th>Settings</th><th>Share</th></tr>
    <tr><td>{{ s.page_views_by_path.landing }}</td>
        <td>{{ s.page_views_by_path.settings }}</td>
        <td>{{ s.page_views_by_path.share }}</td></tr>
  </table>

  <h2>By day</h2>
  <table>
    <tr><th>Day</th><th>Page views</th><th>Shares</th><th>Feeds</th></tr>
    {% for row in s.by_day %}
    <tr><td>{{ row.day }}</td><td>{{ row.page_views }}</td>
        <td>{{ row.shares }}</td><td>{{ row.feeds }}</td></tr>
    {% endfor %}
  </table>

  <h2>Top feeds (by shares)</h2>
  <table>
    <tr><th>Feed (hashed)</th><th>Shares</th></tr>
    {% for f in s.top_feeds %}
    <tr><td><code>{{ f.feed_hash }}</code></td><td>{{ f.shares }}</td></tr>
    {% endfor %}
  </table>
</body>
</html>
```

Add the route to `/Users/noah/Desktop/feed-me/app.py` (next to `admin_export`):

```python
@app.get("/admin/stats", response_class=HTMLResponse)
def admin_stats(request: Request, token: str = ""):
    _check_stats_token(token)
    return templates.TemplateResponse(
        request, "admin_stats.html", {"s": analytics.summary(_analytics_db())},
    )
```

- [ ] **Step 6: Run admin tests, then full suite**

Run: `cd /Users/noah/Desktop/feed-me && uv run pytest tests/test_app.py -v -k admin` → expect PASS.
Run: `cd /Users/noah/Desktop/feed-me && uv run pytest -q` → expect PASS.

- [ ] **Step 7: Commit**

```bash
cd /Users/noah/Desktop/feed-me && git add app.py templates/admin_stats.html tests/test_app.py && git commit -m "feat(admin): token-gated /admin/stats + /admin/export"
```

---

## Task 5: Set the secret, deploy, verify, release v3.1

**Files:** `/Users/noah/Desktop/feed-me/CHANGELOG.md`

- [ ] **Step 1: Pick a strong token and set it as a Fly secret**

Generate one and set it (do NOT commit it anywhere):

```bash
TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")
echo "STATS_TOKEN=$TOKEN  <-- save this in your password manager"
~/.fly/bin/fly secrets set STATS_TOKEN="$TOKEN" --app feed-me-noah-willow-grove-8052
```

(Setting a secret triggers a Fly restart; the next deploy carries the new code too.)

- [ ] **Step 2: Deploy**

```bash
cd /Users/noah/Desktop/feed-me && ~/.fly/bin/fly deploy --app feed-me-noah-willow-grove-8052
```

- [ ] **Step 3: Verify on prod**

```bash
# No token → 404
curl -sS -m 20 -o /dev/null -w "no-token: %{http_code}\n" https://feed-me.xyz/admin/stats
# Correct token → 200 (paste your real token)
curl -sS -m 20 -o /dev/null -w "stats: %{http_code}\n" "https://feed-me.xyz/admin/stats?token=$TOKEN"
curl -sS -m 20 -o /dev/null -w "export: %{http_code}\n" "https://feed-me.xyz/admin/export?token=$TOKEN"
# healthz
curl -sS -m 20 -o /dev/null -w "healthz: %{http_code}\n" https://feed-me.xyz/healthz
```
Expected: `no-token: 404`, `stats: 200`, `export: 200`, `healthz: 200`. Then open `https://feed-me.xyz/admin/stats?token=…` in a browser and confirm the numbers render and increment after a test share.

- [ ] **Step 4: Update CHANGELOG and tag v3.1**

Insert at the top of `/Users/noah/Desktop/feed-me/CHANGELOG.md`:

```markdown
## v3.1 — 2026-06-02

Basic analytics:

- Self-hosted SQLite event store (`analytics.py`, stdlib only — no new dependency, no third party) on the Fly volume at `_analytics/analytics.db`.
- Tracks `page_view`, `feed_created`, and `article_shared`, each attributed by a one-way `sha256(secret)[:12]` hash — the raw feed secret is never stored, so analytics can't reveal a private feed URL.
- Token-gated `/admin/stats` (HTML summary) and `/admin/export` (JSON for later analysis); both 404 without the correct `STATS_TOKEN`.
- Spec: `docs/superpowers/specs/2026-06-02-analytics.html`
```

Then:

```bash
cd /Users/noah/Desktop/feed-me && git add CHANGELOG.md && git commit -m "release: v3.1 basic analytics" && git tag v3.1
```

---

## Self-Review

### Spec coverage

| Spec section | Task |
|---|---|
| §3 SQLite at `DATA_DIR/_analytics/analytics.db`, schema, indexes | Task 1 (`_connect`, `_SCHEMA`) |
| §3 event taxonomy (page_view/feed_created/article_shared) | Task 3 call sites |
| §3 feed-count must filter to dirs | N/A here — `summary` counts feeds from events, not filesystem; no filesystem feed-count is added (YAGNI), so the footgun is avoided by not introducing it |
| §4 `feed_hash` one-way truncated | Task 1 |
| §4 `track` never raises; creates dir + schema | Task 1 (+ tests for both) |
| §4 short-lived per-call connection, WAL, no shared conn | Task 1 (`_connect`) |
| §4 `summary` aggregates (counts, by_path, active, by_day, top_feeds) | Task 2 |
| §5 `_track`/`_analytics_db` helpers built at call time | Task 3 |
| §5 four instrumented call sites | Task 3 |
| §6 `STATS_TOKEN` short-circuit guard, 404 on failure | Task 4 |
| §6 `/admin/stats` HTML + `/admin/export` JSON | Task 4 |
| §7 analytics module tests | Tasks 1–2 |
| §7 app instrumentation tests incl. "failure never 500s" | Task 3 |
| §7 admin route tests (no/wrong/correct token) | Task 4 |
| §9 acceptance: secret never stored; token gating; resilience; no new dep | Tasks 1/3/4 tests + Task 5 prod verify |

Note on the §3 "filesystem feed count as a sanity total": the plan deliberately does **not** add a filesystem feed count (the events `feeds_created` count covers the requirement). This sidesteps the dir-filter footgun entirely rather than implementing it. If a live filesystem count is wanted later, it must use `[p for p in DATA_DIR.iterdir() if p.is_dir()]`.

### Placeholder scan

No "TBD/TODO/handle edge cases/similar to Task N". Every code step is complete. The only intentionally-red interim state (the `summary` test after Task 1) is called out explicitly with the expected error.

### Type / name consistency

- `feed_hash`, `track(db_path, event, *, feed_hash, path, props, ts)`, `summary(db_path)` — signatures consistent across Tasks 1–4 and all tests.
- `summary()` keys (`feeds_created`, `articles_shared`, `page_views`, `page_views_by_path`, `active_feeds`, `by_day`, `top_feeds`) — identical in Task 2 impl, the admin template (Task 4), and tests.
- `_analytics_db()` / `_track()` / `_check_stats_token()` — defined in Task 3/4, used consistently.
- `STATS_TOKEN` — defined Task 4 Step 3, read by `_check_stats_token`, monkeypatched in tests by the same name.
- DB path `DATA_DIR/_analytics/analytics.db` — identical in `_analytics_db()` and every test that reads `tmp_path / "_analytics" / "analytics.db"`.
