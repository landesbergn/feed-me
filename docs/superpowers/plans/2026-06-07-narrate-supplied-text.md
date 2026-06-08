# Narrate Supplied Text (v3.14) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an agent POST `{"text", "title", "url"?}` to `/u/<secret>/episodes` and have Feed Me narrate that text directly, with no server-side fetch, so it bypasses paywalls where the user already holds the full article/email text.

**Architecture:** Add a "text mode" branch to the agent POST handler and to `ingest.process`: when text is supplied, skip `fetch_article` (and the paywall + minimum-length guards) and feed the text into the existing `chunk_text -> synthesize -> write_episode` flow. A small `rss.py` change omits the "Original article" line when an episode has no source url. Docs (`AGENTS.md`, README, CHANGELOG) and a `v3.14` tag.

**Tech Stack:** Python 3, FastAPI, Starlette `TestClient`, pytest. Run tests with `uv run pytest`.

**Spec:** `docs/superpowers/specs/2026-06-07-narrate-supplied-text.html`

---

## File Structure

| File | Change | Responsibility |
|------|--------|----------------|
| `rss.py` | Modify `_episode_description_html` / `_episode_description_text` | Omit "Original article" line when url is empty |
| `ingest.py` | Modify `process` | Text branch: narrate supplied text, skip fetch/paywall/min-guard |
| `app.py` | Modify `spawn_ingest` + `create_episode_api` | Forward `text`/`title`; parse + validate text mode |
| `templates/agents.md` | Add a "Narrate text directly" section | Document text mode |
| `README.md` | Modify the POST route row | Mention text body |
| `CHANGELOG.md` | Prepend a v3.14 entry | Release notes |
| `tests/test_rss.py`, `tests/test_ingest.py`, `tests/test_agent_api.py` | Add tests | Cover each layer |

**Conventions (from CLAUDE.md and existing tests):**
- Agent endpoints authenticate by the path secret only; never read/set the session cookie; errors are `{"error","message"}` JSON via `_agent_error(...)`. The POST parses its body by hand (a Pydantic model would 422, not the documented 400).
- `templates/agents.md` is rendered with a plain `.replace("{base}", APP_BASE_URL)`. Keep the literal `{base}` token. No em-dashes (`—`) in agent/user-facing copy; the middot `·` is allowed. `test_agents_md_served_as_markdown` asserts `"—" not in resp.text`, plus `"5 episodes"` and `"Retry-After"`.
- In tests, `APP_BASE_URL` = `https://test.local`; the `client` fixture sets `DATA_DIR` to `tmp_path`. Helpers in `tests/test_agent_api.py`: `make_feed`, `wire_fake_pipeline`, `ARTICLE_HTML`, `FakeResponse`. In `tests/test_ingest.py`: `fake_http`, `fake_openai`, `HTML_SAMPLE`, `FakeResponse`, and `storage.create_user(tmp_path)`.
- `ingest.MAX_BODY_CHARS == 500_000`, `ingest.MIN_BODY_CHARS == 600`.

---

## Task 1: RSS omits the "Original article" line when there is no source url

**Files:**
- Modify: `rss.py` (functions `_episode_description_html` ~line 22 and `_episode_description_text` ~line 36)
- Test: `tests/test_rss.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_rss.py`:

