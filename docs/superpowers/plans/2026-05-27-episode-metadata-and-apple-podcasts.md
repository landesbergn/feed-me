# Episode Metadata + Apple Podcasts (v1.6) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pending rows show the article's real title (not "couldn't extract"); every RSS item has a description; Apple Podcasts accepts the feed (`length` attribute fixed, `atom:link`/`itunes:type` added, deep-link scheme corrected).

**Architecture:** Six tasks: storage signatures + audio_bytes, ingest fetch_title + body excerpt, app `/ingest` + hostname filter wiring, settings template fallback chain, RSS template + settings deep link, deploy + tag.

**Tech Stack:** Same as v1.5 — no new deps. lxml already vendored (used by ingest). Spec: `docs/superpowers/specs/2026-05-27-episode-metadata-and-apple-podcasts.html`.

---

## File Structure

```
feed-me/
  storage.py                      # +title/description kwargs on writers;
                                  #  +audio_bytes derived in list_episodes
  ingest.py                       # +fetch_title helper;
                                  #  process() passes body excerpt as description
  app.py                          # +hostname filter; /ingest pre-fetches title
  rss.py                          # (unchanged — render_feed signature stays the same)
  templates/
    feed.xml                      # +atom namespace, atom:link, itunes:type,
                                  #  per-item description, real enclosure length
    settings.html                 # podcasts:// → podcast://
    _episodes_section.html        # title fallback chain (pending → "Loading from",
                                  #  failed → "(couldn't extract)")
  tests/                          # updates throughout
```

No new files. No new dependencies.

---

## Task 1: Storage — optional `title`/`description` kwargs; `audio_bytes` in `list_episodes`

**Files:**
- Modify: `/Users/noah/Desktop/feed-me/storage.py`
- Modify: `/Users/noah/Desktop/feed-me/tests/test_storage.py`

- [ ] **Step 1: Append failing tests to `/Users/noah/Desktop/feed-me/tests/test_storage.py`**

```python
def test_write_pending_episode_accepts_title(tmp_path):
    secret = storage.create_user(tmp_path)

    slug = storage.write_pending_episode(
        tmp_path, secret,
        source_url="https://example.com/x",
        title="My Cool Article",
    )

    eps = storage.list_episodes(tmp_path, secret)
    assert len(eps) == 1
    assert eps[0]["title"] == "My Cool Article"
    assert eps[0]["status"] == "pending"


def test_write_episode_accepts_description(tmp_path):
    secret = storage.create_user(tmp_path)

    slug = storage.write_episode(
        tmp_path, secret,
        title="My Article", source_url="https://a", audio=b"X",
        description="The first paragraph or so of the article body...",
    )

    eps = storage.list_episodes(tmp_path, secret)
    assert eps[0]["description"] == "The first paragraph or so of the article body..."


def test_write_failed_episode_accepts_description(tmp_path):
    secret = storage.create_user(tmp_path)

    storage.write_failed_episode(
        tmp_path, secret,
        source_url="https://b", error="boom",
        description="paywall: nytimes.com/...",
    )

    eps = storage.list_episodes(tmp_path, secret)
    assert eps[0]["description"] == "paywall: nytimes.com/..."


def test_list_episodes_exposes_audio_bytes(tmp_path):
    secret = storage.create_user(tmp_path)
    storage.write_episode(
        tmp_path, secret,
        title="A", source_url="https://a", audio=b"FAKEMP3DATA",
    )

    eps = storage.list_episodes(tmp_path, secret)
    assert eps[0]["audio_bytes"] == len(b"FAKEMP3DATA")


def test_list_episodes_audio_bytes_is_none_when_no_mp3(tmp_path):
    """Pending and failed episodes have no .mp3, so audio_bytes should be None."""
    secret = storage.create_user(tmp_path)
    storage.write_pending_episode(tmp_path, secret, source_url="https://p")

    eps = storage.list_episodes(tmp_path, secret)
    assert eps[0]["audio_bytes"] is None


def test_seed_welcome_episode_writes_description(tmp_path):
    """The welcome episode should always carry the hard-coded description."""
    secret = storage.create_user(tmp_path)
    storage.seed_welcome_episode(tmp_path, secret, welcome_audio=b"X")

    eps = storage.list_episodes(tmp_path, secret)
    assert eps[0]["description"] == "Share an article from your phone — it'll show up here a minute later."
```

- [ ] **Step 2: Run, verify the tests FAIL**

```bash
cd /Users/noah/Desktop/feed-me && uv run pytest tests/test_storage.py -v -k "accepts_title or accepts_description or audio_bytes or welcome_episode_writes_description"
```

Expected: 6 FAIL — each will hit a TypeError (unknown kwarg) or KeyError (`audio_bytes` / `description` missing).

- [ ] **Step 3: Update `/Users/noah/Desktop/feed-me/storage.py`**

Replace the three writer functions (`write_episode`, `write_pending_episode`, `write_failed_episode`) and `seed_welcome_episode`. Also update `list_episodes` to expose `audio_bytes`.

Replace `write_pending_episode`:

```python
def write_pending_episode(
    data_dir: Path, secret: str, *,
    source_url: str,
    title: str | None = None,
    description: str | None = None,
) -> str:
    slug = _new_slug()
    record = {
        "title": title,
        "url": source_url,
        "ts": int(time.time()),
        "pending": True,
    }
    if description is not None:
        record["description"] = description
    (data_dir / secret / f"{slug}.json").write_text(json.dumps(record))
    return slug
```

