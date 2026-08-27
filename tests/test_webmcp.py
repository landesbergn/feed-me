"""WebMCP contract tests.

The JS cannot execute under pytest, so these pin the contract instead: the
script is served correctly, the right pages include it, and the toolset,
page guards, and copy stay what the specs say (v3.28 WebMCP tools, and the
2026-08-26 session-page-directions decision: one page, subscribe-first).
"""

TOOL_NAMES = [
    "add_article",
    "add_article_text",
    "list_episodes",
    "get_episode_status",
    "delete_episode",
    "set_voice",
    "get_feed_info",
    "help_subscribe",
    "get_requests",
    "complete_request",
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


# --- agent activity: trace + log ---------------------------------------------

def test_webmcp_js_narrates_every_tool(client):
    body = client.get("/webmcp.js").text
    for activity in (
        "adding an article",
        "narrating supplied text",
        "reading the episode list",
        "checking narration progress",
        "deleting an episode",
        "changing the voice",
        "reading the feed links",
        "helping you subscribe",
        "checking your requests",
        "checking off a request",
        "creating your feed",
    ):
        assert activity in body


def test_webmcp_js_uses_the_native_trace(client):
    # Agent mode renders into the feed page's own trace elements; the
    # injected banner survives only for the landing page.
    body = client.get("/webmcp.js").text
    assert "agent-trace-text" in body
    assert "agent-log" in body
    assert "fmAgentLog" in body
    assert "fm-agent-banner" in body


def test_feed_page_has_the_trace_markup(client):
    secret = make_feed(client)
    text = client.get(f"/u/{secret}").text
    assert 'id="agent-trace" hidden' in text
    assert 'id="agent-trace-text"' in text
    assert 'id="agent-history-btn"' in text
    assert 'id="agent-log"' in text
    # The trace styles use display:flex, which beats the hidden attribute's
    # UA rule; the guard keeps the strip invisible until an agent acts.
    assert "#agent-trace[hidden] { display: none; }" in text


def test_webmcp_js_drives_the_page(client):
    body = client.get("/webmcp.js").text
    assert "episodes_partial" in body        # episode tools refresh the live table
    assert "voice-chip" in body              # set_voice moves the picker's active chip
    assert "scrollIntoView" in body          # reactions bring the change on screen
    assert "fmAgentCreated" in body          # agent mode survives the create_feed hop
    assert "your producer created this feed" in body
    assert "requests_partial" in body        # request tools refresh the assignment desk
    assert "params.note" in body             # producer's note flows through the add tools


# --- one page: /collab redirects home ----------------------------------------

def test_collab_redirects_to_the_feed_page(client):
    secret = make_feed(client)
    resp = client.get(f"/u/{secret}/collab", follow_redirects=False)
    assert resp.status_code == 301
    assert resp.headers["location"] == f"/u/{secret}"


# --- the feed page: subscribe-first, quiet after -----------------------------

def test_fresh_feed_leads_with_the_listen_card(client):
    secret = make_feed(client)
    body = client.get(f"/u/{secret}").text
    assert 'id="listen-card"' in body
    assert body.index("Put your feed in your podcast app") < body.index("Your episodes")
    assert "Overcast" in body
    assert "Pocket Casts" in body
    # iOS setup is always folded now, even on a fresh feed.
    assert "Setup &amp; sharing" in body


def test_shared_feed_leads_with_episodes(client, tmp_path):
    secret = make_feed(client)
    import storage
    storage.write_episode(
        tmp_path, secret, slug="real1", title="A Real Article",
        source_url="https://example.com/a", audio=b"MP3", description="x",
    )
    body = client.get(f"/u/{secret}").text
    assert body.index("Your episodes") < body.index("Put your feed in your podcast app")


def test_feed_page_has_no_agent_chrome(client):
    secret = make_feed(client)
    body = client.get(f"/u/{secret}").text
    assert "Things to say to your agent" not in body
    assert "You + your agent" not in body


# --- help_subscribe ----------------------------------------------------------

def test_help_subscribe_is_honest_about_the_clipboard(client):
    # The "your agent copied it" line renders only on a successful copy: the
    # page carries it hidden, and only the JS reveals it.
    secret = make_feed(client)
    page = client.get(f"/u/{secret}").text
    assert 'id="agent-copied" hidden' in page
    body = client.get("/webmcp.js").text
    assert "agent-copied" in body
    assert "clipboard" in body


def test_create_feed_result_names_help_subscribe(client):
    body = client.get("/webmcp.js").text
    assert "call help_subscribe" in body
    assert "Free and instant" in body
    assert "no extra confirmation" in body


# --- docs --------------------------------------------------------------------

def test_agents_md_documents_webmcp(client):
    text = client.get("/AGENTS.md").text
    assert "## In a browser (WebMCP)" in text
    for name in TOOL_NAMES:
        assert name in text


def test_agents_md_lists_example_prompts(client):
    text = client.get("/AGENTS.md").text
    assert "Example prompts" in text
    for name in TOOL_NAMES:
        assert f"- {name}" in text


def test_llms_txt_mentions_webmcp(client):
    assert "WebMCP" in client.get("/llms.txt").text


def test_episode_article_links_are_clickable(client, tmp_path):
    secret = make_feed(client)
    import storage
    storage.write_episode(
        tmp_path, secret, slug="real1", title="A Real Article",
        source_url="https://example.com/a", audio=b"MP3", description="x",
    )
    body = client.get(f"/u/{secret}").text
    assert '<a class="src" href="https://example.com/a" target="_blank" rel="noopener">' in body
