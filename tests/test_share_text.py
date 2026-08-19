"""POST /u/{secret}/share-text: the on-device-extraction path.

The iOS Shortcut extracts an article's text from the page Safari already
rendered (subscriber session included) and posts the text here, so Feed Me
never fetches the URL itself. That sidesteps both the paywall and the bot
blocks that make nytimes.com unfetchable from a server. Path-secret auth, no
cookies, and a human-sized daily cap (the agent cap of 5/day is a guard on
automation, not on a person sharing what they read)."""
import json
import time

import storage
from tests.conftest import FakeResponse   # noqa: F401  (parity with other suites)

ARTICLE_TEXT = (
    "The first paragraph of a long piece about time, extracted on the "
    "phone from the page Safari had already rendered. " * 20
)


def make_feed(client) -> str:
    create = client.post("/create", follow_redirects=False)
    return create.headers["location"].split("/u/")[1]


def wire_spawn(monkeypatch) -> list:
    calls = []
    import app as app_module
    monkeypatch.setattr(
        app_module, "spawn_ingest",
        lambda url, secret, data_dir, slug, *, text=None, title=None: calls.append(
            {"url": url, "slug": slug, "text": text, "title": title},
        ),
    )
    return calls


def test_share_text_narrates_supplied_text(client, monkeypatch, tmp_path):
    secret = make_feed(client)
    calls = wire_spawn(monkeypatch)

    resp = client.post(f"/u/{secret}/share-text", json={
        "text": ARTICLE_TEXT,
        "title": "On Time",
        "url": "https://www.nytimes.com/2026/08/18/a.html",
    })

    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "pending"
    assert body["title"] == "On Time"
    assert body["slug"]

    # The text is narrated as-is: no fetch of the (unfetchable) source URL.
    assert len(calls) == 1
    assert calls[0]["text"] == ARTICLE_TEXT
    assert calls[0]["title"] == "On Time"
    assert calls[0]["url"] == "https://www.nytimes.com/2026/08/18/a.html"

    eps = storage.list_episodes(tmp_path, secret)
    ep = [e for e in eps if e["slug"] == body["slug"]][0]
    assert ep["status"] == "pending"
    assert ep["via"] == "shortcut"          # distinguishable from agent pushes
    assert ep["chars"] == len(ARTICLE_TEXT)  # metered like agent text mode


def test_share_text_accepts_form_encoded_body(client, monkeypatch):
    """Shortcuts' Get Contents of URL posts a form by default."""
    secret = make_feed(client)
    calls = wire_spawn(monkeypatch)

    resp = client.post(f"/u/{secret}/share-text", data={
        "text": ARTICLE_TEXT, "title": "On Time",
        "url": "https://example.com/a",
    })

    assert resp.status_code == 202
    assert calls[0]["text"] == ARTICLE_TEXT


def test_share_text_never_touches_the_session_cookie(client, monkeypatch):
    """Same rule as the agent API: path-secret auth only."""
    secret = make_feed(client)
    wire_spawn(monkeypatch)

    resp = client.post(
        f"/u/{secret}/share-text", json={"text": ARTICLE_TEXT, "title": "T"},
    )

    assert "set-cookie" not in {k.lower() for k in resp.headers}
    assert client.cookies.get("fm_session") is None


def test_share_text_falls_back_to_a_title_from_the_text(client, monkeypatch):
    """Get Details of Article can hand back an empty name; don't 400 on it."""
    secret = make_feed(client)
    calls = wire_spawn(monkeypatch)

    resp = client.post(f"/u/{secret}/share-text", json={
        "text": "Cycling's stakeholders must reflect\n\n" + ARTICLE_TEXT,
        "title": "",
    })

    assert resp.status_code == 202
    assert resp.json()["title"] == "Cycling's stakeholders must reflect"
    assert calls[0]["title"] == "Cycling's stakeholders must reflect"


def test_share_text_requires_text(client):
    secret = make_feed(client)
    resp = client.post(f"/u/{secret}/share-text", json={"title": "T", "text": "  "})
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_request"


def test_share_text_rejects_text_over_the_body_limit(client):
    import ingest
    secret = make_feed(client)
    resp = client.post(f"/u/{secret}/share-text", json={
        "text": "x" * (ingest.MAX_BODY_CHARS + 1), "title": "T",
    })
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_request"


def test_share_text_rejects_a_bad_source_url(client):
    secret = make_feed(client)
    resp = client.post(f"/u/{secret}/share-text", json={
        "text": ARTICLE_TEXT, "title": "T", "url": "ftp://nope.example/x",
    })
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_url"