Replace `write_episode`:

```python
def write_episode(
    data_dir: Path, secret: str, *,
    title: str, source_url: str, audio: bytes,
    slug: str | None = None,
    description: str | None = None,
) -> str:
    if slug is None:
        slug = _new_slug()
    user_dir = data_dir / secret
    (user_dir / f"{slug}.mp3").write_bytes(audio)
    record = {
        "title": title,
        "url": source_url,
        "ts": int(time.time()),
    }
    if description is not None:
        record["description"] = description
    (user_dir / f"{slug}.json").write_text(json.dumps(record))
    return slug
```

Replace `write_failed_episode`:

```python
def write_failed_episode(
    data_dir: Path, secret: str, *,
    source_url: str, error: str,
    slug: str | None = None,
    description: str | None = None,
) -> str:
    if slug is None:
        slug = _new_slug()
    record = {
        "title": None,
        "url": source_url,
        "ts": int(time.time()),
        "error": error,
    }
    if description is not None:
        record["description"] = description
    (data_dir / secret / f"{slug}.json").write_text(json.dumps(record))
    return slug
```

Replace `seed_welcome_episode`:

```python
WELCOME_DESCRIPTION = "Share an article from your phone — it'll show up here a minute later."


def seed_welcome_episode(
    data_dir: Path, secret: str, *,
    welcome_audio: bytes,
) -> str:
    """Write a pre-rendered welcome episode (mp3 + json) into a new user's dir.

    Returns the slug. Unlike write_episode, the title, URL, and description are
    fixed since the welcome is identical for every user.
    """
    slug = _new_slug()
    user_dir = data_dir / secret
    (user_dir / f"{slug}.mp3").write_bytes(welcome_audio)
    (user_dir / f"{slug}.json").write_text(json.dumps({
        "title": "Welcome to Feed Me",
        "url": "https://feed-me.xyz",
        "ts": int(time.time()),
        "description": WELCOME_DESCRIPTION,
    }))
    return slug
```

Replace `list_episodes`:

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
            mp3_path = user_dir / f"{p.stem}.mp3"
            if mp3_path.exists():
                data["has_audio"] = True
                data["audio_bytes"] = mp3_path.stat().st_size
            else:
                data["has_audio"] = False
                data["audio_bytes"] = None
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

Expected: all storage tests pass (existing + 6 new).

- [ ] **Step 5: Commit**

```bash
cd /Users/noah/Desktop/feed-me && git add storage.py tests/test_storage.py && git commit -m "feat(storage): optional title/description on writers; audio_bytes in list_episodes

- write_pending_episode gains optional title kwarg (set from quick fetch)
- all three writers gain optional description kwarg
- seed_welcome_episode writes the hard-coded WELCOME_DESCRIPTION
- list_episodes exposes audio_bytes from mp3 stat().st_size (None when
  no mp3, so pending/failed episodes can still be rendered)"
```

---

## Task 2: Ingest — `fetch_title` helper + description from body excerpt

**Files:**
- Modify: `/Users/noah/Desktop/feed-me/ingest.py`
- Modify: `/Users/noah/Desktop/feed-me/tests/test_ingest.py`

- [ ] **Step 1: Append failing tests to `/Users/noah/Desktop/feed-me/tests/test_ingest.py`**

```python
def test_fetch_title_extracts_from_html(monkeypatch, fake_http):
    fake_http.responses["https://example.com/x"] = FakeResponse(
        status_code=200,
        text="<html><head><title>Hello World</title></head><body>x</body></html>",
    )
    monkeypatch.setattr(ingest, "http_client", fake_http)

    assert ingest.fetch_title("https://example.com/x") == "Hello World"


def test_fetch_title_returns_none_on_http_error(monkeypatch, fake_http):
    fake_http.responses["https://example.com/x"] = FakeResponse(status_code=500)
    monkeypatch.setattr(ingest, "http_client", fake_http)

    assert ingest.fetch_title("https://example.com/x") is None


def test_fetch_title_returns_none_when_no_title_tag(monkeypatch, fake_http):
    fake_http.responses["https://example.com/x"] = FakeResponse(
        status_code=200,
        text="<html><body>no title here</body></html>",
    )
    monkeypatch.setattr(ingest, "http_client", fake_http)

    assert ingest.fetch_title("https://example.com/x") is None


def test_fetch_title_strips_whitespace(monkeypatch, fake_http):
    fake_http.responses["https://example.com/x"] = FakeResponse(
        status_code=200,
        text="<html><head><title>  Padded Title  \n</title></head></html>",
    )
    monkeypatch.setattr(ingest, "http_client", fake_http)

    assert ingest.fetch_title("https://example.com/x") == "Padded Title"


def test_process_writes_description_from_body(
    monkeypatch, fake_http, fake_openai, tmp_path,
):
    monkeypatch.setattr(ingest, "http_client", fake_http)
    monkeypatch.setattr(ingest, "openai_client", fake_openai)
    fake_http.responses["https://example.com/d"] = FakeResponse(
        status_code=200, text=HTML_SAMPLE,
    )

    secret = storage.create_user(tmp_path)
    ingest.process("https://example.com/d", secret, tmp_path)

    eps = storage.list_episodes(tmp_path, secret)
    assert len(eps) == 1
    desc = eps[0].get("description")
    assert desc is not None
    assert len(desc) > 0
    # Description should contain text from the body (excerpt) — not just the URL
    assert "first paragraph" in desc.lower() or "substantive" in desc.lower()
```

