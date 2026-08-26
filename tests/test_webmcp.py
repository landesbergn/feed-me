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


# --- docs --------------------------------------------------------------------

def test_agents_md_documents_webmcp(client):
    text = client.get("/AGENTS.md").text
    assert "## In a browser (WebMCP)" in text
    for name in TOOL_NAMES:
        assert name in text


def test_llms_txt_mentions_webmcp(client):
    assert "WebMCP" in client.get("/llms.txt").text


# --- agent-mode banner -------------------------------------------------------

def test_webmcp_js_shows_agent_mode_banner(client):
    body = client.get("/webmcp.js").text
    assert "fm-agent-banner" in body
    assert "Agent mode" in body
    # Every tool gets a human-readable activity line for the banner.
    for activity in (
        "adding an article",
        "narrating supplied text",
        "reading the episode list",
        "checking narration progress",
        "deleting an episode",
        "changing the voice",
        "reading the feed links",
        "creating your feed",
    ):
        assert activity in body


# --- example prompts ---------------------------------------------------------

def test_agent_panel_lists_example_prompts(client):
    secret = make_feed(client)
    text = client.get(f"/u/{secret}").text
    assert "Things to say to your agent" in text
    assert "Send this article to my feed" in text


def test_agents_md_lists_example_prompts(client):
    text = client.get("/AGENTS.md").text
    assert "Example prompts" in text
    for name in TOOL_NAMES:
        assert f"- {name}" in text


# --- the agent drives the page -----------------------------------------------

def test_webmcp_js_drives_the_page(client):
    body = client.get("/webmcp.js").text
    # Tool calls drive the same UI a person would use, visibly.
    assert "episodes_partial" in body        # episode tools refresh the live table
    assert "voice-chip" in body              # set_voice moves the picker's active chip
    assert "scrollIntoView" in body          # reactions bring the change on screen
    assert "fmAgentCreated" in body          # agent mode survives the create_feed hop
    assert "your agent created this feed" in body


# --- collab: the agent-session page ------------------------------------------

def test_collab_page_serves_the_agent_session_view(client):
    secret = make_feed(client)
    resp = client.get(f"/u/{secret}/collab")
    assert resp.status_code == 200
    text = resp.text
    assert "You + your agent" in text
    assert 'id="agent-status-text"' in text
    assert 'id="agent-log"' in text
    assert 'id="episodes-section"' in text
    assert '<script src="/webmcp.js" defer></script>' in text
    assert "Things to say to your agent" in text
    assert f'href="/u/{secret}"' in text          # exit back to the classic page
    assert "—" not in text


def test_collab_page_sets_session_cookie(client):
    secret = make_feed(client)
    resp = client.get(f"/u/{secret}/collab")
    assert "fm_session" in resp.headers.get("set-cookie", "")


def test_collab_page_unknown_secret_404(client):
    assert client.get("/u/nope/collab").status_code == 404


def test_collab_page_masks_ga_location(client):
    secret = make_feed(client)
    text = client.get(f"/u/{secret}/collab").text
    assert 'gaCfg.page_location = "https://test.local/u/_"' in text
    assert "gaCfg.page_path = '/u/_'" in text


def test_webmcp_js_runs_the_collab_session(client):
    body = client.get("/webmcp.js").text
    assert "/collab" in body
    assert "agent-log" in body
    assert "fmAgentLog" in body
    assert "agent-status-text" in body


def test_collab_page_exit_link_does_not_tempt_agents(client):
    # Codex clicked "Back to your feed page" after create_feed, treating the
    # classic page as the real deliverable. The exit link must describe the
    # destination as settings, not as the feed's home.
    secret = make_feed(client)
    text = client.get(f"/u/{secret}/collab").text
    assert "Back to your feed page" not in text
    assert "Open setup &amp; settings" in text


def test_create_feed_result_tells_the_agent_to_stay(client):
    body = client.get("/webmcp.js").text
    assert "Stay on that page" in body


def test_create_feed_description_preauthorizes_the_call(client):
    # Codex paused to ask "Shall I create it now?" before create_feed. The
    # description must say the call is low-stakes and that the user's request
    # is the consent, so agents plow through.
    body = client.get("/webmcp.js").text
    assert "Free and instant" in body
    assert "no extra confirmation" in body
