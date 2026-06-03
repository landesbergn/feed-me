# Stats Feeds & Shares Tables Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a full Feeds table (every feed on disk, with created + last-accessed + shares) to `/admin/stats`, remove the now-redundant rendered "Top feeds" table, and reorder the "Recently shared" columns to Feed · When · Article.

**Architecture:** `storage.list_feeds()` enumerates feed dirs (raw secrets); `analytics.feed_last_accessed()` and `analytics.feed_share_counts()` return per-hash maps; the `admin_stats` route hashes each secret, joins the maps, drops the secret, and passes a `feeds` list to the template alongside the existing `summary()`. The template gains an "All feeds" table, drops the "Top feeds" section, and reorders the "Recently shared" header. `summary()` is left unchanged (its `top_feeds` still feeds the JSON export).

**Tech Stack:** FastAPI, Jinja2, stdlib `sqlite3`, pytest with the `client`/`tmp_path` fixtures (no network).

**Spec:** `docs/superpowers/specs/2026-06-02-stats-feeds-shares-tables.html`

---

### Task 1: `storage.list_feeds`

**Files:**
- Modify: `storage.py` (add `list_feeds`)
- Test: `tests/test_storage.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_storage.py`:

```python
def test_list_feeds_returns_one_entry_per_feed(tmp_path):
    s1 = storage.create_user(tmp_path)
    s2 = storage.create_user(tmp_path)
    feeds = storage.list_feeds(tmp_path)
    secrets = {f["secret"] for f in feeds}
    assert secrets == {s1, s2}
    assert all(isinstance(f["created_at"], int) for f in feeds)


def test_list_feeds_skips_analytics_dir(tmp_path):
    storage.create_user(tmp_path)
    (tmp_path / "_analytics").mkdir()
    (tmp_path / "_analytics" / "analytics.db").write_text("x")
    names = {f["secret"] for f in storage.list_feeds(tmp_path)}
    assert "_analytics" not in names


def test_list_feeds_skips_dirs_without_settings(tmp_path):
    storage.create_user(tmp_path)
    (tmp_path / "not-a-feed").mkdir()
    names = {f["secret"] for f in storage.list_feeds(tmp_path)}
    assert "not-a-feed" not in names


def test_list_feeds_falls_back_to_mtime_when_created_at_missing(tmp_path):
    import json
    feed_dir = tmp_path / "legacy-feed"
    feed_dir.mkdir()
    settings = feed_dir / "settings.json"
    settings.write_text(json.dumps({"voice": "shimmer"}))  # no created_at
    feeds = storage.list_feeds(tmp_path)
    entry = next(f for f in feeds if f["secret"] == "legacy-feed")
    assert entry["created_at"] == int(settings.stat().st_mtime)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_storage.py -k list_feeds -v`
Expected: FAIL with `AttributeError: module 'storage' has no attribute 'list_feeds'`

- [ ] **Step 3: Implement `list_feeds`**

Add to `storage.py` (after `list_episodes`, near the other read helpers):

```python
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
```

