# Seamless Agent Sharing (v3.12) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user's agent run "send this article to my feed" in one shot, with no feed-URL rediscovery and no back-and-forth, by adding a cheap feed-listing endpoint and rewriting `AGENTS.md` to make the agent persist the feed URL on first contact.

**Architecture:** One additive FastAPI route, `GET /u/{secret}/episodes`, that returns the feed's recent episodes plus voice and remaining quota as JSON (path-secret auth, no cookie, same `{"error","message"}` contract as the other agent endpoints; currently this path 405s on GET). Plus a re-sequenced `templates/agents.md` and a one-clause prompt change in `templates/_setup_instructions.html`. No change to the POST creation path, the rate limiter, storage, the cookie `/share` flow, or RSS.

**Tech Stack:** Python 3, FastAPI, Starlette `TestClient`, pytest. Run tests with `uv run pytest`.

**Spec:** `docs/superpowers/specs/2026-06-07-agent-sharing-seamless.html`

---

## File Structure

| File | Change | Responsibility |
|------|--------|----------------|
| `app.py` | Modify (add route after the `POST` handler, ~line 300) | New `list_episodes_api` GET handler |
| `tests/test_agent_api.py` | Modify (append tests) | Cover the new endpoint, the AGENTS.md rewrite, and the prompt change |
| `templates/agents.md` | Rewrite | Happy-path-first docs: Step 0 persistence, no-guess rule, list endpoint |
| `templates/_setup_instructions.html` | Modify (one line) | Prompt tells the agent to save the feed URL |
| `README.md` | Modify (one table row) | Document the new route |
| `CHANGELOG.md` | Modify (prepend entry) | v3.12 release notes |

**Conventions to honor (from CLAUDE.md and the existing tests):**
- The agent endpoints authenticate by the path secret only: never read or set the session cookie, and return errors as `{"error","message"}` JSON via the existing `_agent_error(...)` helper.
- `templates/agents.md` is rendered with a plain `.replace("{base}", APP_BASE_URL)` (not Jinja, not `str.format`). Keep using the literal `{base}` token; JSON-example braces are fine because only the literal string `{base}` is replaced.
- No em-dashes (`—`) in user- or agent-facing copy; the middot `·` is allowed. The existing test `test_agents_md_served_as_markdown` already asserts `"—" not in resp.text`.
- In tests, `APP_BASE_URL` is monkeypatched to `https://test.local`; the `client` fixture points `DATA_DIR` at a per-test temp dir (which is `tmp_path`).
- Test helpers already in `tests/test_agent_api.py`: `make_feed(client)`, `wire_fake_pipeline(monkeypatch, fake_http, fake_openai)`, `ARTICLE_HTML`, and `FakeResponse` (imported from `tests.conftest`).

---

## Task 1: New `GET /u/{secret}/episodes` list/confirm endpoint

**Files:**
- Modify: `app.py` (insert a new handler between the `POST /u/{secret}/episodes` handler that ends at ~line 300 and the `GET /u/{secret}/episodes/{slug}` handler at ~line 303)
- Test: `tests/test_agent_api.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_agent_api.py`:

