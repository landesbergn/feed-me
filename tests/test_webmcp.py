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