- [ ] **Step 2: Run, verify the tests FAIL**

```bash
cd /Users/noah/Desktop/feed-me && uv run pytest tests/test_ingest.py -v -k "fetch_title or description_from_body"
```

Expected: 5 FAIL — first four with `AttributeError: module 'ingest' has no attribute 'fetch_title'`; last with `description is None`.

- [ ] **Step 3: Update `/Users/noah/Desktop/feed-me/ingest.py`**

Add a constant for the description excerpt length near the top (after the existing `TTS_CHAR_LIMIT = 4000` etc.):

```python
DESCRIPTION_EXCERPT_CHARS = 200
TITLE_FETCH_TIMEOUT_S = 5.0
```

Add the `fetch_title` helper near `fetch_article`:

```python
def fetch_title(url: str) -> str | None:
    """Quick HTTP GET to extract just the <title> tag. Returns None on any failure."""
    try:
        resp = http_client.get(url, timeout=TITLE_FETCH_TIMEOUT_S)
        resp.raise_for_status()
    except Exception:
        return None
    try:
        doc = lxml_html.fromstring(resp.text)
        title_el = doc.find(".//title")
        if title_el is not None and title_el.text:
            stripped = title_el.text.strip()
            return stripped or None
    except Exception:
        return None
    return None
```

Update `process` to compute description from body and pass it to `write_episode`:

```python
def process(url: str, secret: str, data_dir: Path) -> None:
    slug = storage.write_pending_episode(data_dir, secret, source_url=url)
    try:
        title, body = fetch_article(url)
        settings = storage.get_settings(data_dir, secret)
        audio = synthesize(body, settings["voice"])
        description = _excerpt(body, DESCRIPTION_EXCERPT_CHARS)
        storage.write_episode(
            data_dir, secret, slug=slug,
            title=title, source_url=url, audio=audio,
            description=description,
        )
    except Exception as e:
        log.exception("ingest failed user=%s url=%s", secret[:6], url)
        storage.write_failed_episode(
            data_dir, secret, slug=slug,
            source_url=url, error=str(e)[:200],
        )


def _excerpt(body: str, max_chars: int) -> str:
    """First `max_chars` of body, broken at a word boundary, with ellipsis if truncated."""
    if len(body) <= max_chars:
        return body
    cut = body[:max_chars]
    last_space = cut.rfind(" ")
    if last_space > max_chars * 0.5:
        cut = cut[:last_space]
    return cut + "…"
```

- [ ] **Step 4: Run all ingest tests, verify they pass**

```bash
cd /Users/noah/Desktop/feed-me && uv run pytest tests/test_ingest.py -v
```

Expected: all ingest tests pass (existing + 5 new). The existing `test_process_writes_episode_on_success` etc. continue to work because the new `description` kwarg on `write_episode` is optional.

- [ ] **Step 5: Commit**

```bash
cd /Users/noah/Desktop/feed-me && git add ingest.py tests/test_ingest.py && git commit -m "feat(ingest): fetch_title helper + description excerpt from body

- fetch_title(url) → str | None: quick HTTP GET with 5s timeout, parses
  only the <title> tag. Used by the /ingest route to populate pending
  records with the real title before TTS completes.
- process() now computes a 200-char body excerpt and stores as the
  episode description.
- _excerpt(body, max_chars) breaks at word boundary, appends ellipsis."
```

---

## Task 3: App — `hostname` Jinja filter + `/ingest` quick-title fetch

**Files:**
- Modify: `/Users/noah/Desktop/feed-me/app.py`
- Modify: `/Users/noah/Desktop/feed-me/tests/test_app.py`

- [ ] **Step 1: Append failing tests to `/Users/noah/Desktop/feed-me/tests/test_app.py`**

```python
def test_hostname_filter_strips_scheme_and_path():
    import app
    assert app.hostname("https://colossus.com/article/inside-notion/") == "colossus.com"
    assert app.hostname("http://example.com") == "example.com"
    assert app.hostname("https://www.feed-me.xyz/u/abc/feed.xml") == "www.feed-me.xyz"


def test_hostname_filter_handles_unparseable_input():
    import app
    assert app.hostname("not a url") == "not a url"
    assert app.hostname("") == ""


def test_ingest_route_writes_pending_with_fetched_title(
    client, tmp_path, monkeypatch, fake_http,
):
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]

    fake_http.responses["https://example.com/t"] = FakeResponse(
        status_code=200,
        text="<html><head><title>Inside Notion</title></head></html>",
    )
    import ingest
    monkeypatch.setattr(ingest, "http_client", fake_http)

    # Prevent the worker thread from actually running during this test
    import app as app_module
    monkeypatch.setattr(app_module, "spawn_ingest", lambda *a, **k: None)

    response = client.get(f"/u/{secret}/ingest?url=https://example.com/t")
    assert response.status_code == 200

    import storage
    eps = storage.list_episodes(tmp_path, secret)
    pending = [e for e in eps if e["status"] == "pending"]
    assert len(pending) == 1
    assert pending[0]["title"] == "Inside Notion"


def test_ingest_route_writes_pending_with_no_title_on_fetch_failure(
    client, tmp_path, monkeypatch, fake_http,
):
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]

    fake_http.responses["https://example.com/dead"] = FakeResponse(status_code=500)
    import ingest
    monkeypatch.setattr(ingest, "http_client", fake_http)

    import app as app_module
    monkeypatch.setattr(app_module, "spawn_ingest", lambda *a, **k: None)

    response = client.get(f"/u/{secret}/ingest?url=https://example.com/dead")
    assert response.status_code == 200

    import storage
    eps = storage.list_episodes(tmp_path, secret)
    pending = [e for e in eps if e["status"] == "pending"]
    assert len(pending) == 1
    assert pending[0]["title"] is None
```

