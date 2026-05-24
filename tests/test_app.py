def test_healthz(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.text == "ok"


def test_landing_page_renders(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Get my feed" in response.text
    assert "feed-me" in response.text.lower()


def test_post_create_redirects_to_user_settings(client):
    response = client.post("/create", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/u/")
    secret = response.headers["location"].split("/u/")[1]
    assert len(secret) >= 32


def test_post_create_makes_user_dir(client, tmp_path):
    response = client.post("/create", follow_redirects=False)
    secret = response.headers["location"].split("/u/")[1]
    assert (tmp_path / secret / "settings.json").exists()
