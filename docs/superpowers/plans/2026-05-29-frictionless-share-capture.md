# Frictionless Share Capture (v3.0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the per-user copy/paste Shortcut install with one generic Shortcut that opens `GET /share?url=…` in Safari, where a long-lived first-party cookie identifies the user.

**Architecture:** The entire ingest pipeline (fetch → TTS → RSS → storage) is untouched. We add (1) a session cookie set when you view your feed page, (2) a new `/share` route that reads that cookie and reuses the existing ingest flow, (3) a generic Shortcut + settings-page cleanup. The per-user `/u/{secret}/ingest` route and all copy/paste UI are **deleted** — no current users, no backward compat. The whole build is gated on a one-time on-device spike (Task 2) confirming "Open URLs" carries the Safari cookie.

**Tech Stack:** Python 3.12, FastAPI, Jinja2 templates, pytest (`uv run pytest`), deploy via `~/.fly/bin/fly deploy --app feed-me-noah-willow-grove-8052`. Spec: `docs/superpowers/specs/2026-05-29-frictionless-share-capture.html`.

---

## File Structure

```
feed-me/
  app.py                       # +cookie helper, +set cookie in settings(), +/share route, -ingest route
  templates/share.html         # NEW — confirmation/error/connect page (state switch)
  templates/settings.html      # drop paste flow + ingest-URL drawer + obsolete JS; update copy
  tests/conftest.py            # client fixture: base_url -> https so Secure cookies round-trip
  tests/test_app.py            # +cookie tests, +/share tests, +ingest-gone test; -5 obsolete ingest tests; update settings test
  CHANGELOG.md                 # v3.0 entry
```

The `/share` route, the cookie helper, and the deletion of `ingest_route` all live in `app.py` (the project keeps all routes in one file — follow that pattern). The confirmation UI is the one new file.

---

## Task 1: Session cookie — helper + set it on the feed page

**Files:**
- Modify: `/Users/noah/Desktop/feed-me/tests/conftest.py` (client fixture base_url)
- Modify: `/Users/noah/Desktop/feed-me/app.py` (constants + `set_session_cookie` + call in `settings()`)
- Test: `/Users/noah/Desktop/feed-me/tests/test_app.py`

- [ ] **Step 1: Make the test client use an https base_url**

The `client` fixture monkeypatches `APP_BASE_URL` to `https://test.local`, so `set_session_cookie` (Step 4) will emit a `Secure` cookie. `Secure` cookies are only sent back over https, and `TestClient`'s default base_url is `http://testserver`. Switch it to https so the cookie round-trips in tests.

In `/Users/noah/Desktop/feed-me/tests/conftest.py`, change the `client` fixture's return line:

```python
@pytest.fixture
def client(tmp_path, monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(app_module, "APP_BASE_URL", "https://test.local")
    return TestClient(app_module.app, base_url="https://testserver")
```

- [ ] **Step 2: Run the full suite to confirm the base_url change is harmless**