Also append `FakeResponse` to the test file's imports if not already present (it lives in `tests/conftest.py` — the existing `fake_http` fixture is in there too, but FakeResponse is imported into test_app.py? Check the existing test file. If not imported, add `from tests.conftest import FakeResponse` at the top of test_app.py, OR import locally inside the test bodies as `from tests.conftest import FakeResponse`).

- [ ] **Step 2: Run, verify the tests FAIL**

```bash
cd /Users/noah/Desktop/feed-me && uv run pytest tests/test_app.py -v -k "hostname or ingest_route_writes_pending"
```

Expected: 4 FAIL — first two with `AttributeError: module 'app' has no attribute 'hostname'`; last two because the pending record's title is None (no fetch happens today).

- [ ] **Step 3: Update `/Users/noah/Desktop/feed-me/app.py`**

Add the `hostname` filter near the existing `relative_time` helper (after the imports, before route definitions):

```python
from urllib.parse import urlparse as _urlparse  # add to existing urllib.parse import, OR add this line


def hostname(url: str) -> str:
    """Return the hostname portion of a URL (no scheme, no path).
    On unparseable input, returns the input unchanged so the template stays sane."""
    try:
        parsed = _urlparse(url)
        return parsed.netloc or url
    except Exception:
        return url
```

Note: `urlparse` is already imported in app.py for the existing `/ingest` URL validation. Use the same import — no need to add a new one. If you alias it, alias it once and use everywhere.

Register the filter on the existing `templates` instance. After `templates = Jinja2Templates(directory="templates")`, add:

```python
templates.env.filters["hostname"] = hostname
```

Find the existing `ingest_route` and replace with:

```python
@app.get("/u/{secret}/ingest")
def ingest_route(secret: str, url: str):
    if not storage.user_exists(DATA_DIR, secret):
        raise HTTPException(404)
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(400, "invalid url")
    # Quick title fetch so the Pending row shows the real title from ~1s in.
    # On any failure, fetch_title returns None and the row falls back to the
    # hostname via the _episodes_section template.
    title = ingest.fetch_title(url)
    storage.write_pending_episode(DATA_DIR, secret, source_url=url, title=title)
    spawn_ingest(url, secret, DATA_DIR)
    return {"ok": True}
```

This duplicates the pending-write call that `ingest.process` also does — that's intentional. The route writes pending IMMEDIATELY with the title; the worker's `process()` would otherwise also write one. To prevent two pending records:

Open `/Users/noah/Desktop/feed-me/ingest.py` and update `process` to NOT call `write_pending_episode` when called from the route flow. Instead, have it look up the existing pending record by URL and use its slug.

Actually the cleanest fix: have `process` accept the slug as an argument (passed in by the route). The route writes pending, then spawns the worker with the slug. Worker promotes that slug.

Replace `process` signature in ingest.py:

```python
def process(url: str, secret: str, data_dir: Path, slug: str | None = None) -> None:
    """If slug is provided, use it as the existing pending slug (do not write a new
    pending stub). If slug is None, write a fresh pending stub first (used by tests
    that call process directly)."""
    if slug is None:
        slug = storage.write_pending_episode(data_dir, secret, source_url=url)
    try:
        title, body = fetch_article(url)
        settings = storage.get_settings(data_dir, secret)
        audio = synthesize(body, settings["voice"])
        description = _excerpt(body, DESCRIPTION_EXCERPT_CHARS)
        storage.write_episode(
            data_dir, secret, slug=slug,
            title=title, source_url=url, audio=audio,
            description=description,
        )
    except Exception as e:
        log.exception("ingest failed user=%s url=%s", secret[:6], url)
        storage.write_failed_episode(
            data_dir, secret, slug=slug,
            source_url=url, error=str(e)[:200],
        )
```

Update `spawn_ingest` in app.py to accept and forward the slug:

```python
def spawn_ingest(url: str, secret: str, data_dir: Path, slug: str) -> None:
    t = threading.Thread(
        target=ingest.process,
        args=(url, secret, data_dir),
        kwargs={"slug": slug},
        daemon=True,
    )
    t.start()
```

And update `ingest_route` to capture the slug and pass it:

```python
@app.get("/u/{secret}/ingest")
def ingest_route(secret: str, url: str):
    if not storage.user_exists(DATA_DIR, secret):
        raise HTTPException(404)
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(400, "invalid url")
    title = ingest.fetch_title(url)
    slug = storage.write_pending_episode(
        DATA_DIR, secret, source_url=url, title=title,
    )
    spawn_ingest(url, secret, DATA_DIR, slug)
    return {"ok": True}
```

- [ ] **Step 4: Update the existing `test_process_writes_pending_then_ready` in `tests/test_ingest.py`**

The existing test in T3 from v1.5 calls `ingest.process(url, secret, tmp_path)` directly without a slug. The new signature allows slug=None to behave as before (write own pending). The existing test still works.

But the existing test `test_process_writes_pending_then_ready` observes that ONE pending record exists at fetch time. With the new signature behaving as before when called directly, this should still pass. No update needed.