```python
# --- GET /u/{secret}/episodes : list / confirm -------------------------------

def test_list_episodes_returns_feed_info_and_episodes(
    client, monkeypatch, fake_http, fake_openai,
):
    secret = make_feed(client)
    fake_http.responses["https://example.com/a"] = FakeResponse(
        status_code=200, text=ARTICLE_HTML,
    )
    wire_fake_pipeline(monkeypatch, fake_http, fake_openai)
    slug = client.post(
        f"/u/{secret}/episodes", json={"url": "https://example.com/a"},
    ).json()["slug"]

    resp = client.get(f"/u/{secret}/episodes")

    assert resp.status_code == 200
    assert "set-cookie" not in resp.headers          # path-secret auth, no cookie
    body = resp.json()
    assert body["feed_page"] == f"https://test.local/u/{secret}"
    assert body["feed_url"] == f"https://test.local/u/{secret}/feed.xml"
    assert body["voice"] in storage.ALLOWED_VOICES
    assert body["remaining"] == 4                    # one agent share used
    shared = next(e for e in body["episodes"] if e["slug"] == slug)
    assert shared["status"] == "ready"
    assert shared["title"] == "On Time"
    assert shared["ts"]
    assert shared["audio_url"] == f"https://test.local/u/{secret}/audio/{slug}.mp3"


def test_list_episodes_failed_has_error_and_no_audio(
    client, monkeypatch, fake_http, fake_openai,
):
    secret = make_feed(client)
    fake_http.responses["https://example.com/dead"] = FakeResponse(status_code=500)
    wire_fake_pipeline(monkeypatch, fake_http, fake_openai)
    slug = client.post(
        f"/u/{secret}/episodes", json={"url": "https://example.com/dead"},
    ).json()["slug"]

    body = client.get(f"/u/{secret}/episodes").json()
    failed = next(e for e in body["episodes"] if e["slug"] == slug)
    assert failed["status"] == "failed"
    assert failed["error"]
    assert "audio_url" not in failed


def test_list_episodes_hides_internal_fields(
    client, monkeypatch, fake_http, fake_openai,
):
    secret = make_feed(client)
    fake_http.responses["https://example.com/a"] = FakeResponse(
        status_code=200, text=ARTICLE_HTML,
    )
    wire_fake_pipeline(monkeypatch, fake_http, fake_openai)
    client.post(f"/u/{secret}/episodes", json={"url": "https://example.com/a"})

    body = client.get(f"/u/{secret}/episodes").json()
    assert body["episodes"]
    for ep in body["episodes"]:
        for leaked in ("mtime", "audio_bytes", "has_audio", "source_url", "via"):
            assert leaked not in ep


def test_list_episodes_unknown_feed_404(client):
    resp = client.get("/u/nope/episodes")
    assert resp.status_code == 404
    assert resp.json()["error"] == "not_found"


def test_list_episodes_remaining_tracks_cap(
    client, monkeypatch, fake_http, fake_openai,
):
    secret = make_feed(client)
    wire_fake_pipeline(monkeypatch, fake_http, fake_openai)
    for i in range(3):
        url = f"https://example.com/a{i}"
        fake_http.responses[url] = FakeResponse(status_code=200, text=ARTICLE_HTML)
        client.post(f"/u/{secret}/episodes", json={"url": url})

    body = client.get(f"/u/{secret}/episodes").json()
    assert body["remaining"] == 2                    # 5 cap - 3 used


def test_list_episodes_caps_at_twenty(client, tmp_path):
    secret = make_feed(client)
    # Welcome already seeded; add 25 more so the feed exceeds the cap.
    for i in range(25):
        storage.write_pending_episode(
            tmp_path, secret, source_url=f"https://ex.com/{i}", title=f"E{i}",
        )

    body = client.get(f"/u/{secret}/episodes").json()
    assert len(body["episodes"]) == 20
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_agent_api.py -k list_episodes -v`
Expected: FAIL. The new GET route does not exist yet, so `GET /u/{secret}/episodes` matches no handler and returns **405 Method Not Allowed** (the POST route owns that path). `test_list_episodes_unknown_feed_404` will see 405 instead of 404; the others will fail asserting on a non-JSON / wrong-status body.

- [ ] **Step 3: Implement the endpoint**

In `app.py`, insert this handler immediately before `@app.get("/u/{secret}/episodes/{slug}")` (the `episode_status_api` function):

```python
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
    remaining = max(
        0, AGENT_DAILY_CAP - len(_agent_episodes_in_window(secret, now)),
    )
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
        "episodes": episodes,
    })
```

Notes for the implementer:
- `JSONResponse`, `storage`, `_time`, `_agent_error`, `_agent_episodes_in_window`, `AGENT_DAILY_CAP`, `APP_BASE_URL`, and `DATA_DIR` are all already imported/defined in `app.py` (the POST handler uses every one of them). Add no imports.
- Build each episode dict explicitly. Do **not** pass the raw `storage.list_episodes` record through: it carries `mtime`, `audio_bytes`, `has_audio`, `source_url`, and `via`, which must not leak.
- This endpoint is intentionally **untracked** (no `_track` call), matching the other agent endpoints. The raw secret must never reach analytics.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_agent_api.py -k list_episodes -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Run the full agent-API file to confirm no regressions**

