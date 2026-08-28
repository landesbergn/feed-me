"""The Producer (v3.36): notes, the assignment desk, and podcast-app loop-back.

Spec: docs/superpowers/specs/2026-08-26-the-producer.html
"""

import storage
from tests.conftest import FakeResponse
from tests.test_agent_api import ARTICLE_HTML, make_feed, wire_fake_pipeline


# --- storage: requests -------------------------------------------------------

def test_add_and_list_requests(client, tmp_path):
    secret = make_feed(client)
    req = storage.add_request(tmp_path, secret, "Something on the Ottoman Empire")
    assert req["id"] and req["status"] == "open" and req["source"] == "owner"
    listed = storage.list_requests(tmp_path, secret)
    assert [r["id"] for r in listed] == [req["id"]]


def test_complete_request_records_note(client, tmp_path):
    secret = make_feed(client)
    req = storage.add_request(tmp_path, secret, "Three pieces for the flight")
    assert storage.complete_request(tmp_path, secret, req["id"], note="Queued them up")
    done = storage.list_requests(tmp_path, secret)[0]
    assert done["status"] == "done"
    assert done["done_note"] == "Queued them up"
    assert done["done_ts"]
    assert not storage.complete_request(tmp_path, secret, "nope")


def test_open_requests_dedupe_and_caps(client, tmp_path):
    secret = make_feed(client)
    a = storage.add_request(tmp_path, secret, "same text")
    b = storage.add_request(tmp_path, secret, "same text")
    assert a["id"] == b["id"]                       # open dupes collapse
    storage.complete_request(tmp_path, secret, a["id"])
    c = storage.add_request(tmp_path, secret, "same text")
    assert c["id"] != a["id"]                       # done ones don't block

    import pytest
    with pytest.raises(ValueError):
        storage.add_request(tmp_path, secret, "")
    with pytest.raises(ValueError):
        storage.add_request(tmp_path, secret, "x" * 501)
    for i in range(19):                             # 1 open already ("same text")
        storage.add_request(tmp_path, secret, f"req {i}")
    with pytest.raises(ValueError):
        storage.add_request(tmp_path, secret, "one too many")


def test_requests_never_pollute_episodes(client, tmp_path):
    secret = make_feed(client)
    storage.add_request(tmp_path, secret, "keep me out of the feed")
    slugs = {e["slug"] for e in storage.list_episodes(tmp_path, secret)}
    assert "requests" not in slugs and "inbox" not in slugs


# --- producer's note: through the API, the page, and the feed ----------------

def _ready_episode_with_note(client, monkeypatch, fake_http, fake_openai, secret):
    fake_http.responses["https://example.com/a"] = FakeResponse(
        status_code=200, text=ARTICLE_HTML,
    )
    wire_fake_pipeline(monkeypatch, fake_http, fake_openai)
    resp = client.post(
        f"/u/{secret}/episodes",
        json={"url": "https://example.com/a", "note": "You asked about time; this one is a gem."},
    )
    assert resp.status_code == 202
    return resp.json()["slug"]


def test_note_survives_to_ready_and_shows_everywhere(
    client, monkeypatch, fake_http, fake_openai, tmp_path,
):
    secret = make_feed(client)
    slug = _ready_episode_with_note(client, monkeypatch, fake_http, fake_openai, secret)

    ep = next(e for e in storage.list_episodes(tmp_path, secret) if e["slug"] == slug)
    assert ep["status"] == "ready"
    assert ep["note"] == "You asked about time; this one is a gem."

    page = client.get(f"/u/{secret}").text
    assert "this one is a gem" in page

    feed = client.get(f"/u/{secret}/feed.xml").text
    assert "Producer&#39;s note:" in feed or "Producer's note:" in feed
    assert "this one is a gem" in feed


def test_note_rejected_when_invalid(client):
    secret = make_feed(client)
    r = client.post(f"/u/{secret}/episodes",
                    json={"url": "https://example.com/a", "note": 5})
    assert r.status_code == 400
    r = client.post(f"/u/{secret}/episodes",
                    json={"url": "https://example.com/a", "note": "x" * 301})
    assert r.status_code == 400


# --- loop-back: feedback links in the feed, the tap records a request --------

def test_feed_carries_feedback_links(
    client, monkeypatch, fake_http, fake_openai,
):
    secret = make_feed(client)
    slug = _ready_episode_with_note(client, monkeypatch, fake_http, fake_openai, secret)
    feed = client.get(f"/u/{secret}/feed.xml").text
    assert f"/u/{secret}/feedback?slug={slug}&amp;v=more" in feed
    assert f"/u/{secret}/feedback?slug={slug}&amp;v=less" in feed
    assert "More like this" in feed
    assert "Not for me" in feed


