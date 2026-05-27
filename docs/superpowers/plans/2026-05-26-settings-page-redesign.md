# Settings Page Redesign (v1.3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite `templates/settings.html` into a three-phase layout (Set up · Share · Recent episodes table) with a collapsible Settings drawer, backed by a new "pending" episode state so just-shared articles appear immediately.

**Architecture:** Six tasks: four backend (storage pending state + status field + slug-promotable writers + ingest pending-then-promote), one helper (relative time), one frontend (template rewrite). Then deploy + tag v1.3. All TDD.

**Tech Stack:** Same as v1.0 — FastAPI + Jinja2 + plain CSS. No new dependencies. Spec: `docs/superpowers/specs/2026-05-26-settings-page-redesign.html`.

---

## File Structure

```
feed-me/
  storage.py            # +write_pending_episode, +slug param on writers, +status field
  ingest.py             # process() writes pending then promotes
  app.py                # +relative_time helper, settings route enriches episodes with `when`
  templates/
    settings.html       # FULL REWRITE
  tests/
    test_storage.py     # new pending tests, status field tests, slug-promotion tests
    test_ingest.py      # new pending-then-promote test
    test_app.py         # relative_time tests + settings page assertion updates
```

No new files. All changes are localized to existing modules.

---

## Task 1: `storage.write_pending_episode` + `status` field on `list_episodes`

**Files:**
- Modify: `/Users/noah/Desktop/feed-me/storage.py`
- Modify: `/Users/noah/Desktop/feed-me/tests/test_storage.py`

- [ ] **Step 1: Append the failing tests to `tests/test_storage.py`**

```python
def test_write_pending_episode_writes_json_only(tmp_path):
    secret = storage.create_user(tmp_path)

    slug = storage.write_pending_episode(
        tmp_path, secret, source_url="https://example.com/x",
    )

    assert not (tmp_path / secret / f"{slug}.mp3").exists()
    meta = json.loads((tmp_path / secret / f"{slug}.json").read_text())
    assert meta["pending"] is True
    assert meta["url"] == "https://example.com/x"
    assert meta.get("title") is None
    assert "error" not in meta


def test_list_episodes_status_field_pending(tmp_path):
    secret = storage.create_user(tmp_path)
    storage.write_pending_episode(tmp_path, secret, source_url="https://a")

    eps = storage.list_episodes(tmp_path, secret)

    assert len(eps) == 1
    assert eps[0]["status"] == "pending"


def test_list_episodes_status_field_ready(tmp_path):
    secret = storage.create_user(tmp_path)
    storage.write_episode(tmp_path, secret, title="Hi",
                          source_url="https://a", audio=b"X")

    eps = storage.list_episodes(tmp_path, secret)

    assert eps[0]["status"] == "ready"


def test_list_episodes_status_field_failed(tmp_path):
    secret = storage.create_user(tmp_path)
    storage.write_failed_episode(tmp_path, secret,
                                  source_url="https://b", error="boom")

    eps = storage.list_episodes(tmp_path, secret)

    assert eps[0]["status"] == "failed"
```

- [ ] **Step 2: Run, verify the new tests FAIL**

```bash
cd /Users/noah/Desktop/feed-me && uv run pytest tests/test_storage.py -v -k "pending or status_field"
```

