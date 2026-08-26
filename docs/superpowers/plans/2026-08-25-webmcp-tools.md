# WebMCP Tools (v3.28) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When an agent browses Feed Me in a WebMCP-capable browser (ChatGPT's browser, or Chrome with WebMCP enabled), the pages themselves register tools: `create_feed` on the landing page, and the full episode toolset on the feed page, so the agent can create a feed, narrate articles, poll progress, and manage episodes without ever reading `AGENTS.md`.

**Architecture:** One committed static script, `static/webmcp.js`, served by a new `GET /webmcp.js` route (this app serves static assets via explicit routes; there is no `StaticFiles` mount) and included with `defer` on `landing.html` and `settings.html` only. The script feature-detects `navigator.modelContext` / `document.modelContext`, derives the secret from `location.pathname`, and wraps the existing endpoints (`POST/GET/DELETE /u/<secret>/episodes*`, `POST /u/<secret>/voice`, `POST /create`) in same-origin fetches. No endpoint, cap, storage, RSS, or analytics change.

**Tech Stack:** Python 3, FastAPI, Starlette `TestClient`, pytest; plain browser JS (no build step). Run tests with `uv run pytest`.

**Spec:** `docs/superpowers/specs/2026-08-25-webmcp-tools.html`

---

## File Structure

| File | Change | Responsibility |
|------|--------|----------------|
| `static/webmcp.js` | New (committed, not generated) | Feature-detect WebMCP, register the tools |
| `app.py` | Modify (one route near `cover_route`, ~line 747) | Serve `/webmcp.js` as `text/javascript` |
| `templates/landing.html` | Modify (one line before `</body>`) | Load the script on the landing page |
| `templates/settings.html` | Modify (one line before `</body>`) | Load the script on the feed page |
| `templates/_setup_instructions.html` | Modify (one line in the agent panel) | Tell owners WebMCP browsers need no prompt |
| `templates/agents.md` | Modify (new section) | Document the in-browser toolset |
| `app.py` (`llms_txt_route`) | Modify (one line) | Point browser agents at the pages |
| `tests/test_webmcp.py` | New | Contract tests: serving, includes, toolset, copy |
| `README.md` | Modify (route row + agents bullet) | Document the new route and surface |
| `CHANGELOG.md` | Modify (prepend entry) | v3.28 release notes |

**Conventions to honor (from CLAUDE.md and the existing code):**
- No em-dashes (`—`) in any user- or agent-facing copy, including the JS tool descriptions. Grep every touched file.
- `templates/agents.md` is substituted with plain `.replace("{base}", ...)`: keep the literal `{base}` token, no new stray braces concerns (only the literal string `{base}` is replaced).
- The raw secret never reaches analytics or Google; this change adds no tracking and must not touch `_ga.html` or `_track` calls.
- Static assets follow the `_icon` pattern: `FileResponse(STATIC_DIR / name, media_type=..., headers={"Cache-Control": ...})`.
- In tests, `APP_BASE_URL` is `https://test.local` and the `client` fixture points `DATA_DIR` at a per-test temp dir; `client.post("/create", follow_redirects=False)` returns a 303 whose `location` is `/u/<secret>`.

---

## Task 1: `static/webmcp.js` and the `GET /webmcp.js` route

**Files:**
- Create: `static/webmcp.js`
- Modify: `app.py` (insert the route directly after `cover_route`, before `_icon`)
- Test: `tests/test_webmcp.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_webmcp.py`:

```python
"""WebMCP contract tests.

The JS cannot execute under pytest, so these pin the contract instead: the
script is served correctly, the right pages include it, and the toolset,
page guards, and copy stay what the spec says.
"""

TOOL_NAMES = [
    "add_article",
    "add_article_text",
    "list_episodes",
    "get_episode_status",
    "delete_episode",
    "set_voice",
    "get_feed_info",
    "create_feed",
]


def make_feed(client) -> str:
    resp = client.post("/create", follow_redirects=False)
    assert resp.status_code == 303
    return resp.headers["location"].rsplit("/", 1)[-1]


# --- GET /webmcp.js ----------------------------------------------------------

def test_webmcp_js_served_as_javascript(client):
    resp = client.get("/webmcp.js")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/javascript")


def test_webmcp_js_detects_both_api_homes_and_both_registration_calls(client):
    body = client.get("/webmcp.js").text
    assert "navigator.modelContext" in body
    assert "document.modelContext" in body
    assert "registerTool" in body
    assert "provideContext" in body


def test_webmcp_js_registers_the_full_toolset(client):
    body = client.get("/webmcp.js").text
    for name in TOOL_NAMES:
        assert f'"{name}"' in body


def test_webmcp_js_guards_on_page(client):
    # Feed-page tools only at /u/<secret>, create_feed only at "/": the
    # honest limit of DOM-less testing is asserting the guards exist.
    body = client.get("/webmcp.js").text
    assert "location.pathname" in body
    assert '"/"' in body


def test_webmcp_js_has_no_emdash(client):
    assert "—" not in client.get("/webmcp.js").text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_webmcp.py -v`