Run: `cd /Users/noah/Desktop/feed-me && uv run pytest -q`
Expected: PASS (same count as before — the scheme change doesn't affect existing assertions).

- [ ] **Step 3: Write the failing cookie tests**

Append to `/Users/noah/Desktop/feed-me/tests/test_app.py`:

```python
def test_settings_sets_session_cookie(client):
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]

    response = client.get(f"/u/{secret}")
    assert response.cookies.get("fm_session") == secret


def test_create_links_browser(client):
    # Following the redirect lands on GET /u/{secret}, which sets the cookie.
    response = client.post("/create")  # default: follows redirect
    assert response.status_code == 200
    assert client.cookies.get("fm_session")  # now in the client's jar
```

- [ ] **Step 4: Run them to verify they fail**

Run: `cd /Users/noah/Desktop/feed-me && uv run pytest tests/test_app.py::test_settings_sets_session_cookie tests/test_app.py::test_create_links_browser -v`
Expected: FAIL — `fm_session` cookie is not set yet.

- [ ] **Step 5: Add the cookie constants + helper, and set the cookie in `settings()`**

In `/Users/noah/Desktop/feed-me/app.py`, add these constants just after the existing `SHORTCUT_ICLOUD_URL` block (around line 66):

```python
COOKIE_NAME = "fm_session"
COOKIE_MAX_AGE = 60 * 60 * 24 * 365  # 1 year


def set_session_cookie(response, secret: str) -> None:
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
```

Then in the `settings()` route, build the response into a variable, set the cookie on it, and return it. Replace the existing `return templates.TemplateResponse(...)` at the end of `settings()` with:

```python
    response = templates.TemplateResponse(request, "settings.html", {
        "secret": secret,
        "current_voice": s["voice"],
        "voices": sorted(storage.ALLOWED_VOICES),
        "episodes": eps,
        "feed_url": feed_url,
        "ingest_url": ingest_url,
        "feed_host_and_path": feed_host_and_path,
        "shortcut_url": SHORTCUT_ICLOUD_URL,
    })
    set_session_cookie(response, secret)
    return response
```

(Leave `ingest_url` in place for now — Task 5 removes it along with the template that uses it.)

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd /Users/noah/Desktop/feed-me && uv run pytest tests/test_app.py::test_settings_sets_session_cookie tests/test_app.py::test_create_links_browser -v`
Expected: PASS.

- [ ] **Step 7: Run the full suite**

Run: `cd /Users/noah/Desktop/feed-me && uv run pytest -q`
Expected: PASS (all green).

- [ ] **Step 8: Commit**

```bash
cd /Users/noah/Desktop/feed-me && git add app.py tests/conftest.py tests/test_app.py && git commit -m "feat(app): set long-lived fm_session cookie on the feed page"
```

---

## Task 2: Spike gate — throwaway stub `/share` + on-device cookie test

This proves the one assumption the whole design rests on, before we build anything real. It **cannot** be tested in `TestClient` — it needs real Safari, the `Secure` flag, and the Shortcuts "Open URLs" path against prod. The stub added here is thrown away in Task 3.

**Files:**
- Modify: `/Users/noah/Desktop/feed-me/app.py` (temporary stub route)

- [ ] **Step 1: Add a throwaway stub `/share` route**

In `/Users/noah/Desktop/feed-me/app.py`, add (it will be replaced in Task 3):

```python
@app.get("/share", response_class=PlainTextResponse)
def share_spike(request: Request, url: str = ""):
    # SPIKE — throwaway. Confirms a Shortcut "Open URLs" navigation carries
    # the first-party fm_session cookie. Replaced by the real route in Task 3.
    secret = request.cookies.get(COOKIE_NAME)
    if secret:
        return f"cookie seen: yes (secret={secret[:8]}…) url={url!r}"
    return "cookie seen: no"
```

- [ ] **Step 2: Commit and deploy the spike**

```bash
cd /Users/noah/Desktop/feed-me && git add app.py && git commit -m "spike: stub /share to verify Open URLs carries the Safari cookie"
~/.fly/bin/fly deploy --app feed-me-noah-willow-grove-8052
```

- [ ] **Step 3: Build a one-action test Shortcut on your iPhone**

In the Shortcuts app: new Shortcut → add the **Open URLs** action → set the URL to `https://feed-me.xyz/share` (use your real `APP_BASE_URL` host). Name it "FM Spike". No share-sheet config needed for this test.

- [ ] **Step 4: ⛔ GATE — run the on-device test**

1. On your iPhone, open your feed page in **Safari** (`https://feed-me.xyz/u/<your-secret>`). This sets the cookie.
2. Run the "FM Spike" Shortcut.
3. Safari opens `/share` and shows either `cookie seen: yes (...)` or `cookie seen: no`.

**`yes` → green light, proceed to Task 3.**
**`no` → STOP. Do not build further.** Report back. Fallback options live in the spec §4: re-embed a token via "Get Contents of URL" (reintroduces a paste), or pivot to the email/messaging on-ramp. Either way we've spent ~15 minutes, not a full build.

---

## Task 3: Real `/share` route + `share.html` template

Replaces the spike stub with the production route and confirmation UI.

**Files:**
- Create: `/Users/noah/Desktop/feed-me/templates/share.html`
- Modify: `/Users/noah/Desktop/feed-me/app.py` (replace stub `share_spike` with real `share_route`)
- Test: `/Users/noah/Desktop/feed-me/tests/test_app.py`

- [ ] **Step 1: Create the confirmation template**

Create `/Users/noah/Desktop/feed-me/templates/share.html`:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Feed Me</title>
  <style>
    body {
      font-family: -apple-system, "Inter", "Helvetica Neue", system-ui, sans-serif;
      max-width: 480px; margin: 64px auto; padding: 0 24px;
      line-height: 1.5; color: #0a0a0a; background: #fff; text-align: center;
      -webkit-font-smoothing: antialiased;
    }
    .brand {
      font-size: 10px; color: #767676; text-transform: uppercase;
      letter-spacing: 0.14em; font-weight: 700; margin-bottom: 24px;
    }
    .emoji { font-size: 44px; line-height: 1; margin-bottom: 12px; }
    h1 { font-size: 22px; font-weight: 600; letter-spacing: -0.01em; margin: 0 0 8px; }
    p { font-size: 14px; color: #4a4a4a; margin: 8px 0; }
    .title { font-weight: 600; color: #0a0a0a; }
    .hint { font-size: 12px; color: #767676; margin-top: 18px; }
  </style>
</head>
<body>
  <div class="brand">Feed Me</div>
  {% if state == "added" %}
    <div class="emoji">🎧</div>
    <h1>Added to your feed</h1>
    <p class="title">{{ title }}</p>
    <p>It'll be ready in your podcast app in 1–2 minutes.</p>
    <p class="hint">You can close this tab.</p>
  {% elif state == "error" %}
    <div class="emoji">⚠️</div>
    <h1>Couldn't add that</h1>
    <p>{{ error }}</p>
    <p class="hint">Try sharing again.</p>
  {% else %}{# connect #}
    <div class="emoji">🔗</div>
    <h1>Link this browser first</h1>
    <p>This browser isn't connected to a Feed Me feed yet.</p>
    <p>Open your Feed Me page (the link you bookmarked) in this browser once, then share again.</p>
  {% endif %}
</body>
</html>
```

- [ ] **Step 2: Write the failing `/share` tests**

Append to `/Users/noah/Desktop/feed-me/tests/test_app.py`:

```python
def test_share_with_cookie_spawns_ingest(client, monkeypatch, fake_http, tmp_path):
    from tests.conftest import FakeResponse

    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]
    client.get(f"/u/{secret}")  # links this browser (sets fm_session)

    fake_http.responses["https://example.com/a"] = FakeResponse(
        status_code=200, text="<html><head><title>A</title></head></html>",
    )
    import ingest
    monkeypatch.setattr(ingest, "http_client", fake_http)

    calls = []

    def fake_spawn(url, secret_, data_dir, slug):
        calls.append((url, secret_, slug))

    import app as app_module
    monkeypatch.setattr(app_module, "spawn_ingest", fake_spawn)

    response = client.get("/share?url=https://example.com/a")
    assert response.status_code == 200
    assert "Added" in response.text
    assert len(calls) == 1
    assert calls[0][1] == secret

    import storage
    eps = storage.list_episodes(tmp_path, secret)
    assert any(e["status"] == "pending" for e in eps)


def test_share_without_cookie_shows_connect(client):
    # No /u/{secret} visit in this fresh client → no cookie.
    response = client.get("/share?url=https://example.com/a")
    assert response.status_code == 200
    assert "Link this browser" in response.text


def test_share_bad_url_writes_failed(client, tmp_path):
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]
    client.get(f"/u/{secret}")  # link browser

    response = client.get("/share?url=")
    assert response.status_code == 200
    assert "Couldn't add" in response.text

    import storage
    eps = storage.list_episodes(tmp_path, secret)
    failed = [e for e in eps if e["status"] == "failed"]
    assert len(failed) == 1


def test_share_stale_secret_shows_connect(client):
    # Cookie holds a secret whose dir no longer exists (post-rotation).
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]
    client.get(f"/u/{secret}")  # cookie = old secret
    # Rotate WITHOUT following the redirect, so the cookie still holds the OLD
    # secret while the on-disk dir moves to a new one.
    client.post(f"/u/{secret}/rotate", follow_redirects=False)

    response = client.get("/share?url=https://example.com/a")
    assert response.status_code == 200
    assert "Link this browser" in response.text
```

- [ ] **Step 3: Run them to verify they fail**

Run: `cd /Users/noah/Desktop/feed-me && uv run pytest tests/test_app.py -k share -v`
Expected: FAIL — the stub returns plain text ("cookie seen…"), not the new pages, and writes no episodes.

- [ ] **Step 4: Replace the spike stub with the real route**

In `/Users/noah/Desktop/feed-me/app.py`, delete the `share_spike` function (from Task 2) and add in its place:

```python
@app.get("/share", response_class=HTMLResponse)
def share_route(request: Request, url: str = ""):
    secret = request.cookies.get(COOKIE_NAME)
    if not secret or not storage.user_exists(DATA_DIR, secret):
        return templates.TemplateResponse(request, "share.html", {"state": "connect"})

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
            request, "share.html", {"state": "error", "error": error_msg},
        )

    # Quick title fetch so the confirmation page + pending row show the real
    # title (mirrors the old ingest route). On failure fetch_title returns None
    # and we fall back to the hostname.
    title = ingest.fetch_title(url)
    slug = storage.write_pending_episode(
        DATA_DIR, secret, source_url=url, title=title,
    )
    spawn_ingest(url, secret, DATA_DIR, slug)
    return templates.TemplateResponse(
        request, "share.html", {"state": "added", "title": title or hostname(url)},
    )
```

- [ ] **Step 5: Run the `/share` tests, then the full suite**

Run: `cd /Users/noah/Desktop/feed-me && uv run pytest tests/test_app.py -k share -v`
Expected: PASS (all four).

Run: `cd /Users/noah/Desktop/feed-me && uv run pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd /Users/noah/Desktop/feed-me && git add app.py templates/share.html tests/test_app.py && git commit -m "feat(app): real /share route + confirmation page, cookie-identified"
```

---

## Task 4: Delete the per-user `/u/{secret}/ingest` route

**Files:**
- Modify: `/Users/noah/Desktop/feed-me/app.py` (delete `ingest_route`)
- Test: `/Users/noah/Desktop/feed-me/tests/test_app.py` (delete 5 obsolete tests, add gone-test)

- [ ] **Step 1: Add a test asserting the route is gone**

Append to `/Users/noah/Desktop/feed-me/tests/test_app.py`:

```python
def test_old_ingest_route_gone(client):
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]
    # The per-user ingest route is deleted; the path no longer matches.
    response = client.get(f"/u/{secret}/ingest?url=")
    assert response.status_code == 404
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd /Users/noah/Desktop/feed-me && uv run pytest tests/test_app.py::test_old_ingest_route_gone -v`
Expected: FAIL — the route still exists and returns 400 for an empty url.

- [ ] **Step 3: Delete the `ingest_route` function from `app.py`**

In `/Users/noah/Desktop/feed-me/app.py`, delete the entire `@app.get("/u/{secret}/ingest")` route and its `ingest_route` function body (currently ~lines 159–190, from the decorator through `return {"ok": True}`).

- [ ] **Step 4: Delete the 5 obsolete ingest tests**

In `/Users/noah/Desktop/feed-me/tests/test_app.py`, delete these functions (they exercised the now-removed route):

- `test_ingest_returns_ok_quickly`
- `test_ingest_rejects_invalid_url`
- `test_ingest_404_for_unknown_user`
- `test_ingest_empty_url_writes_visible_failed_episode`
- `test_ingest_invalid_url_writes_visible_failed_episode`

(Their behaviors are now covered against `/share`: `test_share_with_cookie_spawns_ingest`, `test_share_bad_url_writes_failed`, `test_share_without_cookie_shows_connect`.)

- [ ] **Step 5: Run the suite**

Run: `cd /Users/noah/Desktop/feed-me && uv run pytest -q`
Expected: PASS — `test_old_ingest_route_gone` now passes (404) and the deleted tests are gone.

- [ ] **Step 6: Commit**

```bash
cd /Users/noah/Desktop/feed-me && git add app.py tests/test_app.py && git commit -m "feat(app): delete per-user /ingest route (replaced by /share)"
```

---

## Task 5: Settings page cleanup — drop the paste flow

**Files:**
- Modify: `/Users/noah/Desktop/feed-me/tests/test_app.py` (update `test_settings_renders_for_known_user`)
- Modify: `/Users/noah/Desktop/feed-me/templates/settings.html`
- Modify: `/Users/noah/Desktop/feed-me/app.py` (drop `ingest_url` from `settings()`)

- [ ] **Step 1: Update the settings render test**

In `/Users/noah/Desktop/feed-me/tests/test_app.py`, edit `test_settings_renders_for_known_user`. Remove the ingest-URL assertion and its comment:

```python
    # Ingest URL still appears in the page (for the auto-copy JS)
    assert f"/u/{secret}/ingest" in response.text
