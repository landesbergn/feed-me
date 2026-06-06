# For Agents UI (v3.7) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the agent prompt to a dedicated `/u/{secret}/agents` page reached by an always-visible card on the feed page, advertise the capability on the landing page with a CSS robot, and trim the prompt copy.

**Architecture:** One new GET route + template (`agents_page.html`), a tiny shared partial (`_agents_card.html`) included in both feed-page states, removal of the v3.6 fold from `settings.html`, and a pure-CSS decorative robot in `landing.html`. No API or storage changes.

**Tech Stack:** FastAPI + Jinja2 (existing), pytest with the `client` fixture (existing). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-06-06-for-agents-ui.html` (the contract).

**Branch:** work on `for-agents-ui` (already created from `main`).

---

## File structure

| File | Change | Responsibility |
|------|--------|----------------|
| `app.py` | Modify | New `agents_page` route (`GET /u/{secret}/agents`) |
| `templates/agents_page.html` | Create | The personalized prompt page (click-to-copy box) |
| `templates/_agents_card.html` | Create | The "Your agent can share here too" step card |
| `templates/settings.html` | Modify | Remove v3.6 fold + its CSS/JS; include the card in both states |
| `templates/landing.html` | Modify | Robot + bubble over step 2 |
| `tests/test_agent_api.py` | Modify | New page tests; rewrite the v3.6 settings-section test; landing test |
| `README.md`, `CHANGELOG.md` | Modify | Reworded bullet + route row; v3.7 entry |

Conventions that apply throughout:

- `client` fixture: `app.DATA_DIR` → tmp_path, `app.APP_BASE_URL` → `https://test.local`.
- Tests never hit the network. `make_feed`, `wire_fake_pipeline`, `ARTICLE_HTML`, and `FakeResponse` already exist at the top of `tests/test_agent_api.py`.
- NO EM-DASHES in templates or copy (`→` and `←` arrows are fine; they are not em-dashes). After template changes run `grep -rn "—" templates/` and expect empty.
- Current suite: 187 passed. Expected after this plan: 193.

---

### Task 1: The agents page (`GET /u/{secret}/agents`)

**Files:**
- Create: `templates/agents_page.html`
- Modify: `app.py` (new route after `episode_status_api`)
- Test: `tests/test_agent_api.py`

- [ ] **Step 1: Write the failing tests** (append to `tests/test_agent_api.py`):

```python
def test_agents_page_renders_personalized_prompt(client):
    secret = make_feed(client)

    resp = client.get(f"/u/{secret}/agents")

    assert resp.status_code == 200
    assert "Agents welcome." in resp.text
    assert "I have a Feed Me podcast feed" in resp.text
    assert f"My feed page: https://test.local/u/{secret}." in resp.text
    assert "https://test.local/AGENTS.md" in resp.text
    assert "click to copy" in resp.text
    assert f"/u/{secret}" in resp.text                      # back link
    assert "fm_session" in resp.headers.get("set-cookie", "")


def test_agents_page_unknown_feed_404(client):
    resp = client.get("/u/doesnotexist/agents")
    assert resp.status_code == 404


def test_agents_page_prompt_omits_removed_copy(client):
    secret = make_feed(client)

    resp = client.get(f"/u/{secret}/agents")

    assert "5 episodes" not in resp.text          # cap detail lives in AGENTS.md only
    assert "Keep this private" not in resp.text
    assert "Claude Code and friends" not in resp.text


def test_agents_page_records_page_view(client, tmp_path):
    secret = make_feed(client)

    client.get(f"/u/{secret}/agents")

    db = tmp_path / "_analytics" / "analytics.db"
    views = [e for e in analytics.all_events(db)
             if e["event"] == "page_view" and e["path"] == "agents_page"]
    assert len(views) == 1
    assert views[0]["feed_hash"] == analytics.feed_hash(secret)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_agent_api.py -k agents_page -v`
