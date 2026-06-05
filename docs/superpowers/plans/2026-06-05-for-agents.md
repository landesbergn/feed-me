# For Agents (v3.6) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an AI agent holding only a user's feed URL add articles to that feed via a JSON API, documented at `/AGENTS.md`, with a 5/day rolling per-feed cap.

**Architecture:** Two new JSON routes under the existing `/u/{secret}` path reuse the whole `/share` ingest flow (quick title fetch, pending record, background ingest) minus the cookie and the HTML. Episode records gain a `via: "agent"` tag that must survive finalization (both `write_episode` and `write_failed_episode` rebuild the record from scratch today); the cap counts those tags in a rolling 24h window. `/AGENTS.md` is a plain-text template substituted with `APP_BASE_URL` at request time.

**Tech Stack:** FastAPI (existing), filesystem store (existing), pytest with `client` / `fake_http` / `fake_openai` fixtures (existing). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-06-05-for-agents.html` (read it first; it is the contract).

**Branch:** work on `for-agents` (already created from `main`).

---

## File structure

| File | Change | Responsibility |
|------|--------|----------------|
| `storage.py` | Modify | `via` param on `write_pending_episode`; `via` carry-over in `write_episode` / `write_failed_episode` |
| `app.py` | Modify | 4 new routes (`POST/GET /u/{secret}/episodes*`, `/AGENTS.md`, `/llms.txt`), cap constants + helpers, `via: "shortcut"` analytics tag in `share_route` |
| `templates/agents.md` | Create | The agent-facing API doc, `{base}` placeholders |
| `templates/settings.html` | Modify | "For agents" section + CSS + copy script |
| `tests/test_storage.py` | Modify | `via` persistence tests |
| `tests/test_agent_api.py` | Create | All agent-endpoint, cap, and docs-route tests |
| `tests/test_app.py` | Modify | One test: shortcut share tagged `via: "shortcut"` |
| `README.md`, `CHANGELOG.md`, `CLAUDE.md` | Modify | Route table, v3.6 entry, gotchas |

Conventions that apply to every task:

- Tests never hit the network. `client` fixture monkeypatches `app.DATA_DIR` to `tmp_path` and `app.APP_BASE_URL` to `https://test.local`, and uses `base_url="https://testserver"`.
- `POST /create` does **not** set the session cookie; only `GET /u/{secret}` does. Tests below rely on this to create feeds without linking the cookie jar.
- Every new feed is seeded with one welcome episode, so a fresh feed's `list_episodes` has length 1.
- No em-dashes in any user-facing or agent-facing copy (use `·`, commas, colons).

---

### Task 1: `via` tag on episode records, surviving finalization

The agent daily cap counts records with `via == "agent"`. Both finalization writers (`write_episode` on success, `write_failed_episode` on ingest failure) rebuild the record dict from scratch, which would drop the tag the moment an episode completes and silently turn the daily cap into a concurrency cap. This task adds the tag and the carry-over.

**Files:**
- Modify: `storage.py` (functions `write_pending_episode`, `write_episode`, `write_failed_episode`; new helper `_pending_via`)
- Test: `tests/test_storage.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_storage.py`. Check the imports at the top of that file first; it needs `import json` and `import storage` (add whichever is missing).

```python
def test_write_pending_episode_stores_via(tmp_path):
    secret = storage.create_user(tmp_path)
    slug = storage.write_pending_episode(
        tmp_path, secret, source_url="https://ex.com/a", via="agent",
    )
    record = json.loads((tmp_path / secret / f"{slug}.json").read_text())
    assert record["via"] == "agent"


def test_write_pending_episode_omits_via_by_default(tmp_path):
    secret = storage.create_user(tmp_path)
    slug = storage.write_pending_episode(
        tmp_path, secret, source_url="https://ex.com/a",
    )
    record = json.loads((tmp_path / secret / f"{slug}.json").read_text())
    assert "via" not in record


def test_write_episode_carries_via_through_finalization(tmp_path):
    """The agent daily cap counts via == "agent" records; via must survive
    the fresh-dict rewrite that write_episode does on completion."""
    secret = storage.create_user(tmp_path)
    slug = storage.write_pending_episode(
        tmp_path, secret, source_url="https://ex.com/a", via="agent",
    )
    storage.write_episode(
        tmp_path, secret, slug=slug,
        title="T", source_url="https://ex.com/a", audio=b"MP3",
    )
    record = json.loads((tmp_path / secret / f"{slug}.json").read_text())
    assert record["via"] == "agent"
    assert "pending" not in record    # fresh-dict semantics otherwise intact


def test_write_failed_episode_carries_via_through_finalization(tmp_path):
    secret = storage.create_user(tmp_path)
    slug = storage.write_pending_episode(
        tmp_path, secret, source_url="https://ex.com/a", via="agent",
    )
    storage.write_failed_episode(
        tmp_path, secret, slug=slug,
        source_url="https://ex.com/a", error="boom",
    )
    record = json.loads((tmp_path / secret / f"{slug}.json").read_text())
    assert record["via"] == "agent"


def test_finalization_without_pending_record_has_no_via(tmp_path):
    secret = storage.create_user(tmp_path)
    slug = storage.write_episode(
        tmp_path, secret,
        title="T", source_url="https://ex.com/a", audio=b"MP3",
    )
    record = json.loads((tmp_path / secret / f"{slug}.json").read_text())
    assert "via" not in record
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_storage.py -k via -v`
Expected: `test_write_pending_episode_stores_via` and the two carry-through tests FAIL (`TypeError: write_pending_episode() got an unexpected keyword argument 'via'` / `KeyError: 'via'`). The omit/no-via tests may already pass; that's fine.