```

Replace it with:

```python
    # v3.0: no more paste flow — the ingest URL must NOT leak into the page
    assert f"/u/{secret}/ingest" not in response.text
    # v3.0: one-tap install copy
    assert "no copy/paste" in response.text
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd /Users/noah/Desktop/feed-me && uv run pytest tests/test_app.py::test_settings_renders_for_known_user -v`
Expected: FAIL — the page still contains the ingest URL and lacks the new copy.

- [ ] **Step 3: Update `templates/settings.html`**

(a) Replace the Step 2 "Install the iOS Shortcut" row (currently lines ~192–199) with this no-paste version (plain link, new copy):

```html
  <div class="step-row">
    <div class="step-num">2</div>
    <div class="step-body">
      <div class="title">Install the iOS Shortcut</div>
      <div class="desc">One tap — no copy/paste. The same Shortcut works for everyone; it knows it's you because this browser is linked to your feed.</div>
      <a class="btn-primary" href="{{ shortcut_url }}">Install Shortcut</a>
    </div>
  </div>
```

(b) Replace the "Share an article" Step 3 row (currently lines ~232–237) so the confirmation expectation matches the new flow:

```html
  <div class="step-row">
    <div class="step-num">3</div>
    <div class="step-body">
      <div class="title">Safari shows <strong>🎧 Added!</strong> right away</div>
      <div class="desc">The episode lands in your podcast app within 1–2 minutes.</div>
    </div>
  </div>
