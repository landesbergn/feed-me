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
    analytics.track(db, "feed_created", feed_hash_val="aaa")
    analytics.track(db, "article_shared", feed_hash_val="aaa", path="share")
    analytics.track(db, "article_shared", feed_hash_val="bbb", path="share")
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


def test_summary_basic_counts(tmp_path):
    db = tmp_path / "_analytics" / "analytics.db"
    analytics.track(db, "feed_created", feed_hash_val="aaa")
    analytics.track(db, "article_shared", feed_hash_val="aaa", path="share")
    analytics.track(db, "article_shared", feed_hash_val="bbb", path="share")
    analytics.track(db, "page_view", path="landing")
    analytics.track(db, "page_view", feed_hash_val="aaa", path="settings")

    s = analytics.summary(db)
    assert s["feeds_created"] == 1
    assert s["articles_shared"] == 2
    assert s["page_views"] == 2
    assert s["page_views_by_path"]["landing"] == 1
    assert s["page_views_by_path"]["settings"] == 1
    assert s["page_views_by_path"]["share"] == 0
    assert s["active_feeds"] == 2  # distinct non-null feed_hash across all events


def test_summary_by_day_and_top_feeds(tmp_path):
    db = tmp_path / "_analytics" / "analytics.db"
    day1 = 1_750_000_000          # some fixed unix ts
    day2 = day1 + 86_400
    analytics.track(db, "article_shared", feed_hash_val="aaa", ts=day1)
    analytics.track(db, "article_shared", feed_hash_val="aaa", ts=day1)
    analytics.track(db, "page_view", path="landing", ts=day2)

    s = analytics.summary(db)
    days = {row["day"]: row for row in s["by_day"]}
    assert len(days) == 2

    from datetime import datetime
    from zoneinfo import ZoneInfo
    pt = ZoneInfo("America/Los_Angeles")
    day1_str = datetime.fromtimestamp(day1, tz=pt).strftime("%Y-%m-%d")
    day2_str = datetime.fromtimestamp(day2, tz=pt).strftime("%Y-%m-%d")
    assert days[day1_str]["shares"] == 2
    assert days[day1_str]["page_views"] == 0
    assert days[day2_str]["page_views"] == 1
    assert days[day2_str]["shares"] == 0

    assert s["top_feeds"][0]["feed_hash"] == "aaa"
    assert s["top_feeds"][0]["shares"] == 2


def test_summary_by_day_buckets_by_pacific_not_utc(tmp_path):
    # 2026-06-02 05:00 UTC is 2026-06-01 22:00 in Pacific (PDT, UTC-7), so the
    # event must land on the Pacific day 2026-06-01, not the UTC day 2026-06-02.
    db = tmp_path / "_analytics" / "analytics.db"
    ts = 1780376400
    analytics.track(db, "article_shared", feed_hash_val="aaa", ts=ts)

    days = {row["day"]: row for row in analytics.summary(db)["by_day"]}
    assert "2026-06-01" in days
    assert "2026-06-02" not in days
    assert days["2026-06-01"]["shares"] == 1


def test_summary_recent_shares_when_is_pacific_time(tmp_path):
    # Same boundary instant: the rendered "when" must read in Pacific time.
    db = tmp_path / "_analytics" / "analytics.db"
    analytics.track(db, "article_shared", feed_hash_val="aaa",
                    props={"url": "https://ex.com/a", "title": "A"}, ts=1780376400)

    rs = analytics.summary(db)["recent_shares"]
    assert rs[0]["when"] == "2026-06-01 22:00"