Expected: FAIL. `GET /webmcp.js` matches no route, so FastAPI returns 404 and every test trips on the status or the body.

- [ ] **Step 3: Create `static/webmcp.js`**

Full contents:

```js
/* Feed Me WebMCP tools.
 *
 * When this page is opened in a WebMCP-capable agent browser (ChatGPT's
 * browser, or Chrome with WebMCP enabled), register tools that drive the
 * same agent API documented at /AGENTS.md: create_feed on the landing page,
 * the full episode toolset on the feed page. Everywhere else, and in every
 * browser without WebMCP, this script is a silent no-op.
 *
 * The API is an origin trial and has moved between drafts (navigator vs
 * document home, registerTool vs provideContext), so detect every shape and
 * never let a registration failure escape to the page.
 */
(function () {
  "use strict";

  var mc = (typeof navigator !== "undefined" && navigator.modelContext) ||
    (typeof document !== "undefined" && document.modelContext);
  if (!mc) return;

  var match = location.pathname.match(/^\/u\/([A-Za-z0-9_-]+)\/?$/);
  var secret = match ? match[1] : null;

  function result(text) {
    return { content: [{ type: "text", text: text }] };
  }

  /* Same-origin fetch -> {ok, text}. Error bodies from the agent API are
     {"error","message"} JSON; anything else becomes a bare status line. */
  async function call(method, path, options) {
    options = options || {};
    var init = { method: method, headers: {} };
    if (options.json) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(options.json);
    }
    if (options.form) {
      init.body = new URLSearchParams(options.form);
    }
    var resp = await fetch(path, init);
    var body = await resp.text();
    if (!resp.ok) {
      try {
        var err = JSON.parse(body);
        if (err && err.error && err.message) {
          return { ok: false, text: "Error " + resp.status + " (" + err.error + "): " + err.message };
        }
      } catch (e) { /* not the agent API's JSON shape */ }
      return { ok: false, text: "Error " + resp.status + "." };
    }
    return { ok: true, text: body };
  }

  var tools = [];

  if (secret) {
    var base = "/u/" + secret;

    tools.push({
      name: "add_article",
      description: "Narrate an article into this Feed Me podcast feed from its URL. Returns the pending episode as JSON (note the slug); narration takes a few minutes, so poll get_episode_status until status is ready. Do not retry a failed URL.",
      inputSchema: {
        type: "object",
        properties: {
          url: { type: "string", description: "The article's http or https URL." }
        },
        required: ["url"]
      },
      execute: async function (params) {
        var r = await call("POST", base + "/episodes", { json: { url: params.url } });
        return result(r.ok ? "Episode created: " + r.text : r.text);
      }
    });

    tools.push({
      name: "add_article_text",
      description: "Narrate text you already have into this feed: an article a server fetch cannot reach, or writing of your own the user asked for. Requires a title. Returns the pending episode as JSON; poll get_episode_status until ready.",
      inputSchema: {
        type: "object",
        properties: {
          text: { type: "string", description: "The full text to narrate." },
          title: { type: "string", description: "The episode title." },
          url: { type: "string", description: "Optional source URL for the show notes." }
        },
        required: ["text", "title"]
      },
      execute: async function (params) {
        var payload = { text: params.text, title: params.title };
        if (params.url) payload.url = params.url;
        var r = await call("POST", base + "/episodes", { json: payload });
        return result(r.ok ? "Episode created: " + r.text : r.text);
      }
    });

    tools.push({
      name: "list_episodes",
      description: "List this feed's 20 most recent episodes, newest first, with per-episode status, plus the feed's voice and the remaining daily share quota.",
      inputSchema: { type: "object", properties: {} },
      execute: async function () {
        var r = await call("GET", base + "/episodes");
        return result(r.text);
      }
    });

    tools.push({
      name: "get_episode_status",
      description: "Check one episode by slug. Status moves from pending to ready (an audio_url appears) or failed (error says why). Narration takes a few minutes; poll no faster than every few seconds.",
      inputSchema: {
        type: "object",
        properties: {
          slug: { type: "string", description: "The episode slug returned by add_article or add_article_text." }
        },
        required: ["slug"]
      },
      execute: async function (params) {
        var r = await call("GET", base + "/episodes/" + encodeURIComponent(params.slug));
        return result(r.text);
      }
    });

    tools.push({
      name: "delete_episode",
      description: "Delete one episode from the feed by slug. This cannot be undone, so confirm with the user before deleting anything they did not just ask you to remove.",
      inputSchema: {
        type: "object",
        properties: {
          slug: { type: "string", description: "The episode slug to delete." }
        },
        required: ["slug"]
      },
      execute: async function (params) {
        var r = await call("DELETE", base + "/episodes/" + encodeURIComponent(params.slug));
        return result(r.text);
      }
    });

    tools.push({
      name: "set_voice",
      description: "Set the narration voice for future episodes of this feed. Already-narrated episodes keep their voice.",
      inputSchema: {
        type: "object",
        properties: {
          voice: {
            type: "string",
            "enum": ["alloy", "echo", "nova", "shimmer"],
            description: "The voice name."
          }
        },
        required: ["voice"]
      },
      execute: async function (params) {
        var r = await call("POST", base + "/voice", { form: { voice: params.voice } });
        return result(r.ok ? "Voice set to " + params.voice + " for future episodes." : r.text);
      }
    });

    tools.push({
      name: "get_feed_info",
      description: "Get this feed's page URL and its private RSS URL for subscribing in a podcast app. Both URLs are this user's whole account: treat them as secrets and share them only with the user.",
      inputSchema: { type: "object", properties: {} },
      execute: async function () {
        return result(JSON.stringify({
          feed_page: location.origin + base,
          feed_url: location.origin + base + "/feed.xml",
          api_docs: location.origin + "/AGENTS.md"
        }));
      }
    });
  } else if (location.pathname === "/") {
    tools.push({
      name: "create_feed",
      description: "Create a new private Feed Me podcast feed for this user, then go to its feed page, where the tools for adding articles register. One feed per person is plenty: do not call this if the user already has a feed.",
      inputSchema: { type: "object", properties: {} },
      execute: async function () {
        var resp = await fetch("/create", { method: "POST" });
        if (!resp.ok) return result("Error " + resp.status + ".");
        var page = resp.url;
        setTimeout(function () { location.assign(page); }, 500);
        return result(
          "Feed created. Its private page is " + page + " (treat it as a secret; it is the user's whole account). " +
          "Navigating there now; the article tools register on that page."
        );
      }
    });
  }

  if (!tools.length) return;
  try {
    if (typeof mc.registerTool === "function") {
      for (var i = 0; i < tools.length; i++) mc.registerTool(tools[i]);
    } else if (typeof mc.provideContext === "function") {
      mc.provideContext({ tools: tools });
    }
  } catch (e) {
    /* An API-shape drift must never break the page. */
  }
})();
```