- [ ] **Step 3: Implement in `storage.py`**

Add the helper above `write_episode`:

```python
def _pending_via(data_dir: Path, secret: str, slug: str) -> str | None:
    """Read the via tag off an existing (pending) record before finalization
    overwrites it. write_episode / write_failed_episode rebuild the record
    from scratch; the agent daily cap counts via == "agent" episodes, so
    dropping the tag would silently turn the daily cap into a concurrency cap.
    """
    try:
        record = json.loads((data_dir / secret / f"{slug}.json").read_text())
    except (OSError, json.JSONDecodeError):
        return None
    via = record.get("via")
    return via if isinstance(via, str) else None
```

In `write_pending_episode`, add the keyword parameter and the record key:

```python
def write_pending_episode(
    data_dir: Path, secret: str, *,
    source_url: str,
    title: str | None = None,
    description: str | None = None,
    via: str | None = None,
) -> str:
```

and after the `description` handling:

```python
    if via is not None:
        record["via"] = via
```

In `write_episode`, right after the `if slug is None: slug = _new_slug()` block (and **before** the record is written), read the tag and carry it:

```python
    via = _pending_via(data_dir, secret, slug)
```

then after the `description` handling:

```python
    if via is not None:
        record["via"] = via
```

In `write_failed_episode`, the same two additions in the same places.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_storage.py -v`
Expected: all PASS (the new five plus every pre-existing storage test).

- [ ] **Step 5: Commit**

```bash
git add storage.py tests/test_storage.py
git commit -m "feat: via tag on episode records, carried through finalization"
```

---

### Task 2: `POST /u/{secret}/episodes` core endpoint

JSON-in/JSON-out episode creation. Authenticates solely by the path secret; never reads or sets cookies. Parses the body manually (a Pydantic body model would reject malformed JSON with FastAPI's own `422 {"detail": [...]}`, breaking the documented `400 {"error": "invalid_request"}` contract; do not "clean this up" into a model later). The cap *rejection* is Task 3; this task implements window counting only as far as the `remaining` response field.

**Files:**
- Modify: `app.py`
- Create: `tests/test_agent_api.py`

- [ ] **Step 1: Create `tests/test_agent_api.py` with helpers and the failing tests**

```python
"""Agent API tests: POST/GET /u/{secret}/episodes*, the daily cap, and the
agent-facing docs routes. See docs/superpowers/specs/2026-06-05-for-agents.html."""
import json
import time

import analytics
import storage
from tests.conftest import FakeResponse

# Long enough to clear ingest's MIN_BODY_CHARS teaser guard.
ARTICLE_HTML = """<!doctype html><html><head><title>On Time</title></head>
<body><article><h1>On Time</h1>
<p>The first paragraph of a long piece about time.</p>
<p>Another paragraph here, with more substantive content to satisfy
Readability's minimum-content heuristics for extraction.</p>
<p>A third paragraph pads the body past the minimum-extraction guard
(MIN_BODY_CHARS) so fixture-driven tests exercise the happy path rather
than the too-short failure.</p>
<p>Clocks divide the day into hours, the hours into minutes, and the
minutes into seconds, each division more arbitrary than the last.</p>
<p>Calendars do the same to years, charting months and weeks against the
slow drift of seasons that ignore them entirely.</p>
<p>And yet the piece keeps returning to the same question: who decided
that time should be counted at all, and what was lost when we agreed?</p>
</article></body></html>"""


def make_feed(client) -> str:
    """Create a feed WITHOUT linking the client's cookie jar to it.
    (POST /create sets no cookie; only GET /u/{secret} does.)"""
    create = client.post("/create", follow_redirects=False)
    return create.headers["location"].split("/u/")[1]


def wire_fake_pipeline(monkeypatch, fake_http, fake_openai):
    """Run the (faked) ingest pipeline synchronously inside the request, so
    tests observe finished episodes: a via-drop at finalization fails here."""
    import app as app_module
    import ingest
    monkeypatch.setattr(ingest, "http_client", fake_http)
    monkeypatch.setattr(ingest, "openai_client", fake_openai)
    monkeypatch.setattr(
        app_module, "spawn_ingest",
        lambda url, secret, data_dir, slug: ingest.process(
            url, secret, data_dir, slug=slug
        ),
    )