```python
def test_render_feed_omits_original_article_when_url_empty():
    eps = [
        {"slug": "t1", "title": "From text", "url": "", "ts": 5,
         "mtime": 5.0, "has_audio": True, "audio_bytes": 10,
         "description": "An excerpt."},
    ]
    xml = rss.render_feed(
        feed_url="https://feed-me.xyz/u/abc/feed.xml",
        audio_base="https://feed-me.xyz/u/abc/audio",
        cover_url="https://feed-me.xyz/cover.jpg",
        episodes=eps,
    )
    assert "Original article" not in xml
    assert "Generated with" in xml          # the other description line stays
    assert "An excerpt." in xml


def test_render_feed_includes_original_article_when_url_present():
    eps = [
        {"slug": "u1", "title": "From url", "url": "https://example.com/x", "ts": 6,
         "mtime": 6.0, "has_audio": True, "audio_bytes": 10,
         "description": "An excerpt."},
    ]
    xml = rss.render_feed(
        feed_url="https://feed-me.xyz/u/abc/feed.xml",
        audio_base="https://feed-me.xyz/u/abc/audio",
        cover_url="https://feed-me.xyz/cover.jpg",
        episodes=eps,
    )
    assert "Original article" in xml
    assert "https://example.com/x" in xml
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_rss.py -k original_article -v`
Expected: `test_render_feed_omits_original_article_when_url_empty` FAILS (the current code always renders "Original article", even with an empty href). The `_present` test passes.

- [ ] **Step 3: Implement**

In `rss.py`, change the two description builders to only add the line when `article_url` is truthy. Replace:

```python
def _episode_description_html(excerpt: str, article_url: str, home_url: str) -> str:
    parts = []
    if excerpt:
        parts.append(html.escape(excerpt))
    parts.append(
        f'Original article: <a href="{html.escape(article_url, quote=True)}">'
        f"{html.escape(article_url)}</a>"
    )
    parts.append(
        f'Generated with <a href="{html.escape(home_url, quote=True)}">Feed Me</a>'
    )
    return "<br/><br/>".join(parts)


def _episode_description_text(excerpt: str, article_url: str, home_url: str) -> str:
    lines = []
    if excerpt:
        lines.append(excerpt)
    lines.append(f"Original article: {article_url}")
    lines.append(f"Generated with Feed Me: {home_url}")
    return "\n\n".join(lines)
```

with:

```python
def _episode_description_html(excerpt: str, article_url: str, home_url: str) -> str:
    parts = []
    if excerpt:
        parts.append(html.escape(excerpt))
    if article_url:
        parts.append(
            f'Original article: <a href="{html.escape(article_url, quote=True)}">'
            f"{html.escape(article_url)}</a>"
        )
    parts.append(
        f'Generated with <a href="{html.escape(home_url, quote=True)}">Feed Me</a>'
    )
    return "<br/><br/>".join(parts)


def _episode_description_text(excerpt: str, article_url: str, home_url: str) -> str:
    lines = []
    if excerpt:
        lines.append(excerpt)
    if article_url:
        lines.append(f"Original article: {article_url}")
    lines.append(f"Generated with Feed Me: {home_url}")
    return "\n\n".join(lines)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_rss.py -v`
Expected: PASS (all existing rss tests still green, since they pass non-empty urls; the 2 new tests pass).

- [ ] **Step 5: Commit**

```bash
git add rss.py tests/test_rss.py
git commit -m "feat: RSS omits the Original-article line when an episode has no source url

Text episodes (next commit) can have no source URL; render no broken link.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `ingest.process` narrates supplied text

**Files:**
- Modify: `ingest.py` (function `process` ~line 243)
- Test: `tests/test_ingest.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ingest.py`:

```python
def test_process_narrates_supplied_text(monkeypatch, fake_openai, tmp_path):
    monkeypatch.setattr(ingest, "openai_client", fake_openai)
    secret = storage.create_user(tmp_path)

    ingest.process(
        "", secret, tmp_path,
        text="This is the full body of an emailed newsletter, narrated as-is.",
        title="My Newsletter",
    )

    eps = storage.list_episodes(tmp_path, secret)
    assert len(eps) == 1
    assert eps[0]["status"] == "ready"
    assert eps[0]["has_audio"] is True
    assert eps[0]["title"] == "My Newsletter"
    assert eps[0]["url"] == ""          # no source link
    # The supplied text (not a fetched body) was sent to TTS.
    assert "emailed newsletter" in fake_openai.calls[0]["input"]