Run: `uv run pytest tests/test_agent_api.py -v`
Expected: PASS (all existing tests plus the 6 new ones).

- [ ] **Step 6: Commit**

```bash
git add app.py tests/test_agent_api.py
git commit -m "feat: GET /u/<secret>/episodes lists the feed for agents

Adds a cheap JSON listing (20 most recent episodes, voice, remaining
quota) so an agent can confirm it has the right feed and check its budget
without parsing feed.xml. Path-secret auth, no cookie, {error,message}
errors; a 404 doubles as the feed-exists check. Previously GET on this
path returned 405.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Rewrite `AGENTS.md` (persistence + no-guess + list endpoint)

**Files:**
- Modify: `templates/agents.md` (full rewrite)
- Test: `tests/test_agent_api.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_agent_api.py`:

```python
def test_agents_md_tells_agent_to_persist_feed(client):
    text = client.get("/AGENTS.md").text
    assert "Remember this feed" in text
    assert "durable memory" in text


def test_agents_md_forbids_guessing_the_feed(client):
    text = client.get("/AGENTS.md").text
    assert "ask the user" in text
    assert "Never guess" in text


def test_agents_md_documents_list_endpoint(client):
    text = client.get("/AGENTS.md").text
    assert "List the feed" in text
    # The list endpoint line, base substituted, terminated by newline so it
    # does not match the POST line or the per-slug poll line.
    assert "GET https://test.local/u/<secret>/episodes\n" in text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_agent_api.py -k agents_md -v`
Expected: the three new tests FAIL (the current `agents.md` has none of these strings); `test_agents_md_served_as_markdown` still PASSES.

- [ ] **Step 3: Rewrite `templates/agents.md`**

Replace the **entire** contents of `templates/agents.md` with:

```markdown
# Feed Me · API for agents

Feed Me turns articles into narrated podcast episodes in a private feed.
A user shares an article; a few minutes later it is in their podcast app,
read aloud. This page is for AI agents and scripts adding articles on a
user's behalf. Base URL: {base}

## TL;DR

You have a feed URL of the form {base}/u/<secret>. To narrate an article:

1. POST the article URL to {base}/u/<secret>/episodes.
2. Poll the returned status_url every few seconds until status is "ready".
3. Tell the user it is in their feed. Done.

    curl -s -X POST {base}/u/<secret>/episodes \
      -H 'Content-Type: application/json' \
      -d '{"url": "https://example.com/some-article"}'

## Step 0 · Remember this feed

The feed URL is the only credential and the only thing you need to do this
again. The first time a user gives it to you, save the feed URL to your
durable memory or project config so future requests need no URL and no
questions. For example, a Claude Code agent saves it to CLAUDE.md or its
memory directory; other agents save it wherever they keep per-user config.
The prompt the user pasted already contains the URL, so capture it once.

If you do not have the feed URL, ask the user for it. Never guess it, scan
history or past transcripts, or probe candidate feeds. A guessed feed is
the wrong feed.

## Auth: the feed URL is the credential

There is no API key and no signup. The user gives you their feed page URL:

    {base}/u/<secret>

The secret in that URL is their entire account. Treat it like a password:

- Never log it, post it publicly, or echo it into shared context.
- If you do not have it, ask the user. Never guess or rediscover it.
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

## List the feed

    GET {base}/u/<secret>/episodes

    {
      "feed_page": "{base}/u/<secret>",
      "feed_url": "{base}/u/<secret>/feed.xml",
      "voice": "shimmer",
      "remaining": 3,
      "episodes": [
        {
          "slug": "k3kQ9rTzVx0",
          "title": "The Article Title",
          "status": "ready",
          "ts": 1781234567,
          "audio_url": "{base}/u/<secret>/audio/k3kQ9rTzVx0.mp3"
        }
      ]
    }

