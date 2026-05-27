# Welcome Episode + Live Updates (v1.5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pre-seed a welcome episode on every new feed so podcast apps will accept the subscription, and live-update the settings page so friends see Pending → Ready transitions without manual refresh.

**Architecture:** Six tasks: one-time welcome MP3 generator (script + binary), `storage.seed_welcome_episode`, wire it into `POST /create`, extract the episode section into a Jinja partial + add a polling route, JS polling in `settings.html`, then deploy + tag v1.5.

**Tech Stack:** Same as v1.4 — OpenAI TTS for the welcome generation (same client/model the ingest pipeline uses), vanilla JS + native `fetch()` for polling. No new runtime deps. Spec: `docs/superpowers/specs/2026-05-26-welcome-episode-and-live-updates.html`.

---

## File Structure

```
feed-me/
  scripts/
    gen_welcome.py              # NEW — one-time TTS script
  static/
    welcome.mp3                 # NEW — committed binary (~50-100 KB)
  storage.py                    # +seed_welcome_episode
  app.py                        # +WELCOME_AUDIO_BYTES, +seed call in /create,
                                #  +/u/<secret>/episodes_partial route
  templates/
    _episodes_section.html      # NEW — partial extracted from settings.html
    settings.html               # uses include + JS polling block
  tests/
    test_storage.py             # +seed_welcome_episode tests
    test_app.py                 # update post_create + settings render tests,
                                #  add episodes_partial route tests
```

No new runtime dependencies. The OpenAI client is already a runtime dep used by ingest.

---

## Task 1: Generate `static/welcome.mp3`

**Files:**
- Create: `/Users/noah/Desktop/feed-me/scripts/gen_welcome.py`
- Create: `/Users/noah/Desktop/feed-me/static/welcome.mp3` (generated)

One-time tooling. No traditional TDD; verified by ear after running.

- [ ] **Step 1: Create the generator script**

Write `/Users/noah/Desktop/feed-me/scripts/gen_welcome.py` with this exact content:

```python
"""Generate the Feed Me welcome episode MP3 (~30s, OpenAI TTS, shimmer voice).

Run from project root with OPENAI_API_KEY set:
    OPENAI_API_KEY=sk-... uv run python scripts/gen_welcome.py

Writes: static/welcome.mp3

Re-run when the script text changes; commit both this script and the new
MP3 output together. Production never executes this — the MP3 is read
once at app startup and seeded into each new user's directory.
"""
import os
import sys
from pathlib import Path

from openai import OpenAI

OUTPUT = Path(__file__).parent.parent / "static" / "welcome.mp3"
SCRIPT = (
    "Welcome to Feed Me. This is your private podcast feed for articles you "
    "want to listen to instead of read. Open an article on your phone, tap "
    "the Share button, then tap Feed Me to send it to your feed. A new "
    "episode shows up here in about a minute. Enjoy!"
)


def main():
    client = OpenAI()
    response = client.audio.speech.create(
        model="tts-1",
        voice="shimmer",
        input=SCRIPT,
    )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(response.content)
    print(f"wrote {OUTPUT} ({OUTPUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    if not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY not set in environment", file=sys.stderr)
        sys.exit(1)
    main()
```

- [ ] **Step 2: Run the script**

```bash
cd /Users/noah/Desktop/feed-me && OPENAI_API_KEY=$OPENAI_API_KEY uv run python scripts/gen_welcome.py
```

If you don't have `OPENAI_API_KEY` exported, set it from your `.env` or paste inline. Expected: prints `wrote /Users/noah/Desktop/feed-me/static/welcome.mp3 (NN KB)`. File should be 30–200 KB. OpenAI TTS call costs ~$0.02 for this script length — trivial.

- [ ] **Step 3: Verify the file**

```bash
file /Users/noah/Desktop/feed-me/static/welcome.mp3
```

Expected: `MPEG ADTS, layer III, ...` or similar (real MP3).