- [ ] **Step 4: Add the route in `app.py`**

Insert directly after `cover_route` (which ends around line 754), before `_icon`:

```python
@app.get("/webmcp.js")
def webmcp_js():
    """The WebMCP tool registration script (see AGENTS.md, 'In a browser').

    Included by the landing and feed pages; a silent no-op in browsers
    without WebMCP. Committed under static/, not generated.
    """
    return FileResponse(
        STATIC_DIR / "webmcp.js",
        media_type="text/javascript",
        headers={"Cache-Control": "public, max-age=3600"},
    )
```

Notes for the implementer:
- `FileResponse` and `STATIC_DIR` are already imported/defined (`cover_route` uses both). Add no imports.
- No `_track` call: this is a static asset.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_webmcp.py -v`
Expected: PASS (5 tests).

- [ ] **Step 6: Verify no em-dash and run the full suite**

Run: `grep -c '—' static/webmcp.js` (expected `0`), then `uv run pytest` (expected all green).

- [ ] **Step 7: Commit**

```bash
git add static/webmcp.js app.py tests/test_webmcp.py
git commit -m "feat: WebMCP tool registration script, served at /webmcp.js

static/webmcp.js registers page tools for WebMCP-capable agent browsers:
create_feed on the landing page, and add_article / add_article_text /
list_episodes / get_episode_status / delete_episode / set_voice /
get_feed_info on the feed page, all thin same-origin fetch wrappers over
the existing agent API (caps and errors unchanged). Detects both API homes
(navigator/document.modelContext) and both registration calls; no-op
without WebMCP.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Task 2: Load the script on the landing and feed pages; agent-panel copy

