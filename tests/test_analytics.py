import analytics


def test_feed_hash_is_stable_12_chars_and_not_the_secret():
    h1 = analytics.feed_hash("supersecret")
    h2 = analytics.feed_hash("supersecret")
    assert h1 == h2
    assert len(h1) == 12
    assert h1 != "supersecret"
    assert "supersecret" not in h1
    assert analytics.feed_hash("other") != h1


def test_track_writes_rows_readable_via_sql(tmp_path):
    import sqlite3
    db = tmp_path / "_analytics" / "analytics.db"
    analytics.track(db, "feed_created", feed_hash="aaa")
    analytics.track(db, "article_shared", feed_hash="aaa", path="share")
    analytics.track(db, "article_shared", feed_hash="bbb", path="share")
    analytics.track(db, "page_view", path="landing")

    conn = sqlite3.connect(db)
    try:
        total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        shares = conn.execute(
            "SELECT COUNT(*) FROM events WHERE event = 'article_shared'"
        ).fetchone()[0]
        distinct_feeds = conn.execute(
            "SELECT COUNT(DISTINCT feed_hash) FROM events WHERE feed_hash IS NOT NULL"
        ).fetchone()[0]
        landing_path = conn.execute(
            "SELECT path FROM events WHERE event = 'page_view'"
        ).fetchone()[0]
    finally:
        conn.close()

    assert total == 4
    assert shares == 2
    assert distinct_feeds == 2
    assert landing_path == "landing"


def test_track_creates_parent_dir(tmp_path):
    db = tmp_path / "nested" / "_analytics" / "analytics.db"
    analytics.track(db, "page_view", path="landing")
    assert db.exists()


def test_track_never_raises_on_bad_path(tmp_path):
    # A path whose parent is a FILE (cannot mkdir) must not raise.
    bad_parent = tmp_path / "afile"
    bad_parent.write_text("x")
    analytics.track(bad_parent / "sub" / "analytics.db", "page_view")
    # no assertion needed — the test passes if track() did not raise