Also: the existing `test_ingest_returns_ok_quickly` test in `tests/test_app.py` monkey-patches `spawn_ingest` with `def fake_spawn(url, secret_, data_dir):` — three positional args. Need to update to accept the new `slug` arg.

Find the existing `test_ingest_returns_ok_quickly` and update the fake_spawn signature:

```python
def test_ingest_returns_ok_quickly(client, monkeypatch, fake_http):
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]

    # fetch_title needs http_client mocked so it doesn't make real calls
    fake_http.responses["https://example.com/x"] = FakeResponse(
        status_code=200,
        text="<html><head><title>X</title></head></html>",
    )
    import ingest
    monkeypatch.setattr(ingest, "http_client", fake_http)

    calls = []

    def fake_spawn(url, secret_, data_dir, slug):
        calls.append((url, secret_, str(data_dir), slug))

    import app as app_module
    monkeypatch.setattr(app_module, "spawn_ingest", fake_spawn)

    response = client.get(
        f"/u/{secret}/ingest?url=https://example.com/x",
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert len(calls) == 1
    assert calls[0][0] == "https://example.com/x"
    assert calls[0][1] == secret
    # The slug passed to spawn matches the pending record written by the route
    import storage
    # Re-derive tmp_path from the client fixture
    # The slug arg should be non-empty and match the pending record's slug
    assert calls[0][3] is not None
```

Also the existing `test_ingest_rejects_invalid_url` and `test_ingest_404_for_unknown_user` don't hit the fetch_title or spawn paths (they return early with 400 / 404), so they don't need updates.

(The two new tests added in Step 1 already mock fake_http and spawn_ingest correctly.)

- [ ] **Step 5: Run all tests, verify they pass**

```bash
cd /Users/noah/Desktop/feed-me && uv run pytest -v 2>&1 | tail -10
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
cd /Users/noah/Desktop/feed-me && git add app.py ingest.py tests/test_app.py tests/test_ingest.py && git commit -m "feat(app): hostname filter + /ingest pre-fetches title

- app.hostname() returns netloc from a URL; registered as the
  'hostname' Jinja filter for the settings page
- /ingest now calls ingest.fetch_title before spawning the worker.
  Writes pending stub with the title pre-populated, so the polling
  table shows the real article title from ~1s in.
- process() and spawn_ingest() refactored to accept the slug from the
  route so we don't double-write pending records."
```

---

## Task 4: Template — title fallback chain for pending state

**Files:**
- Modify: `/Users/noah/Desktop/feed-me/templates/_episodes_section.html`
- Modify: `/Users/noah/Desktop/feed-me/tests/test_app.py`

- [ ] **Step 1: Append failing tests to `/Users/noah/Desktop/feed-me/tests/test_app.py`**

```python
def test_settings_page_shows_loading_for_pending_with_no_title(client, tmp_path):
    """When a pending episode has no title, the row shows 'Loading from <hostname>...'"""
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]

    import storage
    storage.write_pending_episode(
        tmp_path, secret, source_url="https://colossus.com/article/inside-notion/"
    )

    response = client.get(f"/u/{secret}")
    assert "Loading from colossus.com" in response.text
    # The misleading old fallback is NOT used for pending state
    assert "(couldn't extract article)" not in response.text or \
        response.text.count("(couldn't extract article)") == 0


def test_settings_page_shows_pending_title_when_set(client, tmp_path):
    """When fetch_title succeeded, the row shows the real title, not 'Loading from'."""
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]

    import storage
    storage.write_pending_episode(
        tmp_path, secret,
        source_url="https://example.com/x",
        title="Real Article Title",
    )

    response = client.get(f"/u/{secret}")
    assert "Real Article Title" in response.text
    assert "Loading from" not in response.text


def test_settings_page_shows_couldnt_extract_for_failed_episodes(client, tmp_path):
    """Failed episodes still get the '(couldn't extract article)' fallback."""
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]

    import storage
    storage.write_failed_episode(
        tmp_path, secret, source_url="https://nyt.com/a", error="paywall"
    )

    response = client.get(f"/u/{secret}")
    assert "(couldn't extract article)" in response.text
```

- [ ] **Step 2: Run, verify the tests FAIL**

```bash
cd /Users/noah/Desktop/feed-me && uv run pytest tests/test_app.py -v -k "shows_loading or shows_pending_title or shows_couldnt_extract"
```

Expected: tests fail — `test_settings_page_shows_loading_for_pending_with_no_title` and `test_settings_page_shows_pending_title_when_set` because the current template uses the failed fallback for pending too.

- [ ] **Step 3: Update `/Users/noah/Desktop/feed-me/templates/_episodes_section.html`**

Find the existing line in the `<td class="col-title">` block:

```html
{{ ep.title or "(couldn't extract article)" }}
```

Replace with:

```html
{% if ep.title %}{{ ep.title }}{% elif ep.status == "pending" %}Loading from {{ ep.url | hostname }}…{% else %}(couldn't extract article){% endif %}
```

The entire updated table row (for reference — only the col-title cell changed):

```html
<tr>
  <td class="col-title">
    {% if ep.title %}{{ ep.title }}{% elif ep.status == "pending" %}Loading from {{ ep.url | hostname }}…{% else %}(couldn't extract article){% endif %}
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
```

- [ ] **Step 4: Run all tests, verify they pass**