Optionally play it:

```bash
afplay /Users/noah/Desktop/feed-me/static/welcome.mp3
```

Verify by ear that the audio matches the script text. If the voice mispronounces "Feed Me" or any other word weirdly, regenerate with a different voice (change `voice="shimmer"` to `"alloy"`, `"nova"`, or `"echo"`).

- [ ] **Step 4: Commit script + MP3**

```bash
cd /Users/noah/Desktop/feed-me && git add scripts/gen_welcome.py static/welcome.mp3 && git commit -m "feat: generate welcome episode MP3 (OpenAI TTS, shimmer voice)

- scripts/gen_welcome.py: one-time TTS generator
- static/welcome.mp3: committed binary (~NN KB)
- production reads bytes at startup and seeds per-user (next task)"
```

---

## Task 2: `storage.seed_welcome_episode`

**Files:**
- Modify: `/Users/noah/Desktop/feed-me/storage.py`
- Modify: `/Users/noah/Desktop/feed-me/tests/test_storage.py`

- [ ] **Step 1: Append the failing test to `/Users/noah/Desktop/feed-me/tests/test_storage.py`**

```python
def test_seed_welcome_episode_writes_mp3_and_json(tmp_path):
    secret = storage.create_user(tmp_path)

    slug = storage.seed_welcome_episode(
        tmp_path, secret, welcome_audio=b"FAKEMP3",
    )

    assert (tmp_path / secret / f"{slug}.mp3").read_bytes() == b"FAKEMP3"
    meta = json.loads((tmp_path / secret / f"{slug}.json").read_text())
    assert meta["title"] == "Welcome to Feed Me"
    assert meta["url"] == "https://feed-me.xyz"
    assert isinstance(meta["ts"], int)
    assert "error" not in meta
    assert "pending" not in meta


def test_seed_welcome_episode_appears_in_list_as_ready(tmp_path):
    secret = storage.create_user(tmp_path)
    storage.seed_welcome_episode(tmp_path, secret, welcome_audio=b"X")

    eps = storage.list_episodes(tmp_path, secret)

    assert len(eps) == 1
    assert eps[0]["title"] == "Welcome to Feed Me"
    assert eps[0]["status"] == "ready"
```

- [ ] **Step 2: Run, verify the tests FAIL**

```bash
cd /Users/noah/Desktop/feed-me && uv run pytest tests/test_storage.py -v -k "seed_welcome"
```

Expected: FAIL with `AttributeError: module 'storage' has no attribute 'seed_welcome_episode'`.

- [ ] **Step 3: Implement in `/Users/noah/Desktop/feed-me/storage.py`**

Add this function after `write_pending_episode` (or wherever the writer functions live):

```python
def seed_welcome_episode(
    data_dir: Path, secret: str, *,
    welcome_audio: bytes,
) -> str:
    """Write a pre-rendered welcome episode (mp3 + json) into a new user's dir.

    Returns the slug. Unlike write_episode, the title and URL are fixed since
    the welcome is identical for every user.
    """
    slug = _new_slug()
    user_dir = data_dir / secret
    (user_dir / f"{slug}.mp3").write_bytes(welcome_audio)
    (user_dir / f"{slug}.json").write_text(json.dumps({
        "title": "Welcome to Feed Me",
        "url": "https://feed-me.xyz",
        "ts": int(time.time()),
    }))
    return slug
```

- [ ] **Step 4: Run all storage tests, verify they pass**

```bash
cd /Users/noah/Desktop/feed-me && uv run pytest tests/test_storage.py -v
```

Expected: all tests pass (21 total — 19 from v1.3 + 2 new).

- [ ] **Step 5: Commit**

```bash
cd /Users/noah/Desktop/feed-me && git add storage.py tests/test_storage.py && git commit -m "feat(storage): seed_welcome_episode writes the canonical welcome into a user dir"
```

---

## Task 3: Wire welcome seeding into `POST /create`