**Files:**
- Modify: `templates/landing.html` (one line before `</body>`, ~line 146)
- Modify: `templates/settings.html` (one line before `</body>`, ~line 343)
- Modify: `templates/_setup_instructions.html` (one line after the API link, ~line 88)
- Test: `tests/test_webmcp.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_webmcp.py`:

```python
# --- page includes -----------------------------------------------------------

def test_landing_page_loads_webmcp_script(client):
    resp = client.get("/")
    assert '<script src="/webmcp.js" defer></script>' in resp.text


def test_feed_page_loads_webmcp_script(client):
    secret = make_feed(client)
    resp = client.get(f"/u/{secret}")
    assert '<script src="/webmcp.js" defer></script>' in resp.text


def test_share_page_does_not_load_webmcp_script(client):
    resp = client.get("/share?url=https://example.com/a")
    assert "webmcp.js" not in resp.text


def test_agent_panel_mentions_webmcp(client):
    secret = make_feed(client)
    resp = client.get(f"/u/{secret}")
    assert "WebMCP browser" in resp.text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_webmcp.py -k "loads or share_page or panel" -v`
Expected: the landing, feed-page, and panel tests FAIL (no include, no copy); the share-page test PASSES already (nothing to remove) and simply pins the scope.

- [ ] **Step 3: Add the includes**

In `templates/landing.html`, directly before `</body>`:

```html
  <script src="/webmcp.js" defer></script>
</body>
```

In `templates/settings.html`, directly before `</body>` (after the site footer):

```html
  <script src="/webmcp.js" defer></script>
</body>
```

- [ ] **Step 4: Add the agent-panel line**

In `templates/_setup_instructions.html`, directly after the `agent-api-link` paragraph (the `The full API, for your agent's eyes` line), add:

```html
    <p class="agent-api-link">Browsing with an agent? In a WebMCP browser this page registers its own tools, so your agent can add articles with no prompt at all.</p>
```

- [ ] **Step 5: Verify and run**

Run: `grep -c '—' templates/_setup_instructions.html` (expected `0`), then `uv run pytest tests/test_webmcp.py -v` (expected PASS) and `uv run pytest` (full suite green; the settings-page tests in `test_app.py` / `test_agent_api.py` pin substrings, not whole-page equality, so the added lines are safe).

- [ ] **Step 6: Commit**

```bash
git add templates/landing.html templates/settings.html templates/_setup_instructions.html tests/test_webmcp.py
git commit -m "feat: landing and feed pages load the WebMCP script

Plus one line in the For-your-agent panel telling owners that a WebMCP
browser needs no pasted prompt. Share pages stay script-free.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Task 3: Document the surface in `AGENTS.md` and `llms.txt`

**Files:**
- Modify: `templates/agents.md` (new section after "Read the feed")
- Modify: `app.py` (`llms_txt_route`, ~line 185)
- Test: `tests/test_webmcp.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_webmcp.py`:

```python
# --- docs --------------------------------------------------------------------

def test_agents_md_documents_webmcp(client):
    text = client.get("/AGENTS.md").text
    assert "## In a browser (WebMCP)" in text
    for name in TOOL_NAMES:
        assert name in text


def test_llms_txt_mentions_webmcp(client):
    assert "WebMCP" in client.get("/llms.txt").text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_webmcp.py -k "documents_webmcp or llms" -v`
Expected: FAIL (neither file mentions WebMCP).

- [ ] **Step 3: Add the `AGENTS.md` section**

In `templates/agents.md`, insert after the "Read the feed" section (after the `feed.xml` paragraph, before `## Errors`):

```markdown
## In a browser (WebMCP)

If you are browsing with WebMCP support (ChatGPT's browser, or Chrome with
WebMCP enabled), you do not need this API by hand. Open the user's feed page
{base}/u/<secret> and the page registers tools: add_article,
add_article_text, list_episodes, get_episode_status, delete_episode,
set_voice, and get_feed_info. A user with no feed yet can start at {base}/
where a create_feed tool registers. The HTTP API on this page is the same
capability set and works everywhere else.
```

Keep the literal `{base}` token (the file is substituted with a plain `.replace("{base}", ...)`); no em-dashes.

- [ ] **Step 4: Add the `llms.txt` line**

In `app.py`, `llms_txt_route`, extend the response:

```python
@app.get("/llms.txt")
def llms_txt_route():
    return PlainTextResponse(
        "Feed Me turns shared articles into narrated episodes in a private "
        "podcast feed.\n"
        f"API documentation for agents: {APP_BASE_URL}/AGENTS.md\n"
        "Browsing with WebMCP? The landing page and feed pages register "
        "their own tools; see the 'In a browser' section of AGENTS.md.\n"
    )
```