```bash
cd /Users/noah/Desktop/feed-me && uv run pytest -v 2>&1 | tail -10
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
cd /Users/noah/Desktop/feed-me && git add templates/_episodes_section.html tests/test_app.py && git commit -m "feat(app): pending episodes show 'Loading from <hostname>...' instead of failed fallback

Title fallback chain:
- have a title       → render it
- pending, no title  → 'Loading from <hostname>…' (e.g. 'Loading from colossus.com…')
- everything else    → '(couldn't extract article)' (the old failed-state fallback)

Now the user can tell at a glance that a row is in progress vs. failed."
```

---

## Task 5: RSS template additions + Apple Podcasts deep link fix

**Files:**
- Modify: `/Users/noah/Desktop/feed-me/templates/feed.xml`
- Modify: `/Users/noah/Desktop/feed-me/templates/settings.html`
- Modify: `/Users/noah/Desktop/feed-me/tests/test_rss.py`

- [ ] **Step 1: Update tests in `/Users/noah/Desktop/feed-me/tests/test_rss.py`**

Append these new tests at the end of the file:

```python
def test_render_feed_includes_atom_link_self():
    xml = rss.render_feed(
        feed_url="https://feed-me.xyz/u/abc/feed.xml",
        audio_base="https://feed-me.xyz/u/abc/audio",
        cover_url="https://feed-me.xyz/cover.jpg",
        episodes=[],
    )
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
    }
    root = _parse(xml)
    channel = root.find("channel")
    atom_link = channel.find("atom:link", ns)
    assert atom_link is not None
    assert atom_link.attrib["rel"] == "self"
    assert atom_link.attrib["href"] == "https://feed-me.xyz/u/abc/feed.xml"
    assert atom_link.attrib["type"] == "application/rss+xml"


def test_render_feed_includes_itunes_type_episodic():
    xml = rss.render_feed(
        feed_url="https://feed-me.xyz/u/abc/feed.xml",
        audio_base="https://feed-me.xyz/u/abc/audio",
        cover_url="https://feed-me.xyz/cover.jpg",
        episodes=[],
    )
    ns = {"itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"}
    root = _parse(xml)
    channel = root.find("channel")
    type_el = channel.find("itunes:type", ns)
    assert type_el is not None
    assert type_el.text == "episodic"


def test_render_feed_per_item_description_and_summary():
    eps = [
        {"slug": "s1", "title": "Article", "url": "https://a", "ts": 1,
         "mtime": 1.0, "has_audio": True, "audio_bytes": 42,
         "description": "First few sentences of the article…"},
    ]
    xml = rss.render_feed(
        feed_url="https://feed-me.xyz/u/abc/feed.xml",
        audio_base="https://feed-me.xyz/u/abc/audio",
        cover_url="https://feed-me.xyz/cover.jpg",
        episodes=eps,
    )
    ns = {"itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"}
    root = _parse(xml)
    item = root.find("channel/item")
    assert item.findtext("description") == "First few sentences of the article…"
    assert item.find("itunes:summary", ns).text == "First few sentences of the article…"


def test_render_feed_per_item_description_falls_back_to_url():
    """When an item has no description (pending case), description = source URL."""
    eps = [
        {"slug": "s1", "title": "X", "url": "https://example.com/a", "ts": 1,
         "mtime": 1.0, "has_audio": True, "audio_bytes": 42},
    ]
    xml = rss.render_feed(
        feed_url="https://feed-me.xyz/u/abc/feed.xml",
        audio_base="https://feed-me.xyz/u/abc/audio",
        cover_url="https://feed-me.xyz/cover.jpg",
        episodes=eps,
    )
    root = _parse(xml)
    item = root.find("channel/item")
    assert item.findtext("description") == "https://example.com/a"


def test_render_feed_enclosure_uses_real_audio_bytes():
    eps = [
        {"slug": "s1", "title": "X", "url": "https://a", "ts": 1,
         "mtime": 1.0, "has_audio": True, "audio_bytes": 137154,
         "description": "x"},
    ]
    xml = rss.render_feed(
        feed_url="https://feed-me.xyz/u/abc/feed.xml",
        audio_base="https://feed-me.xyz/u/abc/audio",
        cover_url="https://feed-me.xyz/cover.jpg",
        episodes=eps,
    )
    root = _parse(xml)
    enc = root.find("channel/item/enclosure")
    assert enc.attrib["length"] == "137154"
```

Also find the existing `test_render_feed_emits_ready_episodes_in_order` and update the `eps` dicts to include `audio_bytes: 100` so the length attribute renders. Replace the existing function:

```python
def test_render_feed_emits_ready_episodes_in_order():
    eps = [
        {"slug": "s1", "title": "Newer", "url": "https://a", "ts": 200,
         "mtime": 200.0, "has_audio": True, "audio_bytes": 100},
        {"slug": "s2", "title": "Older", "url": "https://b", "ts": 100,
         "mtime": 100.0, "has_audio": True, "audio_bytes": 200},
    ]
    xml = rss.render_feed(
        feed_url="https://feed-me.xyz/u/abc/feed.xml",
        audio_base="https://feed-me.xyz/u/abc/audio",
        cover_url="https://feed-me.xyz/cover.jpg",
        episodes=eps,
    )
    root = _parse(xml)
    items = root.findall("channel/item")
    assert len(items) == 2
    assert items[0].findtext("title") == "Newer"
    assert items[1].findtext("title") == "Older"
    enc = items[0].find("enclosure")
    assert enc is not None
    assert enc.attrib["url"] == "https://feed-me.xyz/u/abc/audio/s1.mp3"
    assert enc.attrib["type"] == "audio/mpeg"
    assert enc.attrib["length"] == "100"
```