The 20 most recent episodes, newest first, plus the feed's voice and your
"remaining" agent quota. "audio_url" appears only on "ready" episodes;
"error" appears only on "failed" ones. Use this to confirm you have the
right feed (a 404 means the URL is wrong or was rotated, so ask the user)
and to check your remaining quota before sharing.

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

- Save the feed URL the first time you get it; do not ask again next time.
- If you do not have the feed URL, ask the user. Never guess, scan history,
  or probe feeds.
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
    # Save `feed` to your durable memory so you need not ask again next time.

    created = httpx.post(
        feed + "/episodes",
        json={"url": "https://example.com/some-article"},
    )
    created.raise_for_status()
    episode = created.json()

    status = episode
    while status["status"] == "pending":
        time.sleep(5)
        polled = httpx.get(episode["status_url"])
        polled.raise_for_status()
        status = polled.json()

    print(status["status"], status.get("audio_url") or status.get("error"))
```

- [ ] **Step 4: Verify the copy is em-dash free**

Run: `grep -c '—' templates/agents.md`
Expected: `0`

- [ ] **Step 5: Run the AGENTS.md tests**

Run: `uv run pytest tests/test_agent_api.py -k agents_md -v`
Expected: PASS (the 3 new tests plus the existing `test_agents_md_served_as_markdown`, which still finds `"5 episodes"`, `"Retry-After"`, a substituted `https://test.local/u/`, no leftover `{base}`, and no em-dash).

- [ ] **Step 6: Commit**

```bash
git add templates/agents.md tests/test_agent_api.py
git commit -m "docs: rewrite AGENTS.md for one-shot agent sharing

Leads with the happy path, adds 'Step 0 - Remember this feed' (persist the
feed URL on first contact), forbids guessing/scanning/probing for the feed,
and documents GET /episodes. No em-dashes.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Prompt snippet tells the agent to save the feed

**Files:**
- Modify: `templates/_setup_instructions.html` (the prompt text, ~line 70)
- Test: `tests/test_agent_api.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_agent_api.py`:

```python
def test_settings_prompt_tells_agent_to_save_feed(client):
    secret = make_feed(client)
    resp = client.get(f"/u/{secret}")
    assert "Save my feed page so you don't have to ask again" in resp.text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_agent_api.py -k save_feed -v`
Expected: FAIL (the current prompt has no such clause).

- [ ] **Step 3: Edit the prompt text**

In `templates/_setup_instructions.html`, replace the prompt line (the `<div class="text" id="prompt-text">...</div>` content):

Old:
```html
      <div class="text" id="prompt-text">I have a Feed Me podcast feed. To send an article to it, read {{ base_url }}/AGENTS.md and follow it. My feed page: {{ base_url }}/u/{{ secret }}.</div>
```

New:
```html
      <div class="text" id="prompt-text">I have a Feed Me podcast feed. Save my feed page so you don't have to ask again, then read {{ base_url }}/AGENTS.md to send articles. My feed page: {{ base_url }}/u/{{ secret }}.</div>
```

This keeps the substrings the existing tests pin (`I have a Feed Me podcast feed`, `My feed page: {{ base_url }}/u/{{ secret }}.`, the `AGENTS.md` link) so `test_settings_page_inlines_agent_prompt` and friends stay green; only the prose grows.

- [ ] **Step 4: Confirm no em-dash crept in**

Run: `grep -c '—' templates/_setup_instructions.html`
Expected: `0`

- [ ] **Step 5: Run the affected tests**

Run: `uv run pytest tests/test_agent_api.py -k "save_feed or inlines_agent_prompt or share_toggle or prompt_shows_after_setup" -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add templates/_setup_instructions.html tests/test_agent_api.py
git commit -m "feat: agent prompt tells the agent to save the feed URL

The copy-paste prompt now asks the agent to persist the feed page so future
sessions need no URL and no questions.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Docs (README route row + CHANGELOG) and release tag

**Files:**
- Modify: `README.md` (one route-table row)
- Modify: `CHANGELOG.md` (prepend a v3.12 entry)