**Files:**
- Modify: `/Users/noah/Desktop/feed-me/app.py`
- Modify: `/Users/noah/Desktop/feed-me/tests/test_app.py`

- [ ] **Step 1: Update the existing `test_post_create_makes_user_dir` in `/Users/noah/Desktop/feed-me/tests/test_app.py`**

Find the existing function and REPLACE with:

```python
def test_post_create_makes_user_dir(client, tmp_path):
    response = client.post("/create", follow_redirects=False)
    secret = response.headers["location"].split("/u/")[1]

    # Settings file exists
    assert (tmp_path / secret / "settings.json").exists()

    # Welcome episode seeded: exactly one mp3 + one episode json
    user_dir = tmp_path / secret
    mp3s = list(user_dir.glob("*.mp3"))
    episode_jsons = [p for p in user_dir.glob("*.json") if p.name != "settings.json"]
    assert len(mp3s) == 1, f"expected 1 welcome mp3, found {len(mp3s)}"
    assert len(episode_jsons) == 1, f"expected 1 welcome json, found {len(episode_jsons)}"

    import json
    meta = json.loads(episode_jsons[0].read_text())
    assert meta["title"] == "Welcome to Feed Me"
```

Also find `test_settings_renders_for_known_user` and add a `"Welcome to Feed Me"` assertion. Replace it with:

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
    # v1.5: welcome episode pre-seeded on /create
    assert "Welcome to Feed Me" in response.text
```

- [ ] **Step 2: Run the updated tests, verify they FAIL**

```bash
cd /Users/noah/Desktop/feed-me && uv run pytest tests/test_app.py -v -k "post_create_makes_user_dir or settings_renders_for_known_user"
```

Expected: both fail. The first because no welcome MP3 is seeded; the second because the welcome title isn't on the page.

- [ ] **Step 3: Update `/Users/noah/Desktop/feed-me/app.py`**

Near the top, after `STATIC_DIR = Path(__file__).parent / "static"`, add:

```python
WELCOME_AUDIO_BYTES = (STATIC_DIR / "welcome.mp3").read_bytes()
```

This reads the file once at module import. If the file is missing, import fails loudly — that's the right behavior.

Find the existing `create` route and replace with:

```python
@app.post("/create")
def create():
    secret = storage.create_user(DATA_DIR)
    storage.seed_welcome_episode(
        DATA_DIR, secret, welcome_audio=WELCOME_AUDIO_BYTES,
    )
    return RedirectResponse(f"/u/{secret}", status_code=303)
```

- [ ] **Step 4: Run the full test suite, verify all tests pass**

```bash
cd /Users/noah/Desktop/feed-me && uv run pytest -v 2>&1 | tail -10
```

Expected: all tests pass. The welcome seeding adds one episode to every user dir created via the HTTP route, but storage-level tests (which use `storage.create_user` directly without going through HTTP) are unaffected because they don't call the seed function.

- [ ] **Step 5: Commit**

```bash
cd /Users/noah/Desktop/feed-me && git add app.py tests/test_app.py && git commit -m "feat(app): seed welcome episode on POST /create

Module loads static/welcome.mp3 once into WELCOME_AUDIO_BYTES.
POST /create now calls storage.seed_welcome_episode after creating
the user, so the feed has one playable episode from the moment it
exists. Solves the 'empty feed' problem where podcast apps refuse
to subscribe."
```

---

## Task 4: Extract `_episodes_section.html` partial + add `GET /u/<secret>/episodes_partial` route

**Files:**
- Create: `/Users/noah/Desktop/feed-me/templates/_episodes_section.html`
- Modify: `/Users/noah/Desktop/feed-me/templates/settings.html`
- Modify: `/Users/noah/Desktop/feed-me/app.py`
- Modify: `/Users/noah/Desktop/feed-me/tests/test_app.py`

The partial extraction is a pure refactor; the new route renders the partial via a polling-friendly endpoint.

- [ ] **Step 1: Append failing tests to `/Users/noah/Desktop/feed-me/tests/test_app.py`**

```python
def test_episodes_partial_returns_html(client):
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]

    response = client.get(f"/u/{secret}/episodes_partial")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    # Welcome was seeded on /create, so partial shows it
    assert "Welcome to Feed Me" in response.text
    # Outer section structure (h2 header + table or empty state)
    assert "Recent episodes" in response.text