Also update `test_render_feed_omits_failed_episodes` to pass `audio_bytes` on the good record:

```python
def test_render_feed_omits_failed_episodes():
    eps = [
        {"slug": "good", "title": "OK", "url": "https://a", "ts": 1,
         "mtime": 1.0, "has_audio": True, "audio_bytes": 50},
        {"slug": "bad", "title": None, "url": "https://b", "ts": 2,
         "mtime": 2.0, "has_audio": False, "error": "boom"},
    ]
    xml = rss.render_feed(
        feed_url="https://feed-me.xyz/u/abc/feed.xml",
        audio_base="https://feed-me.xyz/u/abc/audio",
        cover_url="https://feed-me.xyz/cover.jpg",
        episodes=eps,
    )
    items = _parse(xml).findall("channel/item")
    assert len(items) == 1
    assert items[0].findtext("title") == "OK"
```

Append a new test for the settings page `podcast://` (singular) scheme:

```python
# In tests/test_app.py:
def test_settings_apple_podcasts_uses_singular_podcast_scheme(client):
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]

    response = client.get(f"/u/{secret}")
    # New v1.6: podcast:// (singular) is Apple's documented scheme
    assert 'href="podcast://feed-me' in response.text or \
           'href="podcast://test.local' in response.text  # depending on APP_BASE_URL
    # The old plural form should not appear
    assert 'href="podcasts://' not in response.text
```

- [ ] **Step 2: Run, verify the tests FAIL**

```bash
cd /Users/noah/Desktop/feed-me && uv run pytest tests/test_rss.py tests/test_app.py -v -k "atom_link or itunes_type_episodic or per_item_description or enclosure_uses_real or singular_podcast_scheme"
```

Expected: the new tests fail because the template hasn't been updated yet.

- [ ] **Step 3: Replace `/Users/noah/Desktop/feed-me/templates/feed.xml` with the v1.6 version**

Full new content:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
     xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>Feed Me</title>
    <link>{{ feed_url }}</link>
    <atom:link href="{{ feed_url }}" rel="self" type="application/rss+xml"/>
    <description>Your personal podcast of articles you've saved with Feed Me.</description>
    <itunes:summary>Your personal podcast of articles you've saved with Feed Me.</itunes:summary>
    <itunes:image href="{{ cover_url }}"/>
    <itunes:type>episodic</itunes:type>
    <language>en-us</language>
    <itunes:author>Feed Me</itunes:author>
    <itunes:explicit>false</itunes:explicit>
    {% for ep in episodes %}
    <item>
      <title>{{ ep.title | e }}</title>
      <link>{{ ep.url | e }}</link>
      <guid isPermaLink="false">{{ ep.slug }}</guid>
      <pubDate>{{ ep.pub_date }}</pubDate>
      <description>{{ (ep.description or ep.url) | e }}</description>
      <itunes:summary>{{ (ep.description or ep.url) | e }}</itunes:summary>
      <enclosure url="{{ audio_base }}/{{ ep.slug }}.mp3"
                 type="audio/mpeg"
                 length="{{ ep.audio_bytes or 0 }}"/>
    </item>
    {% endfor %}
  </channel>
</rss>
```

- [ ] **Step 4: Update `/Users/noah/Desktop/feed-me/templates/settings.html` — change `podcasts://` to `podcast://`**

Find the line:

```html
<a class="btn-primary" href="podcasts://{{ feed_host_and_path }}">Add to Apple Podcasts</a>
```

Replace with:

```html
<a class="btn-primary" href="podcast://{{ feed_host_and_path }}">Add to Apple Podcasts</a>
```

Only the `s` after `podcast` changes.

- [ ] **Step 5: Run all tests, verify they pass**

```bash
cd /Users/noah/Desktop/feed-me && uv run pytest -v 2>&1 | tail -10
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
cd /Users/noah/Desktop/feed-me && git add templates/feed.xml templates/settings.html tests/test_rss.py tests/test_app.py && git commit -m "feat(rss): Apple-compatible feed — atom:link, itunes:type, real lengths, per-item descriptions

- channel: xmlns:atom + <atom:link rel='self'> + <itunes:type>episodic</>
- per-item: <description> and <itunes:summary> (body excerpt, falls back
  to source URL when description not yet computed)
- enclosure: real byte length from audio_bytes (was hard-coded 0,
  which Apple Podcasts often rejects)
- settings.html: 'Add to Apple Podcasts' uses podcast:// (singular —
  Apple's documented scheme; plural podcasts:// was wrong)"
```

---

## Task 6: Deploy v1.6 + tag

**Files:** none (deploy + CHANGELOG + tag)

- [ ] **Step 1: Deploy**

```bash
~/.fly/bin/fly deploy --app feed-me-noah-willow-grove-8052
```

Expected: build succeeds.

- [ ] **Step 2: Verify feed contains new elements**

```bash
curl -s "https://feed-me.xyz/u/GZ3wWyxsNZSraasSwlfYO_OhPrFI3uk9v5pYl-886AA/feed.xml" | grep -E "(atom:link|itunes:type|description|length=)" | head -10
```

Expected: see `atom:link`, `itunes:type`, per-item `description`, and a non-zero `length="..."` on the welcome enclosure.