def test_feedback_tap_records_listener_request(
    client, monkeypatch, fake_http, fake_openai, tmp_path,
):
    secret = make_feed(client)
    slug = _ready_episode_with_note(client, monkeypatch, fake_http, fake_openai, secret)

    r = client.get(f"/u/{secret}/feedback?slug={slug}&v=more")
    assert r.status_code == 200
    assert "Noted" in r.text
    reqs = storage.list_requests(tmp_path, secret)
    assert len(reqs) == 1
    assert reqs[0]["source"] == "listener"
    assert "More like" in reqs[0]["text"]

    client.get(f"/u/{secret}/feedback?slug={slug}&v=more")   # tap twice
    assert len(storage.list_requests(tmp_path, secret)) == 1  # deduped while open

    assert client.get(f"/u/{secret}/feedback?slug={slug}&v=weird").status_code == 404
    assert client.get(f"/u/{secret}/feedback?slug=missing&v=more").status_code == 404


def test_feedback_page_has_no_ga(client, monkeypatch, fake_http, fake_openai):
    secret = make_feed(client)
    slug = _ready_episode_with_note(client, monkeypatch, fake_http, fake_openai, secret)
    body = client.get(f"/u/{secret}/feedback?slug={slug}&v=less").text
    assert "googletagmanager" not in body


# --- the requests API (agent contract) ---------------------------------------

def test_requests_api_roundtrip(client):
    secret = make_feed(client)
    created = client.post(f"/u/{secret}/requests", json={"text": "A poem, narrated"})
    assert created.status_code == 201
    rid = created.json()["id"]

    listed = client.get(f"/u/{secret}/requests")
    assert listed.status_code == 200
    body = listed.json()
    assert body["requests"][0]["id"] == rid
    assert body["requests"][0]["status"] == "open"

    done = client.post(f"/u/{secret}/requests/{rid}/complete",
                       json={"note": "Done: narrated a Rilke poem"})
    assert done.status_code == 200
    assert done.json() == {"id": rid, "status": "done"}

    after = client.get(f"/u/{secret}/requests").json()
    assert after["requests"][0]["status"] == "done"
    assert after["requests"][0]["done_note"] == "Done: narrated a Rilke poem"


def test_requests_api_errors(client):
    secret = make_feed(client)
    assert client.get("/u/nope/requests").status_code == 404
    assert client.post(f"/u/{secret}/requests", json={}).status_code == 400
    assert client.post(f"/u/{secret}/requests", json={"text": "x" * 501}).status_code == 400
    r = client.post(f"/u/{secret}/requests/unknown/complete", json={})
    assert r.status_code == 404
    assert r.json()["error"] == "not_found"


def test_requests_post_is_json_only(client, tmp_path):
    # The page form is gone (the agent records requests from chat), so a
    # form-encoded post is just malformed JSON now.
    secret = make_feed(client)
    r = client.post(f"/u/{secret}/requests", data={"text": "From a form"})
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_request"
    assert storage.list_requests(tmp_path, secret) == []


# --- the page ----------------------------------------------------------------

def test_page_shows_the_producers_desk(client, tmp_path):
    secret = make_feed(client)
    storage.add_request(tmp_path, secret, "Something about lighthouses")
    body = client.get(f"/u/{secret}").text
    assert "Your producer's desk" in body
    assert 'id="requests-section"' in body
    assert "Something about lighthouses" in body


def test_desk_is_pure_status(client, tmp_path):
    # The interaction model: the user talks to their agent in chat, never to
    # the website. The desk takes no input and offers no buttons; suggestions
    # for what to ask come through the chat (the tool results carry them).
    secret = make_feed(client)
    body = client.get(f"/u/{secret}").text
    assert f'action="/u/{secret}/requests"' not in body
    assert "req-form" not in body
    assert "ask-chip" not in body
    assert "in your chat" in body


def test_desk_empty_state_explains_itself(client):
    secret = make_feed(client)
    body = client.get(f"/u/{secret}").text
    assert "Nothing on the desk" in body


def test_requests_partial_serves_fragment(client, tmp_path):
    secret = make_feed(client)
    storage.add_request(tmp_path, secret, "Fragment check")
    body = client.get(f"/u/{secret}/requests_partial").text
    assert "Fragment check" in body
    assert "<html" not in body