- [ ] **Step 1: Add the README route row**

In `README.md`, immediately after the `POST /u/{secret}/episodes` row (currently line 80), insert:

```markdown
| `GET /u/{secret}/episodes` | Agent API: JSON feed listing (20 most recent) + voice + remaining quota, secret-authed |
```

So the two surrounding rows read:

```markdown
| `POST /u/{secret}/episodes` | Agent API: create an episode from a JSON body (`{"url": ...}`); 5/day rolling cap |
| `GET /u/{secret}/episodes` | Agent API: JSON feed listing (20 most recent) + voice + remaining quota, secret-authed |
| `GET /u/{secret}/episodes/{slug}` | Agent API: JSON episode status, secret-authed |
```

- [ ] **Step 2: Prepend the CHANGELOG entry**

In `CHANGELOG.md`, insert this block directly below the `# Changelog` heading and above the current top entry (`## v3.11 ...`). Older entries use an em-dash in the date header, but house style forbids em-dashes (CLAUDE.md: "grep for `—` before shipping"), so use the middot `·` for this entry. Keep the body prose em-dash free too:

```markdown
## v3.12 · 2026-06-07

Seamless agent sharing.

- New `GET /u/<secret>/episodes`: a JSON listing of the feed (the 20 most recent episodes, newest first) plus the feed's voice and the agent's remaining 24h quota. Path-secret auth, no cookie, the same `{"error","message"}` errors as the other agent endpoints; a 404 doubles as the cheap "is this feed real?" check. Previously this path accepted only POST and returned 405 to a GET.
- `AGENTS.md` rewritten to lead with the happy path, tell agents to save the feed URL on first contact ("Step 0 · Remember this feed"), and never guess, scan history, or probe feeds when they lack the URL. The list endpoint is documented.
- The "For your agent" prompt now tells the agent to save the feed page so it does not have to ask again.
```

- [ ] **Step 3: Run the full suite**

Run: `uv run pytest`
Expected: PASS (no network; all tests green).

- [ ] **Step 4: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "docs: README route + CHANGELOG for v3.12 seamless agent sharing

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 5: Tag the release**

```bash
git tag v3.12
```

(Push and deploy are owner-driven and out of scope for this plan. Deploy command, for reference: `~/.fly/bin/fly deploy --app feed-me-noah-willow-grove-8052`.)

---

## Self-Review

**Spec coverage:**
- New `GET /u/{secret}/episodes` endpoint (whole feed, cap 20, voice, remaining, audio_url-when-ready, error-when-failed, 404 JSON, no internals) → Task 1. Covered.
- AGENTS.md: TL;DR, Step 0 persistence, no-guess/scan/probe rule, list endpoint documented, kept happy-path/errors/rate-limit/examples, no em-dash → Task 2. Covered.
- Prompt snippet persistence clause → Task 3. Covered.
- Tests (list, ready/failed, no-leak, bad secret, remaining, cap-20, copy guard) → Tasks 1-3. Covered.
- CHANGELOG entry + v3.12 tag, README route → Task 4. Covered.
- Out of scope (skill artifact, URL de-dupe, cookie/share path, claim code) → not implemented, as specified.

**Placeholder scan:** No TBD/TODO; every code and doc step shows the literal content.

**Type/name consistency:** New handler `list_episodes_api`; reuses existing `_agent_error`, `_agent_episodes_in_window`, `AGENT_DAILY_CAP`, `storage.list_episodes`, `storage.get_settings`, `storage.user_exists`, `storage.write_pending_episode`, `storage.ALLOWED_VOICES`, all confirmed present in `app.py`/`storage.py`. Test helpers `make_feed`, `wire_fake_pipeline`, `ARTICLE_HTML`, `FakeResponse` confirmed present in `tests/test_agent_api.py`. Base URL `https://test.local` matches the `client` fixture. Response field names (`feed_page`, `feed_url`, `voice`, `remaining`, `episodes[].slug/title/status/ts/audio_url/error`) are identical across the endpoint, the tests, and the AGENTS.md example.