(`json` and `Path` are already imported at the top of `storage.py`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_storage.py -k list_feeds -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add storage.py tests/test_storage.py
git commit -m "feat: storage.list_feeds enumerates feed dirs with created_at"
```

---

### Task 2: `analytics.feed_last_accessed`

**Files:**
- Modify: `analytics.py` (add `feed_last_accessed`)
- Test: `tests/test_analytics.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_analytics.py`:

```python
def test_feed_last_accessed_returns_max_ts_per_hash(tmp_path):
    db = tmp_path / "_analytics" / "analytics.db"
    analytics.track(db, "feed_created", feed_hash_val="aaa", ts=100)
    analytics.track(db, "page_view", feed_hash_val="aaa", path="settings", ts=300)
    analytics.track(db, "article_shared", feed_hash_val="bbb", path="share", ts=200)
    analytics.track(db, "page_view", path="landing", ts=999)  # no feed_hash
    result = analytics.feed_last_accessed(db)
    assert result == {"aaa": 300, "bbb": 200}


def test_feed_last_accessed_empty_db_returns_empty(tmp_path):
    db = tmp_path / "_analytics" / "analytics.db"
    assert analytics.feed_last_accessed(db) == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_analytics.py -k feed_last_accessed -v`
Expected: FAIL with `AttributeError: module 'analytics' has no attribute 'feed_last_accessed'`

- [ ] **Step 3: Implement `feed_last_accessed`**

Add to `analytics.py` (after `summary`, before `all_events`):

```python
def feed_last_accessed(db_path) -> dict:
    """{feed_hash: max(ts)} over events with a non-null feed_hash.

    Read-only; never raises on a missing DB (creates an empty one).
    """
    conn = _connect(db_path)
    try:
        return {
            fh: ts
            for (fh, ts) in conn.execute(
                "SELECT feed_hash, MAX(ts) FROM events "
                "WHERE feed_hash IS NOT NULL GROUP BY feed_hash"
            ).fetchall()
        }
    finally:
        conn.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_analytics.py -k feed_last_accessed -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add analytics.py tests/test_analytics.py
git commit -m "feat: analytics.feed_last_accessed maps feed hash to newest event ts"
```

---

### Task 3: `analytics.feed_share_counts`

**Files:**
- Modify: `analytics.py` (add `feed_share_counts`)
- Test: `tests/test_analytics.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_analytics.py`:

```python
def test_feed_share_counts_counts_only_shares_per_hash(tmp_path):
    db = tmp_path / "_analytics" / "analytics.db"
    analytics.track(db, "article_shared", feed_hash_val="aaa", path="share")
    analytics.track(db, "article_shared", feed_hash_val="aaa", path="share")
    analytics.track(db, "article_shared", feed_hash_val="bbb", path="share")
    analytics.track(db, "page_view", feed_hash_val="aaa", path="settings")  # not a share
    analytics.track(db, "feed_created", feed_hash_val="ccc")               # not a share
    result = analytics.feed_share_counts(db)
    assert result == {"aaa": 2, "bbb": 1}


def test_feed_share_counts_empty_db_returns_empty(tmp_path):
    db = tmp_path / "_analytics" / "analytics.db"
    assert analytics.feed_share_counts(db) == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_analytics.py -k feed_share_counts -v`
Expected: FAIL with `AttributeError: module 'analytics' has no attribute 'feed_share_counts'`

- [ ] **Step 3: Implement `feed_share_counts`**

Add to `analytics.py` (directly after `feed_last_accessed`):

```python
def feed_share_counts(db_path) -> dict:
    """{feed_hash: count of article_shared events} per feed. Never raises."""
    conn = _connect(db_path)
    try:
        return {
            fh: n
            for (fh, n) in conn.execute(
                "SELECT feed_hash, COUNT(*) FROM events "
                "WHERE event = 'article_shared' AND feed_hash IS NOT NULL "
                "GROUP BY feed_hash"
            ).fetchall()
        }
    finally:
        conn.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_analytics.py -k feed_share_counts -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add analytics.py tests/test_analytics.py
git commit -m "feat: analytics.feed_share_counts maps feed hash to share count"
```

---

### Task 4: Assemble `feeds` in the `admin_stats` route + render the Feeds table

**Files:**
- Modify: `app.py` (add `_fmt_utc` helper; rewrite `admin_stats`)
- Modify: `templates/admin_stats.html` (add "All feeds" table)
- Test: `tests/test_app.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_app.py` (near the other admin tests, ~line 745):

```python
def test_admin_stats_shows_feed_hash_never_the_raw_secret(client, monkeypatch, tmp_path):
    import app as app_module
    import analytics
    import storage
    monkeypatch.setattr(app_module, "STATS_TOKEN", "right")
    secret = storage.create_user(tmp_path)  # DATA_DIR is monkeypatched to tmp_path

    stats = client.get("/admin/stats?token=right")
    assert stats.status_code == 200
    # Privacy boundary: the hash is rendered, the raw secret never is.
    assert analytics.feed_hash(secret) in stats.text
    assert secret not in stats.text


def test_admin_stats_shows_never_for_feed_with_no_events(client, monkeypatch, tmp_path):
    import app as app_module
    import storage
    monkeypatch.setattr(app_module, "STATS_TOKEN", "right")
    storage.create_user(tmp_path)  # created on disk, but no analytics events tracked

    stats = client.get("/admin/stats?token=right")
    assert stats.status_code == 200
    assert "All feeds" in stats.text
    assert "never" in stats.text  # last-accessed placeholder, not an em-dash
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_app.py -k "feed_hash_never_the_raw_secret or never_for_feed" -v`
Expected: FAIL — the hash/"All feeds"/"never" strings are not yet in the rendered page.

- [ ] **Step 3: Add the `_fmt_utc` helper to `app.py`**

Add near `relative_time` (top of `app.py`; `datetime`/`timezone` are already imported):

```python
def _fmt_utc(ts: int) -> str:
    """Format a unix timestamp as 'YYYY-MM-DD HH:MM' UTC (matches recent_shares)."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
```

- [ ] **Step 4: Rewrite the `admin_stats` route in `app.py`**

Replace the existing `admin_stats` function (currently `app.py:239-244`) with:

```python
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
```

- [ ] **Step 5: Add the "All feeds" table to `templates/admin_stats.html`**

Insert this block immediately after the closing `</div>` of `<div class="nums">` (currently `admin_stats.html:30`), before `<h2>Page views by section</h2>`:

```html
  <h2>All feeds</h2>
  <table>
    <tr><th>Feed</th><th>Created (UTC)</th><th>Last accessed (UTC)</th><th>Shares</th></tr>
    {% for f in feeds %}
    <tr>
      <td><code>{{ f.feed_hash }}</code></td>
      <td>{{ f.created }}</td>
      <td>{{ f.last_accessed or "never" }}</td>
      <td>{{ f.shares }}</td>
    </tr>
    {% endfor %}
  </table>
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_app.py -k "feed_hash_never_the_raw_secret or never_for_feed" -v`
Expected: PASS (2 tests)

- [ ] **Step 7: Commit**

```bash
git add app.py templates/admin_stats.html tests/test_app.py
git commit -m "feat: render All feeds table on /admin/stats (hash, created, last accessed, shares)"
```

---

### Task 5: Reorder "Recently shared" columns + remove the "Top feeds" section

**Files:**
- Modify: `templates/admin_stats.html` (remove Top feeds; reorder Recently shared)
- Test: `tests/test_app.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_app.py`:

```python
def test_recently_shared_columns_are_feed_when_article(client, monkeypatch, tmp_path):
    import app as app_module
    monkeypatch.setattr(app_module, "STATS_TOKEN", "right")
    stats = client.get("/admin/stats?token=right")
    assert stats.status_code == 200
    # Column order is Feed, then When, then Article (header on one line).
    assert "<th>Feed</th><th>When (UTC)</th><th>Article</th>" in stats.text
    # The old "Top feeds (by shares)" section is gone.
    assert "Top feeds" not in stats.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_app.py -k recently_shared_columns -v`
Expected: FAIL — current header order is `When (UTC)`, `Feed`, `Article`, and the "Top feeds" section still exists.

- [ ] **Step 3: Remove the "Top feeds (by shares)" section**

Delete this block from `templates/admin_stats.html` (currently lines 49-55):

```html
  <h2>Top feeds (by shares)</h2>
  <table>
    <tr><th>Feed (hashed)</th><th>Shares</th></tr>
    {% for f in s.top_feeds %}
    <tr><td><code>{{ f.feed_hash }}</code></td><td>{{ f.shares }}</td></tr>
    {% endfor %}
  </table>
```

- [ ] **Step 4: Reorder the "Recently shared" table columns**

Replace the "Recently shared" block (currently `admin_stats.html:57-67`) with this (Feed first, then When, then Article; header kept on one line so the column-order test can match it):

```html
  <h2>Recently shared</h2>
  <table>
    <tr><th>Feed</th><th>When (UTC)</th><th>Article</th></tr>
    {% for r in s.recent_shares %}
    <tr>
      <td><code>{{ r.feed_hash }}</code></td>
      <td>{{ r.when }}</td>
      <td>{% if r.url %}<a href="{{ r.url }}" target="_blank" rel="noopener">{{ r.title or r.url }}</a>{% else %}{{ r.title or "(unknown)" }}{% endif %}</td>
    </tr>
    {% endfor %}
  </table>
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_app.py -k recently_shared_columns -v`
Expected: PASS

- [ ] **Step 6: Run the full suite + check for em-dashes**

Run: `uv run pytest`
Expected: all tests pass.

Run: `grep -n "—" templates/admin_stats.html`
Expected: no output (no em-dashes; project copy rule).

- [ ] **Step 7: Commit**

```bash
git add templates/admin_stats.html tests/test_app.py
git commit -m "feat: reorder Recently shared columns to Feed/When/Article; drop rendered Top feeds table"
```

---

## Notes for the implementer

- The `client` fixture monkeypatches `app.DATA_DIR` to the test's `tmp_path`, so calling `storage.create_user(tmp_path)` in a route test creates a feed the route will see.
- `analytics.track` uses the keyword `feed_hash_val=` (not `feed_hash=`); the tests above already use the correct name.
- Do NOT change `analytics.summary()` — its `top_feeds` key still feeds `/admin/export`; only the *rendered* Top feeds table is removed.
- Keep the "Recently shared" header `<tr>` on a single line; the column-order test matches it as an exact substring.
- After Task 5, optionally start the app locally to eyeball the page:
  `FEED_ME_DATA_DIR=/tmp/feedme OPENAI_API_KEY=sk-test-dummy APP_BASE_URL=http://localhost:8000 STATS_TOKEN=dev uv run uvicorn app:app --reload` then visit `/admin/stats?token=dev`.