def test_share_text_unknown_feed_is_404(client):
    resp = client.post("/u/nosuchsecret/share-text", json={
        "text": ARTICLE_TEXT, "title": "T",
    })
    assert resp.status_code == 404
    assert resp.json()["error"] == "not_found"


def test_share_text_blocked_feed_is_403(client, monkeypatch):
    import analytics
    import app as app_module
    secret = make_feed(client)
    monkeypatch.setattr(
        app_module, "BLOCKED_FEED_HASHES", {analytics.feed_hash(secret)},
    )
    calls = wire_spawn(monkeypatch)

    resp = client.post(f"/u/{secret}/share-text", json={
        "text": ARTICLE_TEXT, "title": "T",
    })

    assert resp.status_code == 403
    assert resp.json()["error"] == "suspended"
    assert calls == []          # no narration spend for a blocked feed


def test_share_text_daily_cap_is_human_sized_and_separate_from_agents(
    client, monkeypatch, tmp_path,
):
    """A person sharing what they read must not be cut off at the agent cap of
    5/day, and agent pushes must not consume the human allowance."""
    import app as app_module
    assert app_module.SHORTCUT_DAILY_CAP > app_module.AGENT_DAILY_CAP
    secret = make_feed(client)
    wire_spawn(monkeypatch)

    now = int(time.time())
    for _ in range(app_module.AGENT_DAILY_CAP):
        storage.write_pending_episode(
            tmp_path, secret, source_url="https://example.com/agent",
            title="A", via="agent", chars=10,
        )

    # Agent episodes fill the agent cap; the shortcut path is unaffected.
    resp = client.post(f"/u/{secret}/share-text", json={
        "text": ARTICLE_TEXT, "title": "T",
    })
    assert resp.status_code == 202

    for _ in range(app_module.SHORTCUT_DAILY_CAP):
        storage.write_pending_episode(
            tmp_path, secret, source_url="https://example.com/s",
            title="S", via="shortcut", chars=10,
        )
    resp = client.post(f"/u/{secret}/share-text", json={
        "text": ARTICLE_TEXT, "title": "T",
    })
    assert resp.status_code == 429
    assert resp.json()["error"] == "rate_limited"
    assert int(resp.headers["Retry-After"]) > 0
    assert now  # window is a rolling one anchored on episode timestamps


def test_share_text_respects_the_feed_character_budget(client, monkeypatch, tmp_path):
    import app as app_module
    secret = make_feed(client)
    calls = wire_spawn(monkeypatch)

    storage.write_pending_episode(
        tmp_path, secret, source_url="https://example.com/s", title="S",
        via="shortcut", chars=app_module.AGENT_FEED_CHAR_BUDGET,
    )
    resp = client.post(f"/u/{secret}/share-text", json={
        "text": ARTICLE_TEXT, "title": "T",
    })

    assert resp.status_code == 429
    assert resp.json()["error"] == "budget_exceeded"
    assert calls == []


def test_share_text_records_analytics_as_shortcut(client, monkeypatch, tmp_path):
    import analytics
    secret = make_feed(client)
    wire_spawn(monkeypatch)

    client.post(f"/u/{secret}/share-text", json={
        "text": ARTICLE_TEXT, "title": "On Time",
        "url": "https://www.nytimes.com/a.html",
    })

    db = tmp_path / "_analytics" / "analytics.db"
    events = [e for e in analytics.all_events(db) if e["event"] == "article_shared"]
    assert len(events) == 1
    assert json.loads(events[0]["props"])["via"] == "shortcut"
    # Attributed by one-way feed hash; the raw secret never reaches analytics.
    assert analytics.feed_hash(secret) in json.dumps(events[0])
    assert secret not in json.dumps(events[0])


# --- The generic (secret-free) path: /share/text -----------------------------
# The Shortcut opens this page in Safari with the article text in the URL
# fragment. Safari sends fm_session exactly as it does for /share, so the
# Shortcut itself carries no identity and is byte-identical for every user.
# The fragment never reaches the server (browsers don't send it), so the
# article text stays out of the request logs.

def link_browser(client) -> str:
    """Create a feed and give this client the cookie, as visiting it in Safari does."""
    create = client.post("/create", follow_redirects=False)
    secret = create.headers["location"].split("/u/")[1]
    client.get(f"/u/{secret}")
    return secret


def test_share_text_page_needs_a_linked_browser(client):
    assert "Link this browser" in client.get("/share/text").text


def test_share_text_page_posts_back_to_itself(client):
    link_browser(client)
    page = client.get("/share/text").text
    assert 'action="/share/text"' in page
    assert 'method="post"' in page


def test_share_text_page_masks_its_url_from_analytics(client):
    """The fragment holds the article text, and gtag reports location.href
    verbatim, so the reported location must be the bare path."""
    link_browser(client)
    page = client.get("/share/text").text
    assert '"https://test.local/share/text"' in page
    assert "page_path" in page