def test_post_episode_happy_path(client, monkeypatch, fake_http, fake_openai, tmp_path):
    secret = make_feed(client)
    fake_http.responses["https://example.com/a"] = FakeResponse(
        status_code=200, text=ARTICLE_HTML,
    )
    wire_fake_pipeline(monkeypatch, fake_http, fake_openai)

    resp = client.post(
        f"/u/{secret}/episodes", json={"url": "https://example.com/a"},
    )

    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "pending"
    assert body["title"] == "On Time"
    assert body["status_url"] == f"https://test.local/u/{secret}/episodes/{body['slug']}"
    assert body["feed_page"] == f"https://test.local/u/{secret}"
    assert body["remaining"] == 4

    # The pipeline ran synchronously, so the episode is already finished;
    # via must survive finalization (pins the Task 1 carry-over end to end).
    record = json.loads((tmp_path / secret / f"{body['slug']}.json").read_text())
    assert "pending" not in record and "error" not in record   # it IS ready
    assert record["via"] == "agent"
    assert (tmp_path / secret / f"{body['slug']}.mp3").exists()


def test_post_episode_sets_no_cookie(client, monkeypatch, fake_http, fake_openai):
    secret = make_feed(client)
    fake_http.responses["https://example.com/a"] = FakeResponse(
        status_code=200, text=ARTICLE_HTML,
    )
    wire_fake_pipeline(monkeypatch, fake_http, fake_openai)

    resp = client.post(f"/u/{secret}/episodes", json={"url": "https://example.com/a"})

    assert resp.status_code == 202
    assert "set-cookie" not in resp.headers


def test_post_episode_ignores_session_cookie(
    client, monkeypatch, fake_http, fake_openai, tmp_path,
):
    """No ambient authority: the path secret decides the target feed; the
    fm_session cookie must be ignored entirely."""
    secret_a = make_feed(client)
    secret_b = make_feed(client)
    client.get(f"/u/{secret_b}")          # cookie now points at feed B
    fake_http.responses["https://example.com/a"] = FakeResponse(
        status_code=200, text=ARTICLE_HTML,
    )
    wire_fake_pipeline(monkeypatch, fake_http, fake_openai)

    client.post(f"/u/{secret_a}/episodes", json={"url": "https://example.com/a"})

    in_a = [e for e in storage.list_episodes(tmp_path, secret_a) if e.get("via") == "agent"]
    in_b = [e for e in storage.list_episodes(tmp_path, secret_b) if e.get("via") == "agent"]
    assert len(in_a) == 1
    assert len(in_b) == 0


def test_post_episode_unknown_feed_404(client):
    resp = client.post("/u/nope/episodes", json={"url": "https://example.com/a"})
    assert resp.status_code == 404
    assert resp.json()["error"] == "not_found"