Expected: `test_write_pending_episode_writes_json_only` fails (no `write_pending_episode`), and the three `status_field` tests fail with `KeyError: 'status'` (list_episodes doesn't return a status field yet).

- [ ] **Step 3: Implement in `storage.py`**

Add the new `write_pending_episode` function after `write_failed_episode`:

```python
def write_pending_episode(
    data_dir: Path, secret: str, *,
    source_url: str,
) -> str:
    slug = _new_slug()
    (data_dir / secret / f"{slug}.json").write_text(json.dumps({
        "title": None,
        "url": source_url,
        "ts": int(time.time()),
        "pending": True,
    }))
    return slug
```

Replace the existing `list_episodes` function with this version that derives `status`:

```python
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
            if data.get("error"):
                data["status"] = "failed"
            elif data.get("pending"):
                data["status"] = "pending"
            else:
                data["status"] = "ready"
            records.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    records.sort(key=lambda r: r["mtime"], reverse=True)
    return records
```

- [ ] **Step 4: Run all storage tests, verify they pass**

```bash
cd /Users/noah/Desktop/feed-me && uv run pytest tests/test_storage.py -v
```

Expected: all tests pass (the original `test_list_episodes_returns_newest_first` etc. still pass because adding `status` to the dict doesn't break them).

- [ ] **Step 5: Commit**

```bash
cd /Users/noah/Desktop/feed-me && git add storage.py tests/test_storage.py && git commit -m "feat(storage): write_pending_episode and derived status field"
```

---

## Task 2: `write_episode` and `write_failed_episode` accept optional `slug` parameter

**Files:**
- Modify: `/Users/noah/Desktop/feed-me/storage.py`
- Modify: `/Users/noah/Desktop/feed-me/tests/test_storage.py`

The pending → ready/failed promotion needs to update the SAME json file the pending record was written to. So both writers need to accept an optional `slug` that, if provided, overwrites instead of creating a new record.

- [ ] **Step 1: Append the failing tests to `tests/test_storage.py`**

```python
def test_write_episode_promotes_pending(tmp_path):
    secret = storage.create_user(tmp_path)
    slug = storage.write_pending_episode(
        tmp_path, secret, source_url="https://example.com/x",
    )

    returned = storage.write_episode(
        tmp_path, secret,
        title="On Time", source_url="https://example.com/x",
        audio=b"FAKEMP3", slug=slug,
    )

    # Same slug returned, same file updated, no second file created
    assert returned == slug
    eps = storage.list_episodes(tmp_path, secret)
    assert len(eps) == 1
    assert eps[0]["status"] == "ready"
    assert eps[0]["title"] == "On Time"
    assert "pending" not in eps[0] or eps[0].get("pending") is None


def test_write_failed_episode_promotes_pending(tmp_path):
    secret = storage.create_user(tmp_path)
    slug = storage.write_pending_episode(
        tmp_path, secret, source_url="https://example.com/y",
    )

    returned = storage.write_failed_episode(
        tmp_path, secret,
        source_url="https://example.com/y", error="paywalled", slug=slug,
    )

    assert returned == slug
    eps = storage.list_episodes(tmp_path, secret)
    assert len(eps) == 1
    assert eps[0]["status"] == "failed"
    assert eps[0]["error"] == "paywalled"
```

- [ ] **Step 2: Run, verify the new tests FAIL**

```bash
cd /Users/noah/Desktop/feed-me && uv run pytest tests/test_storage.py -v -k "promotes_pending"
```

Expected: FAIL with `TypeError: write_episode() got an unexpected keyword argument 'slug'`.

- [ ] **Step 3: Update `write_episode` and `write_failed_episode` in `storage.py`**

Replace the existing `write_episode`:

```python
def write_episode(
    data_dir: Path, secret: str, *,
    title: str, source_url: str, audio: bytes,
    slug: str | None = None,
) -> str:
    if slug is None:
        slug = _new_slug()
    user_dir = data_dir / secret
    (user_dir / f"{slug}.mp3").write_bytes(audio)
    (user_dir / f"{slug}.json").write_text(json.dumps({
        "title": title,
        "url": source_url,
        "ts": int(time.time()),
    }))
    return slug
```

Replace the existing `write_failed_episode`:

```python
def write_failed_episode(
    data_dir: Path, secret: str, *,
    source_url: str, error: str,
    slug: str | None = None,
) -> str:
    if slug is None:
        slug = _new_slug()
    (data_dir / secret / f"{slug}.json").write_text(json.dumps({
        "title": None,
        "url": source_url,
        "ts": int(time.time()),
        "error": error,
    }))
    return slug
```

- [ ] **Step 4: Run all storage tests, verify they pass**

```bash
cd /Users/noah/Desktop/feed-me && uv run pytest tests/test_storage.py -v
```

Expected: all tests pass. The old tests that called `write_episode` without `slug` still work because the parameter is optional and defaults to None.

- [ ] **Step 5: Commit**

```bash
cd /Users/noah/Desktop/feed-me && git add storage.py tests/test_storage.py && git commit -m "feat(storage): optional slug param on write_episode/write_failed_episode for in-place promotion"
```

---

## Task 3: `ingest.process` writes pending then promotes

**Files:**
- Modify: `/Users/noah/Desktop/feed-me/ingest.py`
- Modify: `/Users/noah/Desktop/feed-me/tests/test_ingest.py`

- [ ] **Step 1: Append the failing test to `tests/test_ingest.py`**

```python
def test_process_writes_pending_then_ready(
    monkeypatch, fake_http, fake_openai, tmp_path,
):
    monkeypatch.setattr(ingest, "http_client", fake_http)
    monkeypatch.setattr(ingest, "openai_client", fake_openai)
    fake_http.responses["https://example.com/p"] = FakeResponse(
        status_code=200, text=HTML_SAMPLE,
    )

    secret = storage.create_user(tmp_path)

    # Observe pending state by hooking fetch_article — at the moment fetch
    # is called, the pending record must already exist.
    observed_status_during_fetch = []
    real_fetch = ingest.fetch_article
    def observing_fetch(url):
        eps = storage.list_episodes(tmp_path, secret)
        observed_status_during_fetch.append(
            [e.get("status") for e in eps]
        )
        return real_fetch(url)
    monkeypatch.setattr(ingest, "fetch_article", observing_fetch)

    ingest.process("https://example.com/p", secret, tmp_path)

    # During fetch: exactly one pending record existed.
    assert observed_status_during_fetch == [["pending"]]
    # After process: exactly one record, promoted to ready.
    eps = storage.list_episodes(tmp_path, secret)
    assert len(eps) == 1
    assert eps[0]["status"] == "ready"
```

- [ ] **Step 2: Run, verify the test FAILS**

```bash
cd /Users/noah/Desktop/feed-me && uv run pytest tests/test_ingest.py::test_process_writes_pending_then_ready -v
```

Expected: FAIL — `observed_status_during_fetch` will be `[[]]` (no pending record exists during fetch) because the current `process()` only writes after fetch completes.

- [ ] **Step 3: Update `process()` in `ingest.py`**

Replace the existing `process` function with this version:

```python
def process(url: str, secret: str, data_dir: Path) -> None:
    slug = storage.write_pending_episode(data_dir, secret, source_url=url)
    try:
        title, body = fetch_article(url)
        settings = storage.get_settings(data_dir, secret)
        audio = synthesize(body, settings["voice"])
        storage.write_episode(
            data_dir, secret, slug=slug,
            title=title, source_url=url, audio=audio,
        )
    except Exception as e:
        log.exception("ingest failed user=%s url=%s", secret[:6], url)
        storage.write_failed_episode(
            data_dir, secret, slug=slug,
            source_url=url, error=str(e)[:200],
        )
```

- [ ] **Step 4: Run all ingest tests, verify they pass**

```bash
cd /Users/noah/Desktop/feed-me && uv run pytest tests/test_ingest.py -v
```

Expected: all tests pass. The existing `test_process_writes_episode_on_success` and `test_process_writes_failure_on_extraction_error` still pass because the SAME slug gets promoted (so `len(eps) == 1` still holds, and the final status is correct).

- [ ] **Step 5: Commit**

```bash
cd /Users/noah/Desktop/feed-me && git add ingest.py tests/test_ingest.py && git commit -m "feat(ingest): write pending stub at start, promote to ready/failed at end"
```

---

## Task 4: `app.relative_time` helper

**Files:**
- Modify: `/Users/noah/Desktop/feed-me/app.py`
- Modify: `/Users/noah/Desktop/feed-me/tests/test_app.py`

- [ ] **Step 1: Append the failing tests to `tests/test_app.py`**

```python
def test_relative_time_just_now():
    import app
    assert app.relative_time(1_000_000, now=1_000_000) == "just now"
    assert app.relative_time(1_000_000, now=1_000_059) == "just now"


def test_relative_time_minutes():
    import app
    assert app.relative_time(1_000_000, now=1_000_060) == "1 min ago"
    assert app.relative_time(1_000_000, now=1_000_000 + 30 * 60) == "30 min ago"


def test_relative_time_hours():
    import app
    assert app.relative_time(1_000_000, now=1_000_000 + 3600) == "1 h ago"
    assert app.relative_time(1_000_000, now=1_000_000 + 5 * 3600) == "5 h ago"


def test_relative_time_days():
    import app
    assert app.relative_time(1_000_000, now=1_000_000 + 86400) == "1 d ago"
    assert app.relative_time(1_000_000, now=1_000_000 + 3 * 86400) == "3 d ago"


def test_relative_time_absolute_after_week():
    import app
    # 2001-09-09 01:46:40 UTC (the famous 1_000_000_000 epoch)
    result = app.relative_time(1_000_000_000, now=1_000_000_000 + 8 * 86400)
    assert result == "2001-09-09"
```

- [ ] **Step 2: Run, verify the tests FAIL**

```bash
cd /Users/noah/Desktop/feed-me && uv run pytest tests/test_app.py -v -k "relative_time"
```

Expected: FAIL with `AttributeError: module 'app' has no attribute 'relative_time'`.

- [ ] **Step 3: Implement in `app.py`**

Add this helper near the top of `app.py` (after the imports, before the route definitions):

```python
import time as _time
from datetime import datetime, timezone


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
```

If `app.py` already imports `time` at the top level (it doesn't currently — check), use that import name instead. Aliasing as `_time` here is to avoid name clash with any local variable `time`.

- [ ] **Step 4: Run, verify the tests pass**

```bash
cd /Users/noah/Desktop/feed-me && uv run pytest tests/test_app.py -v -k "relative_time"
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/noah/Desktop/feed-me && git add app.py tests/test_app.py && git commit -m "feat(app): relative_time helper (just now / N min ago / N h ago / N d ago / YYYY-MM-DD)"
```

---

## Task 5: Rewrite `templates/settings.html` and enrich the settings route

**Files:**
- Modify: `/Users/noah/Desktop/feed-me/templates/settings.html` (full rewrite)
- Modify: `/Users/noah/Desktop/feed-me/app.py` (enrich settings route)
- Modify: `/Users/noah/Desktop/feed-me/tests/test_app.py` (update assertions, add pending-status test)

- [ ] **Step 1: Update the existing `test_settings_renders_for_known_user` test in `tests/test_app.py`**

Replace the existing function with this version:

```python
def test_settings_renders_for_known_user(client):
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]

    response = client.get(f"/u/{secret}")
    assert response.status_code == 200
    # v1.3 structure: three-phase layout
    assert "Set up" in response.text
    assert "Install Shortcut" in response.text
    assert "Add to Apple Podcasts" in response.text
    assert "Copy feed URL" in response.text
    assert "Share an article" in response.text
    assert "Feed Me" in response.text
    # Episode table headers
    assert "Recent episodes" in response.text
    # Settings drawer
    assert "Settings" in response.text
    # Ingest URL still appears in the page (for the auto-copy JS)
    assert f"/u/{secret}/ingest" in response.text
```

Also replace `test_settings_lists_recent_episodes` with this updated version:

```python
def test_settings_lists_recent_episodes(client, tmp_path):
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]

    import storage
    storage.write_episode(tmp_path, secret, title="My Article",
                          source_url="https://example.com/a", audio=b"X")

    response = client.get(f"/u/{secret}")
    assert "My Article" in response.text
    assert "Ready" in response.text  # status chip
```

Append a new test for pending state:

```python
def test_settings_shows_pending_episode(client, tmp_path):
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]

    import storage
    storage.write_pending_episode(tmp_path, secret,
                                   source_url="https://example.com/p")

    response = client.get(f"/u/{secret}")
    assert "Pending" in response.text
```

- [ ] **Step 2: Run, verify the existing test fails (the new assertions trip)**

```bash
cd /Users/noah/Desktop/feed-me && uv run pytest tests/test_app.py -v -k "settings"
```

Expected: failures on the new assertions ("Set up", "Copy feed URL", "Share an article", "Ready", "Pending" not yet in template).

- [ ] **Step 3: Update the settings route in `app.py`**

Find the existing `settings` route and replace it with:

```python
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
```

The two new lines are `now_ts = int(_time.time())` and the `for ep in eps: ep["when"] = ...` loop. Everything else is preserved.

- [ ] **Step 4: Replace `templates/settings.html` with the v1.3 layout**

Replace the entire contents of `/Users/noah/Desktop/feed-me/templates/settings.html` with:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Your Feed Me feed</title>
  <style>
    body {
      font-family: -apple-system, "Inter", "Helvetica Neue", system-ui, sans-serif;
      max-width: 480px; margin: 40px auto; padding: 0 20px;
      line-height: 1.5; color: #0a0a0a; background: #fff;
      -webkit-font-smoothing: antialiased;
    }
    .brand {
      font-size: 10px; color: #767676; text-transform: uppercase;
      letter-spacing: 0.14em; font-weight: 700; margin-bottom: 16px;
    }
    h1 { font-size: 26px; font-weight: 600; letter-spacing: -0.02em;
         line-height: 1.15; margin: 0 0 6px; }
    .bookmark-tip {
      background: #FFF8DC; border-left: 3px solid #B8860B;
      padding: 10px 13px; font-size: 12px; color: #5a4a14;
      margin: 14px 0 28px; border-radius: 3px;
    }
    h2 {
      font-size: 11px; color: #767676; text-transform: uppercase;
      letter-spacing: 0.14em; font-weight: 700;
      margin: 32px 0 4px; padding-top: 18px; border-top: 1px solid #eee;
    }
    h2:first-of-type { border-top: none; padding-top: 0; margin-top: 24px; }
    .phase-note { font-size: 12px; color: #6a6a6a; margin: 0 0 8px; }
    .step-row {
      display: grid; grid-template-columns: 26px 1fr; gap: 14px;
      padding: 10px 0; align-items: start; position: relative;
    }
    .step-row:not(:last-of-type)::before {
      content: ''; position: absolute;
      left: 12px; top: 36px; bottom: -6px;
      width: 1.5px; background: #eaeaea;
    }
    .step-num {
      width: 24px; height: 24px; border-radius: 50%;
      border: 1.5px solid #0a0a0a; display: flex; align-items: center;
      justify-content: center; font-size: 12px; font-weight: 700;
      background: #fff; position: relative; z-index: 1;
    }
    .step-body { font-size: 14px; }
    .step-body .title { font-weight: 600; color: #0a0a0a; margin-bottom: 3px; }
    .step-body .desc { font-size: 12px; color: #6a6a6a; line-height: 1.45; }
    .step-body kbd {
      font-family: -apple-system, sans-serif;
      background: #f3f1ec; padding: 1px 6px; border-radius: 3px;
      font-size: 12px; font-weight: 600; color: #0a0a0a;
      border: 1px solid #e5e3dd;
    }
    .ios-share {
      display: inline-block; width: 1em; height: 1em;
      vertical-align: -0.15em; margin: 0 1px; color: #007AFF;
    }
    .btn-primary, .btn-secondary {
      display: inline-block; padding: 10px 18px; font-size: 13px;
      border-radius: 999px; font-weight: 600; cursor: pointer;
      text-decoration: none; margin-top: 8px; border: none;
      font-family: inherit; box-sizing: border-box;
    }
    .btn-primary { background: #0a0a0a; color: #fff; }
    .btn-secondary { background: #fff; color: #0a0a0a; border: 1px solid #d0d0d0; }
    .btn-pair { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px; }
    .btn-pair .btn-primary, .btn-pair .btn-secondary { margin-top: 0; }
    .url-pill {
      font-family: "SF Mono", Menlo, monospace; font-size: 11px;
      background: #f3f1ec; padding: 7px 10px; border-radius: 4px;
      word-break: break-all; margin: 8px 0 6px; color: #4a4a4a;
    }
    .ep-table { margin-top: 10px; width: 100%; border-collapse: collapse; font-size: 13px; }
    .ep-table thead th {
      font-size: 10px; color: #767676; text-transform: uppercase;
      letter-spacing: 0.08em; font-weight: 600; text-align: left;
      padding: 6px 0; border-bottom: 1px solid #eee;
    }
    .ep-table th.col-time { width: 70px; }
    .ep-table th.col-status { width: 64px; text-align: right; }
    .ep-table tbody td {
      padding: 11px 8px 11px 0; border-bottom: 1px solid #f3f3f3; vertical-align: top;
    }
    .ep-table td.col-title { color: #0a0a0a; font-weight: 500; }
    .ep-table td.col-title .src {
      display: block; font-size: 10px; color: #767676;
      font-family: "SF Mono", Menlo, monospace; margin-top: 2px;
      word-break: break-all;
    }
    .ep-table td.col-time { color: #767676; font-size: 11px; font-variant-numeric: tabular-nums; }
    .ep-table td.col-status { text-align: right; }
    .status-chip {
      display: inline-block; padding: 2px 8px;
      font-size: 10px; font-weight: 700; text-transform: uppercase;
      letter-spacing: 0.06em; border-radius: 999px;
    }
    .status-chip.ready { background: #e3f1e3; color: #2f7a3d; }
    .status-chip.failed { background: #f6e0d6; color: #b04a00; }
    .status-chip.pending { background: #f3f1ec; color: #767676; }
    .ep-empty { color: #767676; font-size: 12px; font-style: italic; padding: 14px 0; }
    .voices { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
    .voice-chip {
      padding: 5px 12px; border: 1px solid #d0d0d0; background: #fff;
      border-radius: 999px; font-size: 12px; cursor: pointer;
      font-family: inherit;
    }
    .voice-chip.active { background: #0a0a0a; color: #fff; border-color: #0a0a0a; }
    form { display: inline; }
    details.settings { margin-top: 36px; padding-top: 14px; border-top: 1px solid #eee; }
    details.settings > summary {
      cursor: pointer; font-size: 10px; color: #767676;
      text-transform: uppercase; letter-spacing: 0.14em; font-weight: 700;
      padding: 6px 0; list-style: none; user-select: none;
    }
    details.settings > summary::-webkit-details-marker { display: none; }
    details.settings > summary::before {
      content: '▸ '; font-size: 9px; transition: transform 0.15s;
      display: inline-block; margin-right: 4px;
    }
    details.settings[open] > summary::before { transform: rotate(90deg); }
    details.settings .body { padding: 8px 0 4px; }
    details.settings .body .label {
      font-size: 12px; font-weight: 600; color: #0a0a0a; margin-top: 18px;
    }
    details.settings .body .label:first-child { margin-top: 6px; }
    details.settings .body p { font-size: 11px; color: #6a6a6a; margin: 4px 0 6px; }
    .danger-label { color: #b04a00 !important; }
    .danger-btn { border-color: #e5b8a0 !important; color: #b04a00 !important; }
  </style>
</head>
<body>

  <svg width="0" height="0" style="position:absolute" aria-hidden="true">
    <symbol id="ios-share" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <line x1="12" y1="3" x2="12" y2="15"/>
      <polyline points="7 8 12 3 17 8"/>
      <path d="M5 12v6a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-6"/>
    </symbol>
  </svg>

  <div class="brand">Feed Me</div>
  <h1>Your feed is ready.</h1>
  <div class="bookmark-tip">
    Bookmark this page — it's your account. Losing the URL means losing the feed.
  </div>

  <h2>Set up · do this once</h2>

  <div class="step-row">
    <div class="step-num">1</div>
    <div class="step-body">
      <div class="title">Install the Shortcut</div>
      <div class="desc">We'll copy your ingest URL to your clipboard first, then iOS will ask you to paste it during install.</div>
      <button class="btn-primary" type="button" onclick="installShortcut()">Install Shortcut</button>
    </div>
  </div>

  <div class="step-row">
    <div class="step-num">2</div>
    <div class="step-body">
      <div class="title">Subscribe in your podcast app</div>
      <div class="desc">One tap for Apple Podcasts. For Overcast, Pocket Casts, Castro, etc., copy the URL and paste it in.</div>
      <div class="btn-pair">
        <a class="btn-primary" href="podcasts://{{ feed_host_and_path }}">Add to Apple Podcasts</a>
        <button class="btn-secondary" type="button" onclick="copyFeedUrl()">Copy feed URL</button>
      </div>
    </div>
  </div>

  <h2>Share an article · do this anytime</h2>
  <p class="phase-note">In Safari (or Mail, Reader, anywhere with a Share button):</p>

  <div class="step-row">
    <div class="step-num">1</div>
    <div class="step-body">
      <div class="title">
        Tap <svg class="ios-share"><use href="#ios-share"/></svg> at the bottom of the screen
      </div>
      <div class="desc">That's the iOS Share button.</div>
    </div>
  </div>

  <div class="step-row">
    <div class="step-num">2</div>
    <div class="step-body">
      <div class="title">Scroll to <kbd>Feed Me</kbd> and tap it</div>
      <div class="desc">It lives in the row of app icons. You'll get a "Sent ✓" notification.</div>
    </div>
  </div>

  <div class="step-row">
    <div class="step-num">3</div>
    <div class="step-body">
      <div class="title">Wait ~60 seconds</div>
      <div class="desc">The article appears as a new episode in your podcast app. Pull-to-refresh if it's slow.</div>
    </div>
  </div>

  <h2>Recent episodes</h2>
  {% if episodes %}
    <table class="ep-table">
      <thead>
        <tr>
          <th class="col-title">Article</th>
          <th class="col-time">When</th>
          <th class="col-status">Status</th>
        </tr>
      </thead>
      <tbody>
        {% for ep in episodes %}
          <tr>
            <td class="col-title">
              {{ ep.title or "(couldn't extract article)" }}
              <span class="src">{{ ep.url }}</span>
            </td>
            <td class="col-time">{{ ep.when }}</td>
            <td class="col-status">
              {% if ep.status == "ready" %}
                <span class="status-chip ready">Ready</span>
              {% elif ep.status == "pending" %}
                <span class="status-chip pending">Pending</span>
              {% else %}
                <span class="status-chip failed">Failed</span>
              {% endif %}
            </td>
          </tr>
        {% endfor %}
      </tbody>
    </table>
  {% else %}
    <p class="ep-empty">No episodes yet. Share an article to test.</p>
  {% endif %}

  <details class="settings">
    <summary>Settings</summary>
    <div class="body">

      <div class="label">Voice</div>
      <p>Choose how the narration sounds. Affects future episodes only.</p>
      <div class="voices">
        {% for v in voices %}
          <form action="/u/{{ secret }}/voice" method="post">
            <input type="hidden" name="voice" value="{{ v }}">
            <button class="voice-chip {% if v == current_voice %}active{% endif %}" type="submit">{{ v }}</button>
          </form>
        {% endfor %}
      </div>

      <div class="label">Ingest URL</div>
      <p>For re-pasting into the Shortcut later, or setting up another device. Step 1 already copied this for you.</p>
      <div class="url-pill" id="ingest-url">{{ ingest_url }}</div>
      <button class="btn-secondary" type="button" onclick="copyIngestUrl()">Copy ingest URL</button>

      <div class="label danger-label">Rotate URL</div>
      <p>Use only if you suspect someone else has your URL. Old one stops working.</p>
      <form action="/u/{{ secret }}/rotate" method="post">
        <button class="btn-secondary danger-btn" type="submit"
                onclick="return confirm('Generate a new URL? Old one will stop working.')">Rotate</button>
      </form>

    </div>
  </details>

  <script>
    var INGEST_URL = {{ ingest_url | tojson }};
    var SHORTCUT_URL = {{ shortcut_url | tojson }};
    var FEED_URL = {{ feed_url | tojson }};

    function installShortcut() {
      var go = function () { window.location.href = SHORTCUT_URL; };
      try {
        navigator.clipboard.writeText(INGEST_URL).then(go, go);
      } catch (e) { go(); }
    }
    function copyFeedUrl() {
      try { navigator.clipboard.writeText(FEED_URL); } catch (e) {}
    }
    function copyIngestUrl() {
      try { navigator.clipboard.writeText(INGEST_URL); } catch (e) {}
    }
  </script>

</body>
</html>
```

- [ ] **Step 5: Run the full test suite, verify all 47+ tests pass**

```bash
cd /Users/noah/Desktop/feed-me && uv run pytest -v
```

Expected: all tests pass — the original 42 plus the new tests from Tasks 1-4 plus the new pending settings test.

- [ ] **Step 6: Local sanity check**

```bash
cd /Users/noah/Desktop/feed-me && uv run uvicorn app:app --port 8000
```

In a separate terminal:
```bash
curl -s -X POST http://localhost:8000/create -o /dev/null -w "%{redirect_url}\n"
```

Visit the printed URL in a browser. Confirm:
- Brand mark, h1, bookmark tip render at top
- "Set up · do this once" header with two numbered steps (Install Shortcut, Subscribe)
- "Share an article · do this anytime" header with three numbered steps; iOS share icon visible in step 1
- "Recent episodes" with empty state ("No episodes yet")
- "▸ Settings" collapsible at bottom; click to expand and see Voice / Ingest URL / Rotate

Kill the server with Ctrl+C.

- [ ] **Step 7: Commit**

```bash
cd /Users/noah/Desktop/feed-me && git add app.py templates/settings.html tests/test_app.py && git commit -m "feat(app): settings page v1.3 — three-phase layout with episodes table and collapsible Settings

Set up · do this once → Install Shortcut, Subscribe (paired buttons)
Share an article · do this anytime → 3 numbered steps with inline iOS share icon
Recent episodes → 3-col table with Ready/Pending/Failed status chips
Settings → collapsed details with Voice, Ingest URL, Rotate

Adds relative_time helper for the When column.
Settings route enriches each episode dict with .when before rendering.
Pending episodes now show up between share and ready/failed via the
new write_pending_episode promotion flow.

Spec: docs/superpowers/specs/2026-05-26-settings-page-redesign.html"
```

---

## Task 6: Deploy to Fly and smoke test on `feed-me.xyz`

**Files:** none (deploy only, plus CHANGELOG + tag)

- [ ] **Step 1: Deploy**

```bash
~/.fly/bin/fly deploy --app feed-me-noah-willow-grove-8052
```

Expected: build completes, machine update succeeds.

- [ ] **Step 2: Smoke test the live HTML**

```bash
SECRET=$(curl -s -X POST https://feed-me.xyz/create -o /dev/null -w "%{redirect_url}" | sed 's|.*/u/||') ; \
echo "test user: $SECRET" ; \
curl -s "https://feed-me.xyz/u/$SECRET" | grep -oE "(Set up|Share an article|Recent episodes|Install Shortcut|Add to Apple Podcasts|Copy feed URL|Settings)" | sort -u
```

Expected: all of: `Set up`, `Share an article`, `Recent episodes`, `Install Shortcut`, `Add to Apple Podcasts`, `Copy feed URL`, `Settings`.

- [ ] **Step 3: Verify the pending state in production**

In one terminal:
```bash
curl -s "https://feed-me.xyz/u/$SECRET/ingest?url=https://www.paulgraham.com/winc.html"
```

Within 1-2 seconds, in another terminal:
```bash
curl -s "https://feed-me.xyz/u/$SECRET" | grep -E "(Pending|Ready)" | head -3
```

Expected: `Pending` appears in the response while ingest is in flight. Wait ~60 seconds, re-run the second command — expected: `Ready` appears instead.

- [ ] **Step 4: iPhone visual verification**

On your iPhone:
1. Open Safari → navigate to your bookmarked settings page (or the test secret URL printed above)
2. Verify the page is readable end-to-end without horizontal scroll
3. Tap "Install Shortcut" — clipboard should be populated, iCloud install card opens with paste suggestion
4. Tap "Copy feed URL" — verify clipboard has the .xml URL
5. Tap the collapsed "▸ Settings" → expands cleanly, shows Voice / Ingest URL / Rotate
6. Tap a different voice chip → page reloads, that chip is now active

If anything overflows or looks visually wrong, tweak `templates/settings.html` and re-deploy.

- [ ] **Step 5: Update CHANGELOG and tag v1.3**

Replace the top of `/Users/noah/Desktop/feed-me/CHANGELOG.md` (insert above the v1.2 entry):

```markdown
## v1.3 — 2026-05-26

Settings page redesigned for friend-onboarding:

- Three-phase layout: Set up (Install Shortcut + Subscribe in podcast app, paired buttons) → Share an article (3 numbered steps with inline iOS Share icon SVG and "Feed Me" rendered as a kbd-style tag) → Recent episodes (3-column table with Ready / Pending / Failed status chips and friendly "When" column)
- Voice picker, Ingest URL, and Rotate moved into a collapsible Settings drawer at the bottom (closed by default)
- Backend gains a "pending" episode state: `ingest.process` now writes a pending stub before fetch and promotes it to ready/failed on completion, so just-shared articles show up on the next refresh instead of vanishing into the void
- `app.relative_time` helper buckets timestamps into "just now / N min ago / N h ago / N d ago / YYYY-MM-DD"
- `storage.write_episode` and `write_failed_episode` gain an optional `slug` param for in-place promotion
- Spec: `docs/superpowers/specs/2026-05-26-settings-page-redesign.html`
```

Then:

```bash
cd /Users/noah/Desktop/feed-me && git add CHANGELOG.md && git commit -m "release: v1.3 settings page redesign" && git tag v1.3
```

---

## Self-Review

### Spec coverage

| Spec section | Implementing task(s) |
|---|---|
| §2 Three-phase structure | Task 5 (template + route enrichment) |
| §2 Pending state requirement | Tasks 1 (storage), 2 (slug promotion), 3 (ingest), 5 (template renders status chip) |
| §3 Visual direction (ASCII mockup) | Task 5 |
| §4 Copy table (all 16 slots) | Task 5 (every slot present in the template) |
| §5 Files modified list | Tasks 1-5 cover all listed files |
| §5 Pending state mechanics (3-step flow) | Tasks 1 (pending writer), 2 (slug param), 3 (process flow) |
| §5 Relative time helper with bucket rules | Task 4 |
| §5 Inline iOS Share SVG via symbol/use | Task 5 |
| §5 Color palette | Task 5 (all hex values in template style block) |
| §5 Timeline hairline (per-phase, not crossing) | Task 5 (using `:not(:last-of-type)` selector — note: scoped to step-rows that are siblings under the same parent block, naturally breaking at phase boundaries because h2 separates them) |
| §5 Collapsible Settings via native details | Task 5 |
| §6 Storage tests (3 new) | Task 1 |
| §6 Ingest tests (pending-then-promote) | Task 3 |
| §6 App tests (updated assertions + pending) | Task 5 |
| §9 Deployment + iPhone verification | Task 6 |
| §9 CHANGELOG and tag | Task 6 |

All spec sections covered. Out-of-scope items (live status updates, per-episode retry, etc.) are correctly absent from the plan.

### Placeholder scan

Scanned for "TBD", "TODO", "implement later", "fill in", "appropriate error handling", "similar to Task N", "etc". None found. Every code block is the full final content. Every test has explicit assertions. Every command has expected output described.

### Type consistency

- `slug` parameter is consistently `str | None = None` across `write_episode`, `write_failed_episode`; `write_pending_episode` returns `str` (always).
- `status` field consistently `"ready" | "pending" | "failed"` derived in `list_episodes`.
- Episode dict shape consistent across storage layer and template usage:
  `{slug, title, url, ts, mtime, has_audio, status, error?, pending?, when (added in route)}`.
- `relative_time` signature consistent: `(ts: int, now: int | None = None) -> str`.
- All template `{{ ... }}` placeholders match the keys passed by the settings route in Task 5 step 3.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-26-settings-page-redesign.md`.

Six tasks: four small (storage / ingest / helper) and two larger (template rewrite + deploy). Estimated 45 minutes of focused subagent work end-to-end.