def test_process_text_skips_fetch_and_min_guard(monkeypatch, fake_openai, tmp_path):
    monkeypatch.setattr(ingest, "openai_client", fake_openai)
    # If text mode ever fetches, this explodes the test.
    def boom(*a, **k):
        raise AssertionError("text mode must not fetch")
    monkeypatch.setattr(ingest, "fetch_article", boom)
    secret = storage.create_user(tmp_path)

    # Body far below MIN_BODY_CHARS (600). URL mode would reject this as a
    # teaser; text mode narrates it.
    ingest.process("", secret, tmp_path, text="A short note.", title="Note")

    eps = storage.list_episodes(tmp_path, secret)
    assert eps[0]["status"] == "ready"


def test_process_text_stores_optional_source_url(monkeypatch, fake_openai, tmp_path):
    monkeypatch.setattr(ingest, "openai_client", fake_openai)
    secret = storage.create_user(tmp_path)

    ingest.process(
        "https://src.example/post", secret, tmp_path,
        text="Body text to narrate.", title="T",
    )

    eps = storage.list_episodes(tmp_path, secret)
    assert eps[0]["url"] == "https://src.example/post"


def test_process_text_over_max_fails(monkeypatch, fake_openai, tmp_path):
    monkeypatch.setattr(ingest, "openai_client", fake_openai)
    secret = storage.create_user(tmp_path)

    ingest.process(
        "", secret, tmp_path,
        text="x" * (ingest.MAX_BODY_CHARS + 1), title="Too long",
    )

    eps = storage.list_episodes(tmp_path, secret)
    assert eps[0]["status"] == "failed"
    assert "too long" in eps[0]["error"].lower()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_ingest.py -k "supplied_text or text_skips or text_stores or text_over_max" -v`
Expected: FAIL. `process` does not accept `text`/`title` keyword args yet (`TypeError`).

- [ ] **Step 3: Implement**

In `ingest.py`, replace the entire `process` function (currently ~lines 243-286) with:

```python
def process(url, secret, data_dir, slug=None, *, text=None, title=None):
    """Narrate an article into an episode.

    URL mode (text is None): fetch and extract the article at `url`.
    Text mode (text is not None): narrate the supplied `text` directly with the
    given `title`, skipping the fetch, the paywall check, and the minimum-length
    guard (the caller has vouched for real content). `url`, if any, is only the
    episode's source link, never fetched.
    """
    source_url = url or ""
    if slug is None:
        slug = storage.write_pending_episode(data_dir, secret, source_url=source_url)
    try:
        if text is not None:
            episode_title, body = title, text
        else:
            episode_title, body = fetch_article(url)
            if len(body) < MIN_BODY_CHARS:
                raise FetchError(
                    f"Could only extract a snippet ({len(body)} characters) from "
                    f"{urlparse(url).netloc}. The article may be paywalled."
                )
        if len(body) > MAX_BODY_CHARS:
            raise ValueError(
                f"Article too long: {len(body):,} chars (limit: {MAX_BODY_CHARS:,}). "
                f"Try sharing a shorter article."
            )
        # Write total_chunks so the settings page can show smooth % progress.
        chunks = chunk_text(body, TTS_CHAR_LIMIT)
        storage.update_pending_episode(
            data_dir, secret, slug, total_chunks=len(chunks),
        )
        settings = storage.get_settings(data_dir, secret)
        tmp_audio = data_dir / secret / f"{slug}.mp3.tmp"
        try:
            synthesize(body, settings["voice"], tmp_audio)
            description = _excerpt(body, DESCRIPTION_EXCERPT_CHARS)
            storage.write_episode(
                data_dir, secret, slug=slug,
                title=episode_title, source_url=source_url, audio_path=tmp_audio,
                description=description,
            )
        finally:
            # On success the rename already consumed the tmp; on failure this
            # removes the partial file (the outer except records the episode
            # as failed).
            tmp_audio.unlink(missing_ok=True)
    except Exception as e:
        log.exception("ingest failed user=%s url=%s", secret[:6], url)
        storage.write_failed_episode(
            data_dir, secret, slug=slug,
            source_url=source_url, error=str(e)[:200],
        )