```

(c) Delete the entire "Ingest URL" block in the Settings drawer (currently lines ~270–273):

```html
      <div class="label">Ingest URL</div>
      <p>For re-pasting into the Shortcut later, or setting up another device. Step 1 already copied this for you.</p>
      <div class="url-pill" id="ingest-url">{{ ingest_url }}?url=</div>
      <button class="btn-secondary" type="button" onclick="copyIngestUrl()">Copy ingest URL</button>
```

(d) Replace the first `<script>` block (currently lines ~285–306, defining `INGEST_URL`, `SHORTCUT_URL`, `FEED_URL`, `installShortcut`, `copyFeedUrl`, `copyIngestUrl`) with just what's still used:

```html
  <script>
    var FEED_URL = {{ feed_url | tojson }};
    function copyFeedUrl() {
      try { navigator.clipboard.writeText(FEED_URL); } catch (e) {}
    }
  </script>
```

- [ ] **Step 4: Drop `ingest_url` from the `settings()` route**

In `/Users/noah/Desktop/feed-me/app.py`, in `settings()`, delete the line that builds it:

```python
    ingest_url = f"{APP_BASE_URL}/u/{secret}/ingest"
```

and remove the `"ingest_url": ingest_url,` entry from the `TemplateResponse` context dict (added in Task 1 Step 5). Leave `feed_host_and_path` and `shortcut_url` intact.

- [ ] **Step 5: Check the landing page for stale paste copy**

Run: `cd /Users/noah/Desktop/feed-me && grep -n "ingest\|paste\|clipboard" templates/landing.html`
Expected: no matches. If anything references pasting an ingest URL, simplify that copy to "Install the Shortcut (one tap)". If no matches, no change needed.

- [ ] **Step 6: Run the suite**

Run: `cd /Users/noah/Desktop/feed-me && uv run pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd /Users/noah/Desktop/feed-me && git add app.py templates/settings.html tests/test_app.py && git commit -m "ux(app): drop copy/paste install — one-tap generic Shortcut"
```

---

## Task 6: Publish the generic Shortcut, deploy, verify, release

**Files:** none in-repo except `CHANGELOG.md` (Shortcut is external; `SHORTCUT_ICLOUD_URL` is configured on Fly).

- [ ] **Step 1: Build the generic Shortcut**

In the Shortcuts app, create a new Shortcut:
1. Turn on **Show in Share Sheet** (in the Shortcut's settings/ⓘ) and set "Accept" to **URLs** (and Text, for share targets that pass text).
2. Add a **URL Encode** action; set its input to **Shortcut Input**.
3. Add an **Open URLs** action; set the URL to `https://feed-me.xyz/share?url=` immediately followed by the **Encoded Text** variable from step 2 (no space). Final URL reads: `https://feed-me.xyz/share?url=[Encoded Text]`.
4. Name it **Feed Me**.