def test_post_episode_invalid_json_400(client, tmp_path):
    secret = make_feed(client)
    resp = client.post(
        f"/u/{secret}/episodes",
        content=b"not json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_request"
    assert len(storage.list_episodes(tmp_path, secret)) == 1   # welcome only


def test_post_episode_missing_url_field_400(client, tmp_path):
    secret = make_feed(client)
    resp = client.post(f"/u/{secret}/episodes", json={"link": "https://example.com/a"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_request"
    assert len(storage.list_episodes(tmp_path, secret)) == 1   # welcome only


def test_post_episode_bad_scheme_400(client, tmp_path):
    secret = make_feed(client)
    resp = client.post(f"/u/{secret}/episodes", json={"url": "ftp://example.com/a"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_url"
    assert len(storage.list_episodes(tmp_path, secret)) == 1   # welcome only


def test_post_episode_records_agent_analytics(
    client, monkeypatch, fake_http, fake_openai, tmp_path,
):
    secret = make_feed(client)
    fake_http.responses["https://example.com/a"] = FakeResponse(
        status_code=200, text=ARTICLE_HTML,
    )
    wire_fake_pipeline(monkeypatch, fake_http, fake_openai)

    client.post(f"/u/{secret}/episodes", json={"url": "https://example.com/a"})

    db = tmp_path / "_analytics" / "analytics.db"
    shared = [e for e in analytics.all_events(db) if e["event"] == "article_shared"]
    assert len(shared) == 1
    props = json.loads(shared[0]["props"])
    assert props["via"] == "agent"
    assert props["url"] == "https://example.com/a"
    assert shared[0]["feed_hash"] == analytics.feed_hash(secret)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_agent_api.py -v`
Expected: all FAIL with 404/405 responses (route doesn't exist). Note `test_post_episode_unknown_feed_404` fails too: FastAPI's default 404 body is `{"detail": "Not Found"}`, not `{"error": "not_found"}`.

- [ ] **Step 3: Implement in `app.py`**

Add to the imports at the top:

```python
import json
```

and below the existing `fastapi` imports:

```python
from starlette.concurrency import run_in_threadpool
```

Add constants next to `COOKIE_NAME` / `COOKIE_MAX_AGE`:

```python
AGENT_DAILY_CAP = 5            # agent-created episodes per feed, rolling 24h
AGENT_CAP_WINDOW_S = 86400
```

Add helpers and the route after `share_status` (keeping the share-related routes together):

```python
def _agent_error(status: int, code: str, message: str,
                 headers: dict | None = None) -> JSONResponse:
    """Stable JSON error shape for the agent API: {"error", "message"}."""
    return JSONResponse(
        {"error": code, "message": message},
        status_code=status, headers=headers,
    )


def _agent_episodes_in_window(secret: str, now: int) -> list[dict]:
    """Agent-created episodes (any status) inside the rolling cap window."""
    return [
        ep for ep in storage.list_episodes(DATA_DIR, secret)
        if ep.get("via") == "agent" and ep["ts"] > now - AGENT_CAP_WINDOW_S
    ]


@app.post("/u/{secret}/episodes")
async def create_episode_api(request: Request, secret: str):
    """Agent-facing episode creation (documented at /AGENTS.md).

    Authenticates solely by the path secret; the fm_session cookie is
    deliberately never read and never set (no ambient authority, so no
    CSRF surface). Parses the body manually: a Pydantic body model would
    reject malformed JSON with FastAPI's 422 and break the documented
    400 {"error": "invalid_request"} contract.
    """
    if not storage.user_exists(DATA_DIR, secret):
        return _agent_error(404, "not_found", "No feed at this URL.")
    try:
        payload = json.loads(await request.body())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _agent_error(
            400, "invalid_request",
            'Body must be JSON like {"url": "https://..."}.',
        )
    url = payload.get("url") if isinstance(payload, dict) else None
    if not isinstance(url, str) or not url:
        return _agent_error(
            400, "invalid_request",
            'Body must include a string "url" field.',
        )
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return _agent_error(
            400, "invalid_url",
            f"Invalid URL: {url[:200]!r} (must be http or https).",
        )
    now = int(_time.time())
    in_window = _agent_episodes_in_window(secret, now)
    # fetch_title blocks on the network; this route is async (for
    # request.body()), so run it off the event loop.
    title = await run_in_threadpool(ingest.fetch_title, url)
    slug = storage.write_pending_episode(
        DATA_DIR, secret, source_url=url, title=title, via="agent",
    )
    spawn_ingest(url, secret, DATA_DIR, slug)
    _track("article_shared", secret=secret, path="agent",
           props={"url": url, "title": title, "via": "agent"})
    return JSONResponse({
        "slug": slug,
        "status": "pending",
        "title": title,
        "status_url": f"{APP_BASE_URL}/u/{secret}/episodes/{slug}",
        "feed_page": f"{APP_BASE_URL}/u/{secret}",
        "remaining": AGENT_DAILY_CAP - len(in_window) - 1,
    }, status_code=202)
```

(The 429 rejection between the window count and the title fetch is Task 3.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_agent_api.py -v`
Expected: all 8 PASS.

- [ ] **Step 5: Run the full suite (no regressions)**

Run: `uv run pytest -q`
Expected: everything passes (159 pre-existing + 5 from Task 1 + 8 new).

- [ ] **Step 6: Commit**

```bash
git add app.py tests/test_agent_api.py
git commit -m "feat: agent API: POST /u/{secret}/episodes creates an episode"
```

---

### Task 3: the 5/day rolling agent cap

**Files:**
- Modify: `app.py` (inside `create_episode_api`)
- Test: `tests/test_agent_api.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_agent_api.py`:

```python
def test_agent_cap_blocks_sixth_share(client, monkeypatch, fake_http, fake_openai):
    """Five COMPLETED agent shares block the sixth with 429. Episodes run to
    completion via the fake pipeline, so this validates daily semantics
    (via surviving finalization), not concurrent-pending counting."""
    secret = make_feed(client)
    wire_fake_pipeline(monkeypatch, fake_http, fake_openai)

    remaining_seen = []
    for i in range(5):
        url = f"https://example.com/a{i}"
        fake_http.responses[url] = FakeResponse(status_code=200, text=ARTICLE_HTML)
        resp = client.post(f"/u/{secret}/episodes", json={"url": url})
        assert resp.status_code == 202
        remaining_seen.append(resp.json()["remaining"])
    assert remaining_seen == [4, 3, 2, 1, 0]

    resp = client.post(f"/u/{secret}/episodes", json={"url": "https://example.com/a5"})
    assert resp.status_code == 429
    assert resp.json()["error"] == "rate_limited"
    assert int(resp.headers["Retry-After"]) > 0


def test_agent_cap_ignores_episodes_older_than_window(
    client, monkeypatch, fake_http, fake_openai, tmp_path,
):
    secret = make_feed(client)
    wire_fake_pipeline(monkeypatch, fake_http, fake_openai)

    # Five agent episodes, all outside the 24h window (ts rewritten on disk).
    old_ts = int(time.time()) - 90000
    for i in range(5):
        slug = storage.write_pending_episode(
            tmp_path, secret, source_url=f"https://ex.com/old{i}", via="agent",
        )
        path = tmp_path / secret / f"{slug}.json"
        record = json.loads(path.read_text())
        record["ts"] = old_ts
        path.write_text(json.dumps(record))

    fake_http.responses["https://example.com/new"] = FakeResponse(
        status_code=200, text=ARTICLE_HTML,
    )
    resp = client.post(f"/u/{secret}/episodes", json={"url": "https://example.com/new"})
    assert resp.status_code == 202


def test_shortcut_shares_do_not_count_toward_cap(
    client, monkeypatch, fake_http, fake_openai,
):
    secret = make_feed(client)
    client.get(f"/u/{secret}")     # link cookie for the Shortcut path
    wire_fake_pipeline(monkeypatch, fake_http, fake_openai)

    # A human share first...
    fake_http.responses["https://example.com/human"] = FakeResponse(
        status_code=200, text=ARTICLE_HTML,
    )
    assert client.get("/share?url=https://example.com/human").status_code == 200

    # ...leaves all five agent slots available.
    for i in range(5):
        url = f"https://example.com/a{i}"
        fake_http.responses[url] = FakeResponse(status_code=200, text=ARTICLE_HTML)
        assert client.post(f"/u/{secret}/episodes", json={"url": url}).status_code == 202


def test_agent_cap_does_not_block_shortcut(client, monkeypatch, fake_http, fake_openai):
    """Human sharing stays uncapped: with the agent window full, GET /share
    (cookie path) still works."""
    secret = make_feed(client)
    client.get(f"/u/{secret}")     # link cookie for the Shortcut path
    wire_fake_pipeline(monkeypatch, fake_http, fake_openai)

    for i in range(5):
        url = f"https://example.com/a{i}"
        fake_http.responses[url] = FakeResponse(status_code=200, text=ARTICLE_HTML)
        assert client.post(f"/u/{secret}/episodes", json={"url": url}).status_code == 202

    fake_http.responses["https://example.com/human"] = FakeResponse(
        status_code=200, text=ARTICLE_HTML,
    )
    resp = client.get("/share?url=https://example.com/human")
    assert resp.status_code == 200
    assert "Added" in resp.text


def test_failed_agent_episodes_count_toward_cap(
    client, monkeypatch, fake_http, fake_openai,
):
    """Failed ingests consumed work; an error-looping agent must still hit
    the cap."""
    secret = make_feed(client)
    wire_fake_pipeline(monkeypatch, fake_http, fake_openai)

    for i in range(5):
        url = f"https://example.com/dead{i}"
        fake_http.responses[url] = FakeResponse(status_code=500)
        resp = client.post(f"/u/{secret}/episodes", json={"url": url})
        assert resp.status_code == 202     # accepted; ingest then fails

    resp = client.post(f"/u/{secret}/episodes", json={"url": "https://example.com/ok"})
    assert resp.status_code == 429
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_agent_api.py -k cap -v`
Expected: `test_agent_cap_blocks_sixth_share` and `test_failed_agent_episodes_count_toward_cap` FAIL (202 where 429 expected). The other three PASS already (they assert the non-blocking direction); keep them, they pin the boundary.

- [ ] **Step 3: Implement the rejection**

In `create_episode_api`, directly after `in_window = _agent_episodes_in_window(secret, now)`:

```python
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
```

(The check-then-write is racy under simultaneous POSTs; accepted per spec §4: worst case is one episode over cap, and this is a cost guard, not a security boundary.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_agent_api.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_agent_api.py
git commit -m "feat: 5/day rolling per-feed cap on agent shares"
```

---

### Task 4: `GET /u/{secret}/episodes/{slug}` status endpoint

Secret-authed JSON polling (the existing `/share/status` is cookie-authed, so agents can't use it).

**Files:**
- Modify: `app.py`
- Test: `tests/test_agent_api.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_agent_api.py`:

```python
def test_episode_status_ready(client, monkeypatch, fake_http, fake_openai):
    secret = make_feed(client)
    fake_http.responses["https://example.com/a"] = FakeResponse(
        status_code=200, text=ARTICLE_HTML,
    )
    wire_fake_pipeline(monkeypatch, fake_http, fake_openai)
    slug = client.post(
        f"/u/{secret}/episodes", json={"url": "https://example.com/a"},
    ).json()["slug"]

    resp = client.get(f"/u/{secret}/episodes/{slug}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["slug"] == slug
    assert body["status"] == "ready"
    assert body["audio_url"] == f"https://test.local/u/{secret}/audio/{slug}.mp3"
    assert body["error"] is None
    assert "set-cookie" not in resp.headers


def test_episode_status_pending(client, monkeypatch, fake_http):
    import app as app_module
    import ingest
    secret = make_feed(client)
    monkeypatch.setattr(ingest, "http_client", fake_http)            # title fetch
    monkeypatch.setattr(app_module, "spawn_ingest", lambda *a, **k: None)
    fake_http.responses["https://example.com/a"] = FakeResponse(
        status_code=200, text=ARTICLE_HTML,
    )
    slug = client.post(
        f"/u/{secret}/episodes", json={"url": "https://example.com/a"},
    ).json()["slug"]

    body = client.get(f"/u/{secret}/episodes/{slug}").json()
    assert body["status"] == "pending"
    assert "audio_url" not in body


def test_episode_status_failed(client, monkeypatch, fake_http, fake_openai):
    secret = make_feed(client)
    fake_http.responses["https://example.com/dead"] = FakeResponse(status_code=500)
    wire_fake_pipeline(monkeypatch, fake_http, fake_openai)
    slug = client.post(
        f"/u/{secret}/episodes", json={"url": "https://example.com/dead"},
    ).json()["slug"]

    body = client.get(f"/u/{secret}/episodes/{slug}").json()
    assert body["status"] == "failed"
    assert body["error"]


def test_episode_status_unknown_slug_404(client):
    secret = make_feed(client)
    resp = client.get(f"/u/{secret}/episodes/zzzzzzzzzzz")
    assert resp.status_code == 404
    assert resp.json()["error"] == "not_found"


def test_episode_status_malformed_slug_404(client):
    secret = make_feed(client)
    resp = client.get(f"/u/{secret}/episodes/bad.slug")   # '.' fails SLUG_RE
    assert resp.status_code == 404


def test_episode_status_unknown_feed_404(client):
    resp = client.get("/u/nope/episodes/abc123")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_agent_api.py -k episode_status -v`
Expected: ready/pending/failed tests FAIL (404: route doesn't exist); the unknown-slug test fails on body shape (`{"detail": ...}` vs `{"error": ...}`).

- [ ] **Step 3: Implement in `app.py`**

Add after `create_episode_api`:

```python
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
```

(Route order vs `GET /u/{secret}/episodes_partial` is not a conflict: `episodes_partial` is a distinct literal segment.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_agent_api.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_agent_api.py
git commit -m "feat: agent API: GET /u/{secret}/episodes/{slug} status"
```

---

### Task 5: tag Shortcut shares `via: "shortcut"` in analytics

So "via present" never silently means "agent": both share paths are explicit, and the split is unambiguous in `/admin/export` with zero admin-UI changes. (Episode *records* are unchanged here; only agent episodes carry `via` on disk, which is what the cap counts.)

**Files:**
- Modify: `app.py:171-172` (the `_track("article_shared", ...)` call in `share_route`)
- Test: `tests/test_app.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_app.py`, next to `test_share_event_records_article_url_and_title`:

```python
def test_share_event_props_tag_via_shortcut(client, monkeypatch, tmp_path):
    import json as _json
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]
    client.get(f"/u/{secret}")  # link browser (cookie)

    import app as app_module
    monkeypatch.setattr(app_module, "spawn_ingest", lambda *a, **k: None)
    monkeypatch.setattr(app_module.ingest, "fetch_title", lambda url: "T")

    client.get("/share?url=https://example.com/a")

    import analytics
    db = tmp_path / "_analytics" / "analytics.db"
    shared = [e for e in analytics.all_events(db) if e["event"] == "article_shared"]
    assert len(shared) == 1
    assert _json.loads(shared[0]["props"])["via"] == "shortcut"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_app.py -k via_shortcut -v`
Expected: FAIL with `KeyError: 'via'`.

- [ ] **Step 3: Implement**

In `share_route`, change the existing call:

```python
    _track("article_shared", secret=secret, path="share",
           props={"url": url, "title": title, "via": "shortcut"})
```

- [ ] **Step 4: Run the suite to verify it passes**

Run: `uv run pytest tests/test_app.py -q`
Expected: all PASS (existing analytics tests assert counts and url/title, not exact prop dicts, so the added key is additive; if one does exact-match, update it in the same commit and say so).

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "feat: tag article_shared analytics via=shortcut on the share page"
```

---

### Task 6: `/AGENTS.md` and `/llms.txt`

**Files:**
- Create: `templates/agents.md`
- Modify: `app.py`
- Test: `tests/test_agent_api.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_agent_api.py`:

```python
def test_agents_md_served_as_markdown(client):
    resp = client.get("/AGENTS.md")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    assert "https://test.local/u/" in resp.text       # APP_BASE_URL substituted
    assert "{base}" not in resp.text                  # nothing left unsubstituted
    assert "5 episodes" in resp.text                  # the cap is documented
    assert "Retry-After" in resp.text
    assert "—" not in resp.text                       # house style: no em-dashes


def test_llms_txt_points_at_agents_md(client):
    resp = client.get("/llms.txt")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert "https://test.local/AGENTS.md" in resp.text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_agent_api.py -k "agents_md or llms" -v`
Expected: both FAIL with 404.

- [ ] **Step 3: Create `templates/agents.md`**

The `{base}` placeholder is substituted with `APP_BASE_URL` at request time via `str.replace`. Plain `.replace`, NOT Jinja (Starlette's autoescape would mangle the JSON examples into `&#34;`) and NOT `str.format` (the JSON braces would raise `KeyError`). The JSON braces below are intentional and safe.

```markdown
# Feed Me · API for agents

Feed Me turns articles into narrated podcast episodes in a private feed.
A user shares an article; a few minutes later it is in their podcast app,
read aloud. This page is for AI agents and scripts adding articles on a
user's behalf. Base URL: {base}

## Auth: the feed URL is the credential

There is no API key and no signup. The user gives you their feed page URL:

    {base}/u/<secret>

The secret in that URL is their entire account. Treat it like a password:

- Never log it, post it publicly, or echo it into shared context.
- If you believe it leaked, tell the user to use "Rotate URL" on their
  feed page (the old URL stops working).

## Add an article

    POST {base}/u/<secret>/episodes
    Content-Type: application/json

    {"url": "https://example.com/some-article"}

Response: 202 Accepted

    {
      "slug": "k3kQ9rTzVx0",
      "status": "pending",
      "title": "The Article Title",
      "status_url": "{base}/u/<secret>/episodes/k3kQ9rTzVx0",
      "feed_page": "{base}/u/<secret>",
      "remaining": 4
    }

Notes:

- "title" is null when the quick title fetch failed; the episode still
  processes normally.
- "remaining" is how many agent shares are left in the rolling 24-hour
  window (see Rate limit).
- Only http/https article URLs are accepted. Unknown body fields are
  ignored.

## Poll status

    GET {base}/u/<secret>/episodes/<slug>

    {
      "slug": "k3kQ9rTzVx0",
      "status": "pending",
      "title": "The Article Title",
      "ts": 1781234567,
      "total_chunks": 12,
      "error": null
    }

"status" moves from "pending" to "ready" (an "audio_url" field appears) or
"failed" ("error" holds a human-readable reason: paywalled article, fetch
error, article too long). Narration usually takes one to a few minutes;
poll no faster than every few seconds. When an episode fails, report the
error to the user and do not retry the same URL.

## Read the feed

    GET {base}/u/<secret>/feed.xml

The podcast RSS feed: every episode with titles, descriptions, and audio
URLs.

## Errors

| Status | error | Meaning | Retry? |
|--------|-------|---------|--------|
| 400 | invalid_request | Body is not JSON, or has no string "url" field | No: fix the request |
| 400 | invalid_url | URL is not http/https with a host | No: fix the URL |
| 404 | not_found | No feed at that secret, or no such episode | No: check the feed URL with the user |
| 429 | rate_limited | Agent cap reached | Not before Retry-After; tell the user |

Error bodies are JSON: {"error": "<code>", "message": "<human-readable>"}.

## Rate limit

5 episodes per feed per rolling 24 hours through this API. The user's own
phone sharing does not count against it. A 429 response includes a
Retry-After header (seconds). Do not retry before it elapses; tell the
user instead.

## Etiquette

- Share only what the user asked you to share.
- Do not retry permanent errors (400, 404).
- On 429, stop and tell the user.
- Poll the status URL no faster than every few seconds.
- Send a descriptive User-Agent so your traffic is identifiable.

## Example: curl

    curl -s -X POST {base}/u/<secret>/episodes \
      -H 'Content-Type: application/json' \
      -d '{"url": "https://example.com/some-article"}'

## Example: Python

    import time
    import httpx

    feed = "{base}/u/<secret>"      # the URL the user gave you

    created = httpx.post(
        feed + "/episodes",
        json={"url": "https://example.com/some-article"},
    )
    created.raise_for_status()
    episode = created.json()

    status = episode
    while status["status"] == "pending":
        time.sleep(5)
        status = httpx.get(episode["status_url"]).json()

    print(status["status"], status.get("audio_url") or status.get("error"))
```

- [ ] **Step 4: Implement the routes in `app.py`**

Add a constant next to `STATIC_DIR`:

```python
TEMPLATES_DIR = Path(__file__).parent / "templates"
```

Add the routes near `healthz`:

```python
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
    )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_agent_api.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add templates/agents.md app.py tests/test_agent_api.py
git commit -m "feat: serve /AGENTS.md and /llms.txt for agent discovery"
```

---

### Task 7: "For agents" section on the feed page

**Files:**
- Modify: `templates/settings.html`, `app.py` (settings route context)
- Test: `tests/test_agent_api.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_agent_api.py`:

```python
def test_settings_page_shows_for_agents_section(client):
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]

    resp = client.get(f"/u/{secret}")

    assert resp.status_code == 200
    assert "For agents" in resp.text
    assert "I have a Feed Me podcast feed" in resp.text
    # The prompt is personalized with this feed's URL and the docs URL.
    assert f"My feed page: https://test.local/u/{secret}." in resp.text
    assert "https://test.local/AGENTS.md" in resp.text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_agent_api.py -k for_agents -v`
Expected: FAIL (`"For agents" not in resp.text`).

- [ ] **Step 3: Pass `base_url` to the template**

In `app.py` `settings()`, add one key to the `TemplateResponse` context dict:

```python
        "base_url": APP_BASE_URL,
```

- [ ] **Step 4: Add the section to `templates/settings.html`**

Insert after the closing `</details>` of the existing `details.settings` block (the one ending with the Rotate form), before the `<script>` block with `FEED_URL`:

```html
  <details class="settings">
    <summary>For agents</summary>
    <div class="body">
      <p>Your AI agent (Claude Code and friends) can add articles to this
         feed. Copy this into your agent's instructions or memory:</p>
      <pre class="agent-prompt" id="agent-prompt">I have a Feed Me podcast feed. To send an article to it, read {{ base_url }}/AGENTS.md and follow it. My feed page: {{ base_url }}/u/{{ secret }}. Agents can add up to 5 episodes per day.</pre>
      <button class="btn-secondary" type="button" onclick="copyAgentPrompt()">Copy</button>
      <p class="note">Keep this private: that link is your whole account.</p>
    </div>
  </details>
```

Add CSS next to the `.voices` rules in the `<style>` block:

```css
    .agent-prompt {
      white-space: pre-wrap; overflow-wrap: anywhere; background: #fff;
      border: 1.5px solid #E9C9AC; border-radius: 12px; padding: 12px 14px;
      font-size: 12px; line-height: 1.5; margin: 10px 0 0;
      font-family: ui-monospace, "SF Mono", Menlo, monospace;
    }
```

Add the copy function inside the existing `<script>` that defines `copyFeedUrl`:

```javascript
    function copyAgentPrompt() {
      var el = document.getElementById("agent-prompt");
      try { navigator.clipboard.writeText(el.textContent.trim()); } catch (e) {}
    }
```

- [ ] **Step 5: Run the test, then grep for em-dashes (house rule for template changes)**

Run: `uv run pytest tests/test_agent_api.py -v`
Expected: all PASS.

Run: `grep -rn "—" templates/`
Expected: no output (exit code 1).

- [ ] **Step 6: Commit**

```bash
git add templates/settings.html app.py tests/test_agent_api.py
git commit -m "feat: For agents section on the feed page"
```

---

### Task 8: docs, changelog, final verification

**Files:**
- Modify: `README.md` (route table + one "Good to know" bullet), `CHANGELOG.md`, `CLAUDE.md` (gotchas)

- [ ] **Step 1: README**

Add to the route table (after the `/share/status` row, keeping the share flow together):

```markdown
| `POST /u/{secret}/episodes` | Agent API: create an episode from a JSON body (`{"url": ...}`); 5/day rolling cap |
| `GET /u/{secret}/episodes/{slug}` | Agent API: JSON episode status, secret-authed |
| `GET /AGENTS.md`, `GET /llms.txt` | Agent-facing API docs |
```

Add one bullet under "Good to know":

```markdown
- **Agents welcome.** Your AI agent (Claude Code and friends) can add
  articles for you. Open your feed page and copy the "For agents" prompt,
  or point your agent at [feed-me.xyz/AGENTS.md](https://feed-me.xyz/AGENTS.md).
```

- [ ] **Step 2: CHANGELOG**

Add at the top of `CHANGELOG.md`:

```markdown
## v3.6 — 2026-06-05

For agents: AI agents can add articles to a feed.

- New agent API: `POST /u/<secret>/episodes` (JSON in, 202 + status URL out) and `GET /u/<secret>/episodes/<slug>` for polling. Authenticated by the path secret only; the session cookie is never read or set on these routes.
- `/AGENTS.md` (plus an `/llms.txt` pointer) documents the API for agents: endpoints, stable error codes, etiquette, rate limit, curl/Python examples.
- "For agents" section on the feed page with a copy-paste prompt personalized to the feed.
- Agent shares capped at 5 per feed per rolling 24h (429 + `Retry-After` beyond that); phone sharing is never throttled. The `via: "agent"` record tag now survives episode finalization so the cap counts completed episodes, not just pending ones.
- `article_shared` analytics carry `via: "agent" | "shortcut"`. No user-agent strings are stored (keeps the v3.1 analytics privacy promise).
```

- [ ] **Step 3: CLAUDE.md gotchas**

Add two bullets under "Gotchas":

```markdown
- The agent API (`POST/GET /u/<secret>/episodes*`) authenticates by the
  path secret only: never read or set the session cookie there, and keep
  its errors as `{"error", "message"}` JSON (the POST parses its body by
  hand because a Pydantic model would 422 instead of the documented 400).
- `templates/agents.md` is substituted with plain `.replace("{base}", ...)`,
  not Jinja (autoescape mangles the JSON examples) and not `str.format`
  (the JSON braces break it).
```

- [ ] **Step 4: Full verification**

Run: `uv run pytest -q`
Expected: all tests pass (~180), zero failures.

Run: `grep -rn "—" templates/`
Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add README.md CHANGELOG.md CLAUDE.md
git commit -m "docs: README routes, gotchas, changelog for v3.6"
```

---

## After the plan

Release steps (NOT part of this plan; follow superpowers:finishing-a-development-branch): merge `for-agents`, tag `v3.6`, deploy with `~/.fly/bin/fly deploy --app feed-me-noah-willow-grove-8052`, then verify `curl https://feed-me.xyz/AGENTS.md` and `curl https://feed-me.xyz/healthz`.