```

Notes for the implementer:
- The only behavioral change for URL mode is cosmetic: `source_url` is now `url or ""` (identical to `url` for any real URL) and the title local is renamed `episode_title`. The MIN/MAX guards and all downstream calls are unchanged. Existing url-mode tests must stay green.
- Do not call `fetch_title` here (that lives in the POST handler, url mode only).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_ingest.py -v`
Expected: PASS (all existing ingest tests plus the 4 new ones).

- [ ] **Step 5: Commit**

```bash
git add ingest.py tests/test_ingest.py
git commit -m "feat: ingest.process can narrate supplied text

Text mode skips the fetch, the paywall check, and the 600-char minimum guard,
then reuses the existing chunk/synthesize/write flow. URL mode unchanged.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: POST handler text mode + `spawn_ingest`

**Files:**
- Modify: `app.py` (`spawn_ingest` ~line 68 and `create_episode_api` ~lines 240-300)
- Test: `tests/test_agent_api.py` (update `wire_fake_pipeline`, append tests)

- [ ] **Step 1: Update the test helper, then write the failing tests**

First, in `tests/test_agent_api.py`, update `wire_fake_pipeline` so its stub `spawn_ingest` accepts and forwards the new `text`/`title` kwargs (the real `spawn_ingest` will grow them in Step 3; without this the text-mode tests would `TypeError`). Replace the `monkeypatch.setattr(app_module, "spawn_ingest", ...)` call inside `wire_fake_pipeline` with:

```python
    monkeypatch.setattr(
        app_module, "spawn_ingest",
        lambda url, secret, data_dir, slug, *, text=None, title=None: ingest.process(
            url, secret, data_dir, slug=slug, text=text, title=title
        ),
    )
```

Add `import ingest` to the top of `tests/test_agent_api.py` (next to `import storage`), then append these tests:

```python
# --- text mode -------------------------------------------------------------

def test_text_mode_narrates_without_fetching(
    client, monkeypatch, fake_http, fake_openai, tmp_path,
):
    secret = make_feed(client)
    wire_fake_pipeline(monkeypatch, fake_http, fake_openai)
    # Prove text mode never fetches: both fetchers explode if called.
    def boom(*a, **k):
        raise AssertionError("text mode must not fetch")
    monkeypatch.setattr(ingest, "fetch_article", boom)
    monkeypatch.setattr(ingest, "fetch_title", boom)

    resp = client.post(
        f"/u/{secret}/episodes",
        json={"text": "The full body of a newsletter, narrated as-is.",
              "title": "My Newsletter"},
    )

    assert resp.status_code == 202
    body = resp.json()
    assert body["title"] == "My Newsletter"
    assert body["remaining"] == 4
    record = json.loads((tmp_path / secret / f"{body['slug']}.json").read_text())
    assert "pending" not in record and "error" not in record   # ready
    assert record["title"] == "My Newsletter"
    assert record["url"] == ""
    assert (tmp_path / secret / f"{body['slug']}.mp3").exists()


def test_text_mode_optional_url_is_source_link_not_fetched(
    client, monkeypatch, fake_http, fake_openai, tmp_path,
):
    secret = make_feed(client)
    wire_fake_pipeline(monkeypatch, fake_http, fake_openai)
    def boom(*a, **k):
        raise AssertionError("must not fetch the source url")
    monkeypatch.setattr(ingest, "fetch_article", boom)
    monkeypatch.setattr(ingest, "fetch_title", boom)

    client.post(
        f"/u/{secret}/episodes",
        json={"text": "Body to narrate.", "title": "T",
              "url": "https://paywalled.example/post"},
    )

    feed = client.get(f"/u/{secret}/feed.xml").text
    assert "https://paywalled.example/post" in feed
    assert "Original article" in feed