This Shortcut contains **no secret** — it's identical for every user. URL-encoding the input keeps article URLs with their own `?`/`&` from corrupting the `url` query param.

- [ ] **Step 2: Publish it and grab the iCloud link**

Share the Shortcut → **Copy iCloud Link**. This is the generic install link for all users.

- [ ] **Step 3: Point `SHORTCUT_ICLOUD_URL` at the new Shortcut**

First check where it's configured:

```bash
cd /Users/noah/Desktop/feed-me && grep -n "SHORTCUT_ICLOUD_URL" fly.toml
```

- If it's set under `[env]` in `fly.toml`, update that value to the new iCloud link and it ships with the next deploy.
- If it's not in `fly.toml`, set it as a Fly secret:

```bash
~/.fly/bin/fly secrets set SHORTCUT_ICLOUD_URL="<paste-icloud-link>" --app feed-me-noah-willow-grove-8052
```

- [ ] **Step 4: Deploy**

```bash
cd /Users/noah/Desktop/feed-me && ~/.fly/bin/fly deploy --app feed-me-noah-willow-grove-8052
```

- [ ] **Step 5: ⛔ End-to-end verification on your iPhone**

1. Open your feed page in Safari (`https://feed-me.xyz/u/<your-secret>`) — links this browser. Confirm the page shows the one-tap install copy and **no** ingest URL anywhere.
2. Tap **Install Shortcut** → it installs in one tap, **no paste prompt**.
3. (Optional) Pin Feed Me to the top of the share sheet via the existing tip.
4. Open any article in Safari → Share → **Feed Me**.
5. Safari should flash a **🎧 Added!** page within a second or two.
6. Within 1–2 minutes the episode appears **Ready** in your podcast app.
7. Sanity-check the connect fallback: in a browser that has never opened your feed page (or after clearing cookies), running the Shortcut should show the "Link this browser first" page — not a crash.