Expected: all 4 FAIL (404 where 200 expected; the 404 test fails because FastAPI's default 404 happens to pass — check it asserts only the status, so it may already pass; the other three FAIL).

- [ ] **Step 3: Create `templates/agents_page.html`** with exactly this content:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Feed Me · for agents</title>
  <link rel="icon" href="/favicon.ico" sizes="any">
  <link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png">
  <link rel="apple-touch-icon" href="/apple-touch-icon.png">
  <style>
    :root {
      --bg: #FFF8F2; --ink: #2a1f18; --accent: #b04a00;
      --muted: #8a6f5e; --faint: #b89a84; --card: #ffffff;
      --hair: #EFE2D6;
      --round: ui-rounded, "SF Pro Rounded", -apple-system, system-ui, sans-serif;
      --sans: -apple-system, "Helvetica Neue", system-ui, sans-serif;
    }
    * { box-sizing: border-box; }
    body {
      font-family: var(--sans);
      max-width: 480px; margin: 44px auto; padding: 0 22px 64px;
      line-height: 1.5; color: var(--ink); background: var(--bg);
      -webkit-font-smoothing: antialiased;
    }
    .brand {
      font-family: var(--round); font-size: 12px; font-weight: 800;
      letter-spacing: .08em; text-transform: uppercase; color: var(--accent);
      margin-bottom: 18px;
    }
    h1 {
      font-family: var(--round); font-size: 28px; font-weight: 800;
      letter-spacing: -.01em; line-height: 1.12; margin: 0 0 14px;
    }
    p { font-size: 15px; margin: 0 0 16px; }
    .prompt-box {
      background: var(--card); border: 1.5px solid #E9C9AC; border-radius: 16px;
      padding: 14px 16px; cursor: pointer; user-select: none;
      box-shadow: 0 1px 0 #F3E6D9, 0 6px 16px rgba(176, 74, 0, .05);
    }
    .prompt-box .text {
      font-family: ui-monospace, "SF Mono", Menlo, monospace;
      font-size: 13px; line-height: 1.55; overflow-wrap: anywhere;
    }
    .prompt-box .hint { font-size: 12px; color: var(--faint); margin-top: 10px; font-weight: 600; }
    .api-link { font-size: 14px; margin-top: 22px; }
    a { color: var(--accent); font-weight: 700; text-decoration: none; }
    a:hover { text-decoration: underline; }
    .back { display: block; margin-top: 36px; font-size: 13px; }
  </style>
</head>
<body>
  <div class="brand">🎧 Feed Me</div>
  <h1>Agents welcome.</h1>
  <p>Give your agent this prompt and it can add articles to your feed:</p>

  <div class="prompt-box" id="prompt-box" role="button" tabindex="0"
       onclick="copyPrompt()" onkeydown="promptKey(event)">
    <div class="text" id="prompt-text">I have a Feed Me podcast feed. To send an article to it, read {{ base_url }}/AGENTS.md and follow it. My feed page: {{ base_url }}/u/{{ secret }}.</div>
    <div class="hint" id="copy-hint">⧉ click to copy</div>
  </div>

  <p class="api-link">The full API, for your agent's eyes: <a href="{{ base_url }}/AGENTS.md">{{ base_url }}/AGENTS.md</a></p>

  <a class="back" href="/u/{{ secret }}">← Back to your feed</a>

  <script>
    function copyPrompt() {
      var text = document.getElementById("prompt-text").textContent.trim();
      try {
        navigator.clipboard.writeText(text);
        var hint = document.getElementById("copy-hint");
        hint.textContent = "copied!";
        setTimeout(function () { hint.textContent = "⧉ click to copy"; }, 1500);
      } catch (e) {}
    }
    function promptKey(e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); copyPrompt(); }
    }
  </script>