def test_share_text_page_submit_creates_the_episode(client, monkeypatch, tmp_path):
    secret = link_browser(client)
    calls = wire_spawn(monkeypatch)

    resp = client.post("/share/text", data={
        "text": ARTICLE_TEXT, "title": "On Time",
        "url": "https://www.nytimes.com/a.html",
    })

    assert resp.status_code == 200
    assert "Added" in resp.text
    assert "On Time" in resp.text
    assert calls[0]["text"] == ARTICLE_TEXT
    ep = [e for e in storage.list_episodes(tmp_path, secret) if e.get("via") == "shortcut"]
    assert len(ep) == 1
    assert ep[0]["chars"] == len(ARTICLE_TEXT)


def test_share_text_page_submit_without_cookie_shows_connect(client, monkeypatch):
    calls = wire_spawn(monkeypatch)
    resp = client.post("/share/text", data={"text": ARTICLE_TEXT, "title": "T"})
    assert "Link this browser" in resp.text
    assert calls == []


def test_share_text_page_submit_blocked_feed_shows_suspended(client, monkeypatch):
    import analytics
    import app as app_module
    secret = link_browser(client)
    monkeypatch.setattr(
        app_module, "BLOCKED_FEED_HASHES", {analytics.feed_hash(secret)},
    )
    calls = wire_spawn(monkeypatch)

    resp = client.post("/share/text", data={"text": ARTICLE_TEXT, "title": "T"})

    assert "Feed suspended" in resp.text
    assert calls == []


def test_share_text_page_submit_with_no_text_explains(client, monkeypatch, tmp_path):
    secret = link_browser(client)
    calls = wire_spawn(monkeypatch)

    resp = client.post("/share/text", data={"text": "  ", "title": "T"})

    assert "Couldn't add" in resp.text
    assert calls == []
    failed = [
        e for e in storage.list_episodes(tmp_path, secret) if e["status"] == "failed"
    ]
    assert len(failed) == 1      # visible in the feed, like a failed /share


def test_share_text_page_submit_over_the_length_limit_explains(client, monkeypatch):
    import ingest
    link_browser(client)
    calls = wire_spawn(monkeypatch)

    resp = client.post("/share/text", data={
        "text": "x" * (ingest.MAX_BODY_CHARS + 1), "title": "T",
    })

    assert "Couldn't add" in resp.text
    assert "too long" in resp.text.lower()
    assert calls == []


def test_share_text_rejects_a_truncated_stub(client, monkeypatch, tmp_path):
    """A URL that lost most of the article (unencoded text breaks at the first
    space) used to become an 8-second episode. Below ingest's teaser threshold,
    say so instead of narrating the stub."""
    secret = link_browser(client)
    calls = wire_spawn(monkeypatch)

    resp = client.post("/share/text", data={
        "text": "Cycling's stakeholders must reflect on a teenager's death.",
        "title": "",
    })

    assert "Couldn't add" in resp.text
    assert "58 characters" in resp.text        # names what actually arrived
    assert calls == []
    failed = [
        e for e in storage.list_episodes(tmp_path, secret) if e["status"] == "failed"
    ]
    assert len(failed) == 1


def test_share_text_added_page_reports_the_length(client, monkeypatch):
    """So a short extraction is visible at a glance, not only by ear."""
    link_browser(client)
    wire_spawn(monkeypatch)

    resp = client.post("/share/text", data={"text": ARTICLE_TEXT, "title": "On Time"})

    assert f"{len(ARTICLE_TEXT):,} characters" in resp.text


def test_share_text_failure_records_what_arrived(client, monkeypatch, tmp_path):
    """A too-short share is only diagnosable if the payload is kept: the
    difference between a link preview and a truncated article is what it says,
    not how long it is."""
    secret = link_browser(client)
    wire_spawn(monkeypatch)

    client.post("/share/text", data={"text": "￼Cycling's stakeholders", "title": ""})

    failed = [
        e for e in storage.list_episodes(tmp_path, secret) if e["status"] == "failed"
    ][0]
    assert "Shortcut sent:" in failed["description"]
    assert "Cycling's stakeholders" in failed["description"]


def test_share_text_page_offers_a_clipboard_paste_button(client):
    """Text too big for a URL arrives via the clipboard instead: iOS allows
    navigator.clipboard.readText() on a tap (with its own confirmation), so
    the whole article lands in one tap and no size limit applies."""
    link_browser(client)
    page = client.get("/share/text").text

    assert "clipboard.readText" in page
    assert "Paste article" in page
    # The manual textarea stays as the fallback when the read is refused.
    assert 'name="text"' in page