If anything is off (no Added page, episode never appears, or the install still prompts for a paste), stop and report before tagging.

- [ ] **Step 6: Update CHANGELOG and tag v3.0**

Insert this entry at the top of `/Users/noah/Desktop/feed-me/CHANGELOG.md`:

```markdown
## v3.0 — 2026-05-29

Frictionless share capture:

- One **generic Shortcut** for everyone — installs in one tap, no copy/paste, no per-user secret baked in.
- New `GET /share?url=…` route identifies you by a long-lived first-party `fm_session` cookie (set whenever you view your feed page). Sharing opens Safari to an instant "🎧 Added!" confirmation.
- Rotating your secret no longer breaks the Shortcut — identity rides in the cookie, re-established by reopening your feed page.
- Removed the per-user `/u/{secret}/ingest` route and the entire copy/paste install flow (no backward compat — no current users).
- Spec: `docs/superpowers/specs/2026-05-29-frictionless-share-capture.html`
```

Then:

```bash
cd /Users/noah/Desktop/feed-me && git add CHANGELOG.md && git commit -m "release: v3.0 frictionless share capture" && git tag v3.0
```

---

## Self-Review

### Spec coverage

| Spec section | Implementing task |
|---|---|
| §2 New `GET /share` route | Task 3 (Step 4) |
| §2 Long-lived session cookie set on `GET /u/{secret}` | Task 1 (Steps 5) |
| §2 One generic Shortcut + settings cleanup | Task 5 (template/copy), Task 6 (Shortcut + env) |
| §2 Delete `/u/{secret}/ingest` | Task 4 |
| §2 Delete `ingest_url` var + clipboard JS + drawer block | Task 5 (Steps 3–4) |
| §3 Cookie lifecycle (set/refresh on feed page; attributes) | Task 1 (Step 5 helper) |
| §3 `/share` three branches (added / error / connect) | Task 3 (template Step 1 + route Step 4; tests Step 2) |
| §3 Stale-secret treated as no-cookie | Task 3 (`test_share_stale_secret_shows_connect`) |
| §3 The "Open URLs" cookie assumption | Task 2 (on-device spike gate) |
| §4 Spike first, gated | Task 2 |
| §5 Cookie helper + Secure-gating | Task 1 (Step 5) |
| §5 `/share` route code | Task 3 (Step 4 — matches spec sketch) |
| §5 `share.html` state switch | Task 3 (Step 1) |
| §5 settings.html changes (4 edits) | Task 5 (Step 3 a–d) |
| §5 `settings()` drops `ingest_url` | Task 5 (Step 4) |
| §6 New app tests (7) | Task 1 (2), Task 3 (4), Task 4 (1) |
| §6 Existing tests updated/removed | Task 4 (delete 5), Task 5 (update settings test) |
| §9 Acceptance: one-tap install, instant Added, generic Shortcut, connect fallback, rotation survives, /ingest 404, no ingest URL on page | Tasks 4–6 + Task 6 Step 5 manual checks |