</body>
</html>
```

- [ ] **Step 4: Add the route to `app.py`**, directly after `episode_status_api`:

```python
@app.get("/u/{secret}/agents", response_class=HTMLResponse)
def agents_page(request: Request, secret: str):
    """Human-facing page holding the personalized agent prompt."""
    if not storage.user_exists(DATA_DIR, secret):
        raise HTTPException(404)
    _track("page_view", secret=secret, path="agents_page")
    response = templates.TemplateResponse(request, "agents_page.html", {
        "secret": secret,
        "base_url": APP_BASE_URL,
    })
    set_session_cookie(response, secret)
    return response
```

(`HTMLResponse`, `HTTPException`, `set_session_cookie`, `_track`, and `templates` already exist in `app.py`. No route conflict: `/u/{secret}/agents` has a distinct literal segment vs `/u/{secret}/episodes/...` and `/u/{secret}/audio/...`.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_agent_api.py -v`
Expected: 26 passed (22 prior + 4 new).

Then: `uv run pytest -q`
Expected: 191 passed.

- [ ] **Step 6: Commit**

```bash
git add templates/agents_page.html app.py tests/test_agent_api.py
git commit -m "feat: personalized agents page at /u/{secret}/agents"
```

---

### Task 2: Feed page card replaces the v3.6 fold

**Files:**
- Create: `templates/_agents_card.html`
- Modify: `templates/settings.html`
- Test: `tests/test_agent_api.py`

- [ ] **Step 1: Rewrite the v3.6 settings test and add the post-setup test**

In `tests/test_agent_api.py`, REPLACE the whole `test_settings_page_shows_for_agents_section` function with:

```python
def test_settings_page_links_to_agents_page(client):
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]

    resp = client.get(f"/u/{secret}")

    assert resp.status_code == 200
    assert "Your agent can share here too" in resp.text
    assert f"/u/{secret}/agents" in resp.text
    # The prompt moved to the agents page; it must be gone from here.
    assert "I have a Feed Me podcast feed" not in resp.text


def test_settings_page_agents_card_shows_after_setup(client, monkeypatch, fake_http, fake_openai):
    """The card renders in BOTH page states; this covers the episodes-leading
    (setup_done) state, the other test covers the fresh-feed state."""
    secret = make_feed(client)
    fake_http.responses["https://example.com/a"] = FakeResponse(
        status_code=200, text=ARTICLE_HTML,
    )
    wire_fake_pipeline(monkeypatch, fake_http, fake_openai)
    client.post(f"/u/{secret}/episodes", json={"url": "https://example.com/a"})

    resp = client.get(f"/u/{secret}")

    assert "Your agent can share here too" in resp.text
    assert f"/u/{secret}/agents" in resp.text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_agent_api.py -k "links_to_agents or card_shows" -v`
Expected: both FAIL (`"Your agent can share here too" not in resp.text`).

- [ ] **Step 3: Create `templates/_agents_card.html`** with exactly this content:

```html
<div class="step">
  <div class="n">🤖</div>
  <div class="body">
    <div class="t">Your agent can share here too</div>
    <a class="btn-secondary" href="/u/{{ secret }}/agents">For agents →</a>
  </div>
</div>
```

- [ ] **Step 4: Edit `templates/settings.html`** (three removals, two includes):

a. REMOVE the whole "For agents" details block (everything from `<details class="settings">` with `<summary>For agents</summary>` through its closing `</details>`, currently right before the `<script>` that defines `FEED_URL`).

b. REMOVE the `.agent-prompt` CSS rule from the `<style>` block (the rule added in v3.6 next to `.voices`).

c. REMOVE the `copyAgentPrompt` function from the script that defines `copyFeedUrl` (keep `copyFeedUrl` itself).

d. ADD `{% include "_agents_card.html" %}` in BOTH branches of the `{% if setup_done %}`, directly after the `<div id="episodes-section">...</div>` element:

```html
  {% if setup_done %}
    <div id="episodes-section">
      {% include "_episodes_section.html" %}
    </div>
    {% include "_agents_card.html" %}

    <details class="setup-fold">
      ...
    </details>
  {% else %}
    {% include "_setup_instructions.html" %}

    <div id="episodes-section">
      {% include "_episodes_section.html" %}
    </div>
    {% include "_agents_card.html" %}
  {% endif %}
```