def test_episodes_partial_404_for_unknown_user(client):
    response = client.get("/u/nope/episodes_partial")
    assert response.status_code == 404


def test_episodes_partial_reflects_new_pending_episode(client, tmp_path):
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]

    import storage
    storage.write_pending_episode(tmp_path, secret,
                                   source_url="https://example.com/p")

    response = client.get(f"/u/{secret}/episodes_partial")
    # Partial picks up the newly-written pending episode
    assert "Pending" in response.text
    assert "example.com/p" in response.text
```

- [ ] **Step 2: Run, verify the tests FAIL**

```bash
cd /Users/noah/Desktop/feed-me && uv run pytest tests/test_app.py -v -k "episodes_partial"
```

Expected: 3 FAIL — `404 != 200` for the first and third (no route registered), and `404 != 404` semantically OK for the second but it'd actually return 404 from FastAPI's default unmatched-path 404, which happens to be the right status; verify by reading the failure output. (If `test_episodes_partial_404_for_unknown_user` passes incidentally, that's fine.)

- [ ] **Step 3: Create `/Users/noah/Desktop/feed-me/templates/_episodes_section.html`**

Copy these lines verbatim from `templates/settings.html` (the existing "Recent episodes" block) into a new file:

```html
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
```

- [ ] **Step 4: Replace the inline block in `/Users/noah/Desktop/feed-me/templates/settings.html` with the include**

Find the existing `<h2>Recent episodes</h2>` block (the same content you just put in the partial). Replace it with:

```html
<div id="episodes-section">
  {% include "_episodes_section.html" %}
</div>
```

- [ ] **Step 5: Add the route to `/Users/noah/Desktop/feed-me/app.py`**

Add this route near the existing `settings` route:

```python
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
```

- [ ] **Step 6: Run all tests, verify they pass**

```bash
cd /Users/noah/Desktop/feed-me && uv run pytest -v 2>&1 | tail -10
```

Expected: all tests pass — the existing `test_settings_renders_for_known_user`, `test_settings_lists_recent_episodes`, and `test_settings_shows_pending_episode` continue to work because the included partial renders the same content; the new `episodes_partial` tests pass against the new route.

- [ ] **Step 7: Commit**

```bash
cd /Users/noah/Desktop/feed-me && git add templates/_episodes_section.html templates/settings.html app.py tests/test_app.py && git commit -m "refactor(app): extract episode section to partial + add polling endpoint

- templates/_episodes_section.html: shared partial for the episode table
  + empty state. Single source of truth for episode-row markup.
- settings.html wraps the include in <div id='episodes-section'> so JS
  polling (next task) can swap it in place.
- GET /u/<secret>/episodes_partial renders just the partial with the
  user's current episodes (with relative-time enrichment).
- All existing settings-page tests continue to pass."
```

---

## Task 5: JS polling in `settings.html`

**Files:**
- Modify: `/Users/noah/Desktop/feed-me/templates/settings.html`

No new tests — the polling is JS that we'll verify by deploying and watching it work. Existing tests are unaffected.

- [ ] **Step 1: Add the polling script to `/Users/noah/Desktop/feed-me/templates/settings.html`**

Find the existing `<script>` block (the one that defines `installShortcut`, `copyFeedUrl`, `copyIngestUrl`). Append this block IMMEDIATELY AFTER the existing script's closing `</script>`:

```html
<script>
  // Live updates: poll /u/<secret>/episodes_partial every 3s
  (function () {
    var POLL_MS = 3000;
    var target = document.getElementById("episodes-section");
    if (!target) return;
    var url = window.location.pathname + "/episodes_partial";

    function refresh() {
      if (document.hidden) return;
      fetch(url, { cache: "no-store" })
        .then(function (resp) {
          if (!resp.ok) return null;
          return resp.text();
        })
        .then(function (html) {
          if (html != null) target.innerHTML = html;
        })
        .catch(function () { /* silent — page still works */ });
    }

    setInterval(refresh, POLL_MS);
    document.addEventListener("visibilitychange", function () {
      if (!document.hidden) refresh();
    });
  })();