def test_pacific_zone_resolves_without_system_tzdata():
    # The slim prod container has no /usr/share/zoneinfo; the bundled tzdata
    # package must supply the zone, else `PT = ZoneInfo(...)` crashes app import.
    # Run in a subprocess with the system tz path emptied: this simulates the
    # slim container faithfully AND keeps the global zoneinfo state mutation out
    # of the test process (otherwise it leaks across the suite).
    import subprocess
    import sys
    code = (
        "import zoneinfo; zoneinfo.reset_tzpath([]); "
        "zoneinfo.ZoneInfo('America/Los_Angeles')"
    )
    result = subprocess.run([sys.executable, "-c", code],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_summary_recent_shares_includes_url_and_title(tmp_path):
    db = tmp_path / "_analytics" / "analytics.db"
    analytics.track(db, "article_shared", feed_hash_val="aaa", path="share",
                    props={"url": "https://ex.com/a", "title": "Article A"}, ts=100)
    analytics.track(db, "article_shared", feed_hash_val="bbb", path="share",
                    props={"url": "https://ex.com/b", "title": "Article B"}, ts=200)
    # An older share with no props (pre-feature) must not break recent_shares.
    analytics.track(db, "article_shared", feed_hash_val="ccc", path="share", ts=50)

    rs = analytics.summary(db)["recent_shares"]
    assert rs[0]["title"] == "Article B"          # newest first
    assert rs[0]["url"] == "https://ex.com/b"
    assert rs[0]["feed_hash"] == "bbb"
    assert "when" in rs[0]
    assert rs[-1]["url"] is None                   # the no-props one
    assert rs[-1]["title"] is None


def test_summary_empty_db(tmp_path):
    db = tmp_path / "_analytics" / "analytics.db"
    s = analytics.summary(db)
    assert s["feeds_created"] == 0
    assert s["articles_shared"] == 0
    assert s["page_views"] == 0
    assert s["active_feeds"] == 0
    assert s["by_day"] == []
    assert s["top_feeds"] == []
    assert s["recent_shares"] == []


def test_feed_last_accessed_returns_max_ts_per_hash(tmp_path):
    db = tmp_path / "_analytics" / "analytics.db"
    analytics.track(db, "feed_created", feed_hash_val="aaa", ts=100)
    analytics.track(db, "page_view", feed_hash_val="aaa", path="settings", ts=300)
    analytics.track(db, "article_shared", feed_hash_val="bbb", path="share", ts=200)
    analytics.track(db, "page_view", path="landing", ts=999)  # no feed_hash
    result = analytics.feed_last_accessed(db)
    assert result == {"aaa": 300, "bbb": 200}


def test_feed_last_accessed_missing_db_returns_empty(tmp_path):
    db = tmp_path / "_analytics" / "analytics.db"
    assert analytics.feed_last_accessed(db) == {}


def test_feed_last_accessed_all_null_feed_hash_returns_empty(tmp_path):
    db = tmp_path / "_analytics" / "analytics.db"
    analytics.track(db, "page_view", path="landing", ts=999)  # no feed_hash
    assert analytics.feed_last_accessed(db) == {}


def test_feed_share_counts_counts_only_shares_per_hash(tmp_path):
    db = tmp_path / "_analytics" / "analytics.db"
    analytics.track(db, "article_shared", feed_hash_val="aaa", path="share")
    analytics.track(db, "article_shared", feed_hash_val="aaa", path="share")
    analytics.track(db, "article_shared", feed_hash_val="bbb", path="share")
    analytics.track(db, "page_view", feed_hash_val="aaa", path="settings")  # not a share
    analytics.track(db, "feed_created", feed_hash_val="ccc")               # not a share
    result = analytics.feed_share_counts(db)
    assert result == {"aaa": 2, "bbb": 1}


def test_feed_share_counts_empty_db_returns_empty(tmp_path):
    db = tmp_path / "_analytics" / "analytics.db"
    assert analytics.feed_share_counts(db) == {}


def test_all_events_returns_rows_ordered_and_empty_on_missing(tmp_path):
    db = tmp_path / "_analytics" / "analytics.db"
    assert analytics.all_events(db) == []   # missing DB → empty, no raise
    analytics.track(db, "feed_created", feed_hash_val="aaa", ts=100)
    analytics.track(db, "page_view", path="landing", ts=50)
    rows = analytics.all_events(db)
    assert [r["ts"] for r in rows] == [50, 100]   # ordered by ts
    assert {r["event"] for r in rows} == {"feed_created", "page_view"}