- [ ] **Step 5: Run the tests, then the em-dash grep**

Run: `uv run pytest tests/test_agent_api.py -v`
Expected: 27 passed (the rewritten test + the new one; the old name is gone).

Run: `grep -rn "—" templates/`
Expected: no output (exit 1).

Then: `uv run pytest -q`
Expected: 192 passed.

- [ ] **Step 6: Commit**

```bash
git add templates/_agents_card.html templates/settings.html tests/test_agent_api.py
git commit -m "feat: agents card on the feed page; prompt fold removed"
```

---

### Task 3: The landing page robot

**Files:**
- Modify: `templates/landing.html`
- Test: `tests/test_agent_api.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_agent_api.py`):

```python
def test_landing_page_advertises_agents(client):
    resp = client.get("/")

    assert resp.status_code == 200
    assert "or have your AI agent send things" in resp.text
    assert "/AGENTS.md" in resp.text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_agent_api.py -k landing -v`
Expected: FAIL (`"or have your AI agent send things" not in resp.text`).

- [ ] **Step 3: Add the robot CSS to `templates/landing.html`**, in the `<style>` block after the `.step .t` rule:

```css
    /* The agents robot: peeks over the "Share any article" step. Decorative;
       positions tuned for the 480px column ("fix it in post" per the owner). */
    .agent-peek { position: relative; margin-top: 46px; }
    .agent-peek .step { position: relative; z-index: 1; }
    .robot { position: absolute; top: -36px; left: 175px; transform: rotate(-5deg); z-index: 0; }
    .robot-head { position: relative; width: 44px; height: 40px; background: #8a6f5e; border-radius: 11px 11px 5px 5px; }
    .robot-head .antenna { position: absolute; top: -8px; left: 20px; width: 3px; height: 8px; background: #8a6f5e; }
    .robot-head .bobble { position: absolute; top: -14px; left: 17px; width: 8px; height: 8px; border-radius: 50%; background: var(--accent); }
    .robot-head .eye { position: absolute; top: 9px; width: 9px; height: 9px; border-radius: 50%; background: #fff; }
    .robot-head .eye.left { left: 8px; }
    .robot-head .eye.right { right: 8px; }
    .robot-head .pupil { position: absolute; top: 12px; width: 4px; height: 4px; border-radius: 50%; background: var(--ink); }
    .robot-head .pupil.left { left: 11px; }
    .robot-head .pupil.right { right: 11px; }
    .robot-head .smile { position: absolute; top: 24px; left: 16px; width: 12px; height: 6px; border-radius: 0 0 10px 10px; background: #fff; }
    .finger { position: absolute; top: -4px; width: 6px; height: 6px; border-radius: 3px 3px 0 0; background: #8a6f5e; z-index: 2; }
    .finger.f1 { left: 180px; }
    .finger.f2 { left: 207px; }
    .agent-bubble {
      position: absolute; top: -52px; left: 230px; max-width: 200px;
      background: #fff; border: 1.5px solid #E9C9AC; border-radius: 12px;
      padding: 5px 11px; font-size: 12px; line-height: 1.35; color: #5c4636;
      font-weight: 400; text-decoration: none; z-index: 2;
      box-shadow: 0 2px 6px rgba(176, 74, 0, .06);
    }
    .agent-bubble:hover { text-decoration: none; border-color: var(--accent); }
    .agent-bubble .tail {
      position: absolute; left: -6px; bottom: 9px; width: 9px; height: 9px;
      background: #fff; border-bottom: 1.5px solid #E9C9AC; border-left: 1.5px solid #E9C9AC;
      transform: rotate(45deg);
    }
```

- [ ] **Step 4: Wrap step 2 in the peek container** in `templates/landing.html`. REPLACE:

```html
  <div class="step">
    <div class="n">2</div>
    <div class="t">Share any article</div>
  </div>
```

WITH:

```html
  <div class="agent-peek">
    <div class="robot" aria-hidden="true">
      <div class="robot-head">
        <div class="antenna"></div>
        <div class="bobble"></div>
        <div class="eye left"></div>
        <div class="eye right"></div>
        <div class="pupil left"></div>
        <div class="pupil right"></div>
        <div class="smile"></div>
      </div>
    </div>
    <div class="finger f1" aria-hidden="true"></div>
    <div class="finger f2" aria-hidden="true"></div>
    <a class="agent-bubble" href="/AGENTS.md">or have your AI agent send things<span class="tail" aria-hidden="true"></span></a>
    <div class="step">
      <div class="n">2</div>
      <div class="t">Share any article</div>
    </div>
  </div>
```

- [ ] **Step 5: Run the test, em-dash grep, full suite**

Run: `uv run pytest tests/test_agent_api.py -k landing -v`
Expected: PASS.

Run: `grep -rn "—" templates/`
Expected: no output.

Run: `uv run pytest -q`
Expected: 193 passed.

- [ ] **Step 6: Eyeball it** (the one visual change worth a human glance before committing): start the app (`FEED_ME_DATA_DIR=$(mktemp -d) OPENAI_API_KEY=sk-test-dummy APP_BASE_URL=http://localhost:8000 uv run uvicorn app:app --port 8000`), open `http://localhost:8000/`, confirm the robot peeks over step 2 with the bubble to its right, then stop the server. If positions are off by a few px, ship anyway (owner: "fix it in post").

- [ ] **Step 7: Commit**

```bash
git add templates/landing.html tests/test_agent_api.py
git commit -m "feat: landing page robot advertises the agent API"
```

---

### Task 4: Docs, changelog, final verification

**Files:**
- Modify: `README.md`, `CHANGELOG.md`

- [ ] **Step 1: README**

a. REPLACE the "Agents welcome" bullet under "Good to know":

```markdown
- **Agents welcome.** Your AI agent can add articles for you. Tap
  *For agents* on your feed page, or point your agent at
  [feed-me.xyz/AGENTS.md](https://feed-me.xyz/AGENTS.md).
```

b. ADD a route-table row after the `GET /u/{secret}/episodes/{slug}` row:

```markdown
| `GET /u/{secret}/agents` | Personalized "give this to your agent" prompt page |
```

- [ ] **Step 2: CHANGELOG** (new entry at the top, above v3.6):

```markdown
## v3.7 — 2026-06-06

For Agents UI: the agent prompt gets a proper home.

- New page `/u/<secret>/agents`: the copy-paste agent prompt (click the box to copy) plus a link to `AGENTS.md`. Reached from an always-visible card under the episodes: "Your agent can share here too".
- The collapsed "For agents" fold (v3.6) is gone from the feed page.
- Landing page: a small robot peeks over the "Share any article" step saying "or have your AI agent send things", linking to `AGENTS.md`.
- Prompt copy trimmed: the daily-cap detail lives only in `AGENTS.md`; the privacy line and "(Claude Code and friends)" are removed.
```

(The CHANGELOG header em-dash is the existing convention; keep it. Note: the unimplemented GA4 spec doc claims v3.7 in its title; this release takes v3.7 because it ships first. Do not edit the GA4 spec.)

- [ ] **Step 3: Full verification**

Run: `uv run pytest -q`
Expected: 193 passed.

Run: `grep -rn "—" templates/`
Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "docs: README and changelog for v3.7"
```

---

## After the plan

Release steps (NOT part of this plan; follow superpowers:finishing-a-development-branch): merge `for-agents-ui` to `main`, tag `v3.7`, deploy with `~/.fly/bin/fly deploy --app feed-me-noah-willow-grove-8052`, verify `https://feed-me.xyz/` shows the robot and `/u/<secret>/agents` works in prod.