</script>
```

This is wrapped in an IIFE to keep `target`, `url`, and `refresh` out of the global scope.

- [ ] **Step 2: Run the full test suite to confirm no regressions**

```bash
cd /Users/noah/Desktop/feed-me && uv run pytest -v 2>&1 | tail -5
```

Expected: all tests still pass. JS doesn't run during request-level tests.

- [ ] **Step 3: Local sanity check**

```bash
cd /Users/noah/Desktop/feed-me && uv run uvicorn app:app --port 8000
```

In another terminal:

```bash
curl -s -X POST http://localhost:8000/create -o /dev/null -w "%{redirect_url}\n"
```

Open the printed URL in a browser. Open DevTools → Network tab → filter "episodes_partial". You should see a request firing every ~3 seconds. Switch tabs away (DevTools → Sources tab works since the page is in the background) and confirm requests stop. Switch back and confirm they resume.

Kill the local server with Ctrl+C.

- [ ] **Step 4: Commit**

```bash
cd /Users/noah/Desktop/feed-me && git add templates/settings.html && git commit -m "feat(app): live-poll episode section every 3s

3-second polling via fetch() while document.hidden is false. On
visibility resume, immediately fetch once. Skip when hidden to avoid
needless requests in background tabs.

Friend taps Share → returns to settings page → sees Pending row appear
within ~3s without manual refresh, then Ready chip ~30-60s later."
```

---

## Task 6: Deploy v1.5 + tag

**Files:** none (deploy + CHANGELOG + tag)

- [ ] **Step 1: Deploy**

```bash
~/.fly/bin/fly deploy --app feed-me-noah-willow-grove-8052
```

Expected: build succeeds. The new `static/welcome.mp3` is included automatically via the existing `COPY . .` in the Dockerfile.

- [ ] **Step 2: Verify the welcome episode appears for new users**

```bash
SECRET=$(curl -s -X POST https://feed-me.xyz/create -o /dev/null -w "%{redirect_url}" | sed 's|.*/u/||') ; \
echo "test user: $SECRET" ; \
echo "==settings page contains welcome==" ; \
curl -s "https://feed-me.xyz/u/$SECRET" | grep -o "Welcome to Feed Me" | head -1 ; \
echo "==feed.xml contains welcome item==" ; \
curl -s "https://feed-me.xyz/u/$SECRET/feed.xml" | grep -o "<title>Welcome to Feed Me</title>" | head -1
```

Expected: both `grep` commands match.

- [ ] **Step 3: Verify the polling endpoint works**

```bash
curl -s "https://feed-me.xyz/u/$SECRET/episodes_partial" | grep -oE "(Recent episodes|Welcome to Feed Me)" | sort -u
```

Expected: both `Recent episodes` and `Welcome to Feed Me` appear.

- [ ] **Step 4: iPhone visual + Apple Podcasts verification**

On your iPhone:

1. Visit `https://feed-me.xyz/u/<your-real-secret>` in Safari (or use a fresh test account)
2. Tap **Add to Apple Podcasts**
3. In Podcasts, tap **Follow** — confirm the button enables and the show subscribes successfully (this was the original blocker)
4. Tap the show → tap the "Welcome to Feed Me" episode → confirm it plays the narrated script

Then test live updates:

1. Settings page open in Safari
2. Share an article from another tab via the Feed Me shortcut
3. Switch back to the settings page (don't refresh)
4. Within ~3 seconds, a new row should appear with "Pending" chip
5. ~30-60s later, it should flip to "Ready" — again, without manual refresh

If polling stops on tab switch and resumes on return, the feature is working as designed.

- [ ] **Step 5: Update CHANGELOG and tag v1.5**

Insert this entry at the top of `/Users/noah/Desktop/feed-me/CHANGELOG.md` (above the v1.4 entry):

```markdown
## v1.5 — 2026-05-27

First-run smoothness:

- Pre-seeded "Welcome to Feed Me" episode (~30s AI-narrated MP3) on every new feed, so podcast apps can subscribe even before the user has shared any articles
- Settings page now polls `/u/<secret>/episodes_partial` every 3s while tab is visible — new shares show up as "Pending" then "Ready" without manual refresh (~6s total perceived latency)
- Episode section extracted to a Jinja partial so the polling endpoint and the main settings render share one source of truth
- Spec: `docs/superpowers/specs/2026-05-26-welcome-episode-and-live-updates.html`
```

Then:

```bash
cd /Users/noah/Desktop/feed-me && git add CHANGELOG.md && git commit -m "release: v1.5 welcome episode + live updates" && git tag v1.5
```

---

## Self-Review

### Spec coverage

| Spec section | Implementing task |
|---|---|
| §3 Welcome script (verbatim text) | Task 1 (SCRIPT constant matches spec exactly) |
| §3 Welcome generation via OpenAI TTS, shimmer voice | Task 1 |
| §3 `seed_welcome_episode` storage function | Task 2 |
| §3 Module-level WELCOME_AUDIO_BYTES + /create wires the seed | Task 3 |
| §3 Rotate URL keeps existing welcome (no special handling) | Implicit — no rotate changes |
| §4 Extract partial, settings.html includes it | Task 4 step 3-4 |
| §4 GET /u/<secret>/episodes_partial route | Task 4 step 5 |
| §4 3s polling, fetch, swap innerHTML, Page Visibility API | Task 5 |
| §5 New files + modified files list | Tasks 1-5 cover all listed files |
| §5 Test data dir gotcha (storage-level tests unaffected) | Implicit — tests use storage.create_user directly without seeding |
| §6 Storage tests (seed_welcome_episode) | Task 2 |
| §6 App tests (post_create updated + settings render updated + new episodes_partial tests) | Task 3 (existing updates) + Task 4 (new tests) |
| §9 Acceptance criteria | Tasks 1-6 collectively satisfy all |
| §9 "Subscribing to that feed in Apple Podcasts succeeds" | Task 6 step 4 |

All sections covered.

### Placeholder scan

Scanned for "TBD", "TODO", "fill in", "implement later", "appropriate error handling", "similar to Task N". None found. Every code block is complete. Every command has expected output. The `NN KB` in T1 step 2 is intentional — it's a placeholder for the actual file size the engineer will see, not a TODO.

### Type consistency

- `seed_welcome_episode(data_dir, secret, *, welcome_audio: bytes) -> str` — signature used in Task 2 implementation, Task 2 tests, and Task 3 app.py call. Consistent.
- `WELCOME_AUDIO_BYTES` — module-level constant named consistently in Task 3 declaration and call site.
- `episodes_partial` — route name consistent across Task 4 implementation and Task 5 JS URL construction.
- `#episodes-section` — div ID consistent in Task 4 template wrapping and Task 5 JS lookup.
- Title text `"Welcome to Feed Me"` — consistent across Task 1 script, Task 2 seed function, Task 2 tests, and Task 3 test assertion.
- URL field `"https://feed-me.xyz"` — consistent for the welcome's source URL.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-27-welcome-episode-and-live-updates.md`.

Six tasks: one TTS generation, one storage function, one /create wiring, one partial extraction + route, one JS polling block, one deploy. Estimated ~35 minutes of focused subagent work plus a manual iPhone re-subscribe at the end.