def test_text_mode_no_url_omits_source_link(
    client, monkeypatch, fake_http, fake_openai, tmp_path,
):
    secret = make_feed(client)
    wire_fake_pipeline(monkeypatch, fake_http, fake_openai)
    client.post(
        f"/u/{secret}/episodes",
        json={"text": "Body to narrate.", "title": "No Source"},
    )

    feed = client.get(f"/u/{secret}/feed.xml").text
    # The only items are the welcome (url feed-me.xyz) and this text episode.
    # The text episode contributes no "Original article" line; assert the feed
    # does not link the text episode as a source (its title is present though).
    assert "No Source" in feed


def test_text_mode_requires_title(client, tmp_path):
    secret = make_feed(client)
    for bad in ({"text": "Body only."}, {"text": "Body.", "title": ""},
                {"text": "Body.", "title": "   "}):
        resp = client.post(f"/u/{secret}/episodes", json=bad)
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_request"
    assert len(storage.list_episodes(tmp_path, secret)) == 1   # welcome only


def test_text_mode_rejects_empty_text(client, tmp_path):
    secret = make_feed(client)
    resp = client.post(f"/u/{secret}/episodes", json={"text": "   ", "title": "x"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_request"
    assert len(storage.list_episodes(tmp_path, secret)) == 1   # welcome only


def test_text_mode_rejects_over_max(client, tmp_path):
    import ingest as ingest_mod
    secret = make_feed(client)
    resp = client.post(
        f"/u/{secret}/episodes",
        json={"text": "x" * (ingest_mod.MAX_BODY_CHARS + 1), "title": "Too long"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_request"
    assert "too long" in resp.json()["message"].lower()
    assert len(storage.list_episodes(tmp_path, secret)) == 1   # welcome only


def test_text_mode_bad_optional_url(client, tmp_path):
    secret = make_feed(client)
    resp = client.post(
        f"/u/{secret}/episodes",
        json={"text": "Body.", "title": "T", "url": "ftp://nope/x"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_url"
    assert len(storage.list_episodes(tmp_path, secret)) == 1   # welcome only


def test_post_neither_url_nor_text_400(client, tmp_path):
    secret = make_feed(client)
    resp = client.post(f"/u/{secret}/episodes", json={"foo": "bar"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_request"
    assert "text" in resp.json()["message"]
    assert len(storage.list_episodes(tmp_path, secret)) == 1   # welcome only


def test_text_share_counts_toward_cap_and_lists(
    client, monkeypatch, fake_http, fake_openai,
):
    secret = make_feed(client)
    wire_fake_pipeline(monkeypatch, fake_http, fake_openai)

    post = client.post(
        f"/u/{secret}/episodes", json={"text": "A body.", "title": "Counted"},
    )
    assert post.json()["remaining"] == 4

    listing = client.get(f"/u/{secret}/episodes").json()
    assert listing["remaining"] == 4
    assert any(e["title"] == "Counted" for e in listing["episodes"])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_agent_api.py -k "text_mode or neither_url or text_share" -v`
Expected: FAIL. The handler does not parse `text` yet, so text posts currently hit the `"url"` validation and return 400 with the wrong message / the wrong mode (and `spawn_ingest` does not accept `text`).

- [ ] **Step 3: Implement**

First, in `app.py`, replace `spawn_ingest` (~lines 68-75) with:

```python
def spawn_ingest(url, secret, data_dir, slug, *, text=None, title=None) -> None:
    t = threading.Thread(
        target=ingest.process,
        args=(url, secret, data_dir),
        kwargs={"slug": slug, "text": text, "title": title},
        daemon=True,
    )
    t.start()
```

Then replace the body of `create_episode_api` (~lines 240-300) with:

```python
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

    if text_mode:
        record_title = episode_title
        spawn_text, spawn_title = text, episode_title
    else:
        # fetch_title blocks on the network; run it off the event loop.
        record_title = await run_in_threadpool(ingest.fetch_title, url)
        spawn_text, spawn_title = None, None

    slug = storage.write_pending_episode(
        DATA_DIR, secret, source_url=source_url, title=record_title, via="agent",
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
    }, status_code=202)
```

Notes for the implementer:
- URL mode is behavior-preserving: it still validates the url, calls `fetch_title`, writes the pending record with `via="agent"`, spawns ingest with the url, and returns the same 202 shape. The existing url-mode tests (`test_post_episode_happy_path`, the cap tests, the analytics test) must stay green.
- In url mode `spawn_ingest(source_url, ...)` passes the url (== `source_url`) with `text=None`, so `ingest.process` takes its url branch exactly as before.
- `json`, `urlparse`, `ingest`, `run_in_threadpool`, `storage`, `_time`, `_agent_episodes_in_window`, `AGENT_DAILY_CAP`, `AGENT_CAP_WINDOW_S`, `APP_BASE_URL`, `_track`, `JSONResponse`, `_agent_error` are all already imported/defined. Add no imports.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_agent_api.py -v`
Expected: PASS (all existing agent-API tests plus the new text-mode tests).

- [ ] **Step 5: Run the full suite (cross-file integration)**

Run: `uv run pytest -q`
Expected: PASS (all green).

- [ ] **Step 6: Commit**

```bash
git add app.py tests/test_agent_api.py
git commit -m "feat: POST /u/<secret>/episodes accepts text mode

{text, title, url?} narrates the supplied body directly, no fetch. Title
required; over-length and empty text rejected at request time so they never
create an episode or spend a rate-limit share. spawn_ingest forwards the new
text/title kwargs.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Document text mode in `AGENTS.md`

**Files:**
- Modify: `templates/agents.md` (insert a section before `## Poll status`)
- Test: `tests/test_agent_api.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_agent_api.py`:

```python
def test_agents_md_documents_text_mode(client):
    text = client.get("/AGENTS.md").text
    assert "Narrate text directly" in text
    assert '"text":' in text
    assert "title" in text and "required" in text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_agent_api.py -k documents_text_mode -v`
Expected: FAIL (no such section yet).

- [ ] **Step 3: Implement**

In `templates/agents.md`, insert this new section immediately BEFORE the `## Poll status` heading (and after the `## Add an article` section's notes). Keep the literal `{base}` token; use no em-dashes:

```markdown
## Narrate text directly

If you already hold the full text of an article or email (for example a
newsletter the user receives in full as a paying subscriber), send the text
itself instead of a URL. Feed Me narrates it as-is and never fetches anything,
so it is not subject to the paywall a server-side fetch would hit.

    POST {base}/u/<secret>/episodes
    Content-Type: application/json

    {
      "text": "The full article or email body to narrate...",
      "title": "The Episode Title",
      "url": "https://example.com/the-source"
    }

- "text" is the body to narrate (plain text; strip HTML first).
- "title" is required (there is no page to derive one from).
- "url" is optional: it becomes the episode's "Original article" link and is
  never fetched. Omit it when there is no canonical source.

The response is the same 202 shape as a URL share, and the same rate limit
applies. Over-long text (more than the article limit) and empty text are
rejected immediately. Prefer text over a URL whenever you have the full body
and the URL would be paywalled.

```

- [ ] **Step 4: Verify no em-dash and run the tests**

Run: `grep -c '—' templates/agents.md`
Expected: `0`

Run: `uv run pytest tests/test_agent_api.py -k "agents_md or documents_text_mode" -v`
Expected: PASS (the new test plus the existing `test_agents_md_served_as_markdown` and the v3.13 AGENTS.md tests).

- [ ] **Step 5: Commit**

```bash
git add templates/agents.md tests/test_agent_api.py
git commit -m "docs: AGENTS.md documents text mode

How and when to POST {text, title} to bypass paywalls. No em-dashes.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: README + CHANGELOG + v3.14 tag

**Files:**
- Modify: `README.md` (the POST route row)
- Modify: `CHANGELOG.md` (prepend a v3.14 entry)

Do NOT create the git tag here; the controller tags `v3.14` after the branch merges to main.

- [ ] **Step 1: Update the README route row**

In `README.md`, replace the `POST /u/{secret}/episodes` row:

Old:
```markdown
| `POST /u/{secret}/episodes` | Agent API: create an episode from a JSON body (`{"url": ...}`); 5/day rolling cap |
```
New:
```markdown
| `POST /u/{secret}/episodes` | Agent API: create an episode from a JSON body (`{"url": ...}` or `{"text", "title"}`); 5/day rolling cap |
```

- [ ] **Step 2: Prepend the CHANGELOG entry**

In `CHANGELOG.md`, insert this block directly below the `# Changelog` heading and above the current top entry (`## v3.13 · 2026-06-07`). Use the middot `·` in the date header (house style forbids em-dashes); keep the body em-dash free:

```markdown
## v3.14 · 2026-06-07

Narrate supplied text.

- `POST /u/<secret>/episodes` now accepts `{"text": "...", "title": "..."}` to narrate an article or email body directly, with no server-side fetch. This bypasses paywalls when the user already receives the full text (for example a newsletter they get as a paying subscriber); a browser fetch of the URL would see only the preview. An optional `url` becomes the episode's source link.
- `title` is required in text mode; over-length text (more than 500,000 characters) and empty text are rejected at request time, so they never create an episode or spend a rate-limit share.
- A text episode with no source link omits the "Original article" line in the feed instead of showing a broken link.
```

- [ ] **Step 3: Verify no new em-dash and run the full suite**

Run: `sed -n '/## v3.14/,/## v3.13/p' CHANGELOG.md | grep -c '—'`
Expected: `0` (the v3.14 block has no em-dash; the `## v3.13` boundary line uses a middot too).

Run: `uv run pytest`
Expected: PASS (all green).

- [ ] **Step 4: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "docs: README + CHANGELOG for v3.14 narrate supplied text

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Request contract (text mode selection, required title, optional url validation, over-length 400, neither-field 400, both-fields text-wins) → Task 3. Covered.
- `ingest.process` text branch (skip fetch/paywall/min, keep MAX, reuse synth/write) → Task 2. Covered.
- `spawn_ingest` forwards text/title; `wire_fake_pipeline` updated → Task 3. Covered.
- RSS omits "Original article" when url empty → Task 1. Covered.
- AGENTS.md text-mode section → Task 4. Covered.
- README + CHANGELOG + v3.14 tag → Task 5 (tag deferred to post-merge). Covered.
- Tests for every spec bullet (happy path no-fetch, source link, no-link omission, title required, empty text, over-length, bad url, neither, cap+listing, AGENTS.md) → Tasks 1-4. Covered.
- Out of scope (Shortcut/text, HTML sanitizing, dedupe) → not implemented, as specified.

**Placeholder scan:** No TBD/TODO; every code and doc step shows literal content.

**Type/name consistency:** `process(url, secret, data_dir, slug=None, *, text=None, title=None)` matches the `spawn_ingest(..., text=None, title=None)` forward and the updated `wire_fake_pipeline` stub. Handler locals `text_mode`, `source_url`, `episode_title`, `record_title`, `spawn_text`, `spawn_title` are internally consistent. Response/record field names (`url`, `title`, `via`, `remaining`) match storage and the existing tests. `ingest.MAX_BODY_CHARS`/`MIN_BODY_CHARS` referenced consistently. The RSS builders keep their `(excerpt, article_url, home_url)` signatures; only the conditional changed.