All spec sections covered. Out-of-scope items (login/magic-link, email/messaging, native app, silent ingest) are correctly absent.

### Placeholder scan

Scanned for "TBD", "TODO", "fill in", "appropriate error handling", "similar to Task N", and bare "write tests". None present — every code step shows complete code, every command shows expected output. The two manual gates (Task 2 Step 4, Task 6 Step 5) are honestly labeled on-device checks, not code placeholders.

### Type / name consistency

- `COOKIE_NAME = "fm_session"` — consistent across helper (Task 1), route reads `request.cookies.get(COOKIE_NAME)` (Task 3), and all test assertions on `"fm_session"` (Tasks 1, 3).
- `set_session_cookie(response, secret)` — defined Task 1 Step 5, called once in `settings()` same step.
- `share.html` `state` values `"added" / "error" / "connect"` — produced by `share_route` (Task 3 Step 4) match the template's `{% if %}` branches (Task 3 Step 1).
- Template assertion strings — `"Added"`, `"Couldn't add"`, `"Link this browser"` in tests (Task 3 Step 2) match exact copy in `share.html` (Task 3 Step 1).
- `storage.write_failed_episode(... source_url=, error=)` and `storage.write_pending_episode(... source_url=, title=)` — signatures match existing usage in the old `ingest_route` (verified against `app.py`).
- `spawn_ingest(url, secret, data_dir, slug)` — monkeypatched in tests with the same 4-arg shape it's called with in `share_route`.
- The `fake_spawn` signature `(url, secret_, data_dir, slug)` matches the real `spawn_ingest` positional args.

No inconsistencies found.