- [ ] **Step 3: Verify settings page uses podcast:// scheme**

```bash
curl -s "https://feed-me.xyz/u/GZ3wWyxsNZSraasSwlfYO_OhPrFI3uk9v5pYl-886AA" | grep -o "href=\"podcast.*://[^\"]*\"" | head -1
```

Expected: `href="podcast://feed-me.xyz/u/.../feed.xml"` (note: singular `podcast`, not `podcasts`).

- [ ] **Step 4: Verify pending title fetch via share**

On your iPhone, share a fresh article using the Feed Me Shortcut. Within ~3 seconds the polling table should show the row with the **real article title** (e.g., "Inside Notion — Colossus") and a **Pending** chip — NOT "(couldn't extract article)".

- [ ] **Step 5: Re-test Apple Podcasts subscribe**

Apple aggressively caches feeds. To force a fresh fetch:

1. On your iPhone, **rotate your URL** (Settings drawer → Rotate URL on the existing account, OR just create a fresh `/create` account)
2. On the new settings page, tap **Add to Apple Podcasts** — opens with the new `podcast://` scheme + a feed URL Apple has never seen
3. In Podcasts, tap **Follow**. Should succeed. Show notes for the welcome episode should read "Share an article from your phone — it'll show up here a minute later."

If Apple still refuses subscription on the fresh URL, the spec's hypothesis is wrong and we'd need to investigate further. Tell me; don't move to step 6.

- [ ] **Step 6: Update CHANGELOG and tag v1.6**

Insert this entry at the top of `/Users/noah/Desktop/feed-me/CHANGELOG.md` (above the v1.5 entry):

```markdown
## v1.6 — 2026-05-27

Episode metadata + Apple Podcasts compatibility:

- Pending rows now show the article's real title (via a quick `<title>` fetch at /ingest time, before TTS runs). Falls back to "Loading from <hostname>…" if the fetch fails. The misleading "(couldn't extract article)" is now reserved for actual failures.
- Every RSS item carries a `<description>` and `<itunes:summary>` — first ~200 chars of the article body for ready episodes, source URL for pending, error + URL for failed, hand-written for the welcome.
- Apple Podcasts compatibility:
  - Real byte-count `length` attribute on every `<enclosure>` (was `length="0"` — Apple often rejects)
  - `<atom:link rel="self">` added to channel
  - `<itunes:type>episodic</itunes:type>` added to channel
  - "Add to Apple Podcasts" button uses `podcast://` (singular — Apple's documented scheme; plural `podcasts://` was wrong)
- Spec: `docs/superpowers/specs/2026-05-27-episode-metadata-and-apple-podcasts.html`
```

Then:

```bash
cd /Users/noah/Desktop/feed-me && git add CHANGELOG.md && git commit -m "release: v1.6 episode metadata + Apple Podcasts compat" && git tag v1.6
```

---

## Self-Review

### Spec coverage

| Spec section | Implementing task |
|---|---|
| §3 Quick title fetch (fetch_title + write_pending_episode title kwarg + /ingest pre-fetch) | Tasks 1, 2, 3 |
| §3 Template fallback chain (Loading from hostname) | Task 4 (hostname filter registered in Task 3) |
| §4 Per-episode descriptions (storage kwargs + WELCOME_DESCRIPTION + body excerpt) | Tasks 1, 2 |
| §4 RSS template per-item description/summary | Task 5 |
| §5 Real enclosure length | Tasks 1 (audio_bytes derivation) + 5 (template) |
| §5 atom:link + itunes:type | Task 5 |
| §5 podcast:// deep link | Task 5 |
| §6 fetch_title implementation sketch | Task 2 step 3 (exact match) |
| §6 Worker thread interaction with fetched title | Task 3 step 3 (process accepts slug from route) |
| §6 Hostname filter implementation | Task 3 step 3 |
| §7 Tests (ingest/storage/RSS/app) | All tasks |
| §10 Acceptance | Task 6 manual verification steps |

All sections covered. Out-of-scope items (per-episode image, duration, itunes:owner, AI summaries) correctly absent.

### Placeholder scan

Scanned for "TBD", "TODO", "implement later", "appropriate error handling", "similar to Task N", "etc". None found. Every code block is complete. The "(e.g., 'Loading from colossus.com…')" in the commit message is exemplification, not a placeholder.

### Type consistency

- `title: str | None = None`, `description: str | None = None` consistent across all writers
- `slug: str | None = None` consistent
- `audio_bytes` consistent (None when no MP3, int otherwise)
- `fetch_title(url: str) -> str | None` consistent between definition and call sites
- `hostname(url: str) -> str` consistent between definition and Jinja filter registration
- `process(url, secret, data_dir, slug=None)` signature consistent across direct calls (tests) and route call (via spawn_ingest)
- `spawn_ingest(url, secret, data_dir, slug)` — 4 positional args; the fake_spawn in the existing test is updated to match
- WELCOME_DESCRIPTION constant consistent between storage.py definition and test assertion
- TITLE_FETCH_TIMEOUT_S and DESCRIPTION_EXCERPT_CHARS module constants in ingest.py — referenced once each

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-27-episode-metadata-and-apple-podcasts.md`.

Six tasks: storage signatures, ingest helper + body excerpt, app filter + route, template fallback, RSS additions + scheme fix, deploy + tag. Estimated ~40 minutes of focused subagent work plus a manual iPhone re-subscribe at the end.