- [ ] **Step 5: Verify and run**

Run: `grep -c '—' templates/agents.md` (expected `0`), then `uv run pytest tests/test_webmcp.py -v` and `uv run pytest tests/test_agent_api.py -k agents_md -v` (the existing AGENTS.md tests must stay green: `{base}` still substituted, no em-dash, existing section strings untouched).

- [ ] **Step 6: Commit**

```bash
git add templates/agents.md app.py tests/test_webmcp.py
git commit -m "docs: AGENTS.md and llms.txt document the WebMCP surface

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Task 4: README, CHANGELOG, release tag

**Files:**
- Modify: `README.md` (route row + "Agents welcome" bullet)
- Modify: `CHANGELOG.md` (prepend entry)

- [ ] **Step 1: README**

In the routes table, after the `GET /AGENTS.md`, `GET /llms.txt` row, insert:

```markdown
| `GET /webmcp.js` | WebMCP tool registration script, loaded by the landing and feed pages for in-browser agents |
```

In the "Agents welcome" bullet (~line 40), extend the copy:

```markdown
- **Agents welcome.** Your AI agent can add articles for you. Tap
  *For agents* on your feed page, or point your agent at
  [feed-me.xyz/AGENTS.md](https://feed-me.xyz/AGENTS.md). In a WebMCP
  browser (ChatGPT's browser, or Chrome with WebMCP enabled) the pages
  register their own tools, so the agent needs no docs at all.
```

- [ ] **Step 2: CHANGELOG**

Prepend below `# Changelog`:

```markdown
## v3.28 · 2026-08-25

WebMCP tools: the pages register their own agent tools.

- New `static/webmcp.js`, served at `GET /webmcp.js` and loaded (with `defer`) by the landing and feed pages. In a WebMCP-capable agent browser (ChatGPT's browser, or Chrome with WebMCP enabled) the landing page registers `create_feed`, and the feed page registers `add_article`, `add_article_text`, `list_episodes`, `get_episode_status`, `delete_episode`, `set_voice`, and `get_feed_info`. Every tool is a thin same-origin fetch over the existing agent API, so the caps, character budget, and error messages apply unchanged, and the secret never leaves the page's origin. In browsers without WebMCP the script is a silent no-op.
- The script detects both API homes (`navigator.modelContext` and `document.modelContext`) and both registration calls (`registerTool`, `provideContext({tools})`), and a registration failure can never break the page: the API is an origin trial and has moved between drafts.
- `AGENTS.md` gains an "In a browser (WebMCP)" section, `llms.txt` points browser agents at the pages, and the For-your-agent panel notes that a WebMCP browser needs no pasted prompt.
```

- [ ] **Step 3: Full suite**

Run: `uv run pytest`
Expected: PASS.

- [ ] **Step 4: Commit and tag**

```bash
git add README.md CHANGELOG.md
git commit -m "docs: README route + CHANGELOG for v3.28 WebMCP tools

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
git tag v3.28
```

(Push and deploy are owner-driven. Deploy command, for reference: `~/.fly/bin/fly deploy --app feed-me-noah-willow-grove-8052`. Before the hackathon submission the owner should verify the toolset once in a real WebMCP browser; likely drifts are one-line fixes in `static/webmcp.js`.)

---

## Self-Review

**Spec coverage:**
- Eight tools, right pages, MCP-shaped results, pass-through JSON, documented error strings, dual API detection, try/catch guard → Task 1. Covered.
- Includes on landing + settings with `defer`, not on share pages; agent-panel line → Task 2. Covered.
- AGENTS.md section, llms.txt line → Task 3. Covered.
- README, CHANGELOG v3.28, tag → Task 4. Covered.
- Out of scope (hackathon submission, origin-trial token, cross-origin exposure, share/admin pages, JS test runner) → not implemented, as specified.

**Placeholder scan:** No TBD/TODO; every code and doc step shows the literal content.

**Type/name consistency:** `STATIC_DIR`, `FileResponse`, `PlainTextResponse`, `APP_BASE_URL` all already present in `app.py`. Voice enum `["alloy","echo","nova","shimmer"]` matches `storage.ALLOWED_VOICES`. The secret regex `[A-Za-z0-9_-]+` matches the URL-safe token alphabet. Tool names are identical across `webmcp.js`, `tests/test_webmcp.py` (`TOOL_NAMES`), `AGENTS.md`, and the CHANGELOG. `client.post("/create", follow_redirects=False)` → 303 with `location: /u/<secret>` matches `create()` in `app.py`.
