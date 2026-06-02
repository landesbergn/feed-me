"""Self-hosted analytics for Feed Me.

A single SQLite table on the Fly volume. No third party, no runtime dependency
beyond the standard library. Per-feed identity is a one-way hash so analytics
data can never reveal a private feed URL.

The DB lives in its own subdirectory (DATA_DIR/_analytics/) so the
/data/<secret>/ feed level stays pure for any feed-enumeration code.
"""
import hashlib
import json
import logging
import sqlite3
import time
from pathlib import Path

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        INTEGER NOT NULL,
    event     TEXT    NOT NULL,
    feed_hash TEXT,
    path      TEXT,
    props     TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_event ON events(event);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
"""


def feed_hash(secret: str) -> str:
    """One-way, truncated. Stable per feed, never reversible to the secret."""
    return hashlib.sha256(secret.encode()).hexdigest()[:12]


def _connect(db_path) -> sqlite3.Connection:
    """Open a short-lived connection, creating the dir + schema on first use.

    A new connection per call (not a shared module-level one): article ingest
    runs in background daemon threads, so a shared connection would be unsafe.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    return conn


def track(db_path, event, *, feed_hash_val=None, path=None, props=None, ts=None) -> None:
    """Insert one event. MUST never raise — analytics can't break a request.

    `feed_hash_val` is the already-hashed feed id (see feed_hash()); the raw
    secret must never be passed here.
    """
    try:
        conn = _connect(db_path)
        with conn:
            conn.execute(
                "INSERT INTO events (ts, event, feed_hash, path, props) "
                "VALUES (?, ?, ?, ?, ?)",
                (ts if ts is not None else int(time.time()),
                 event, feed_hash_val, path,
                 json.dumps(props) if props else None),
            )
        conn.close()
    except Exception:
        log.debug("analytics.track failed", exc_info=True)


def summary(db_path) -> dict:
    """Aggregate counts for the stats page / export. Read-only; never raises
    on a missing DB (creates an empty one)."""
    conn = _connect(db_path)
    try:
        cur = conn.cursor()

        # `where` must always be a hardcoded literal here — never user input.
        def count(where: str, args=()) -> int:
            return cur.execute(
                f"SELECT COUNT(*) FROM events WHERE {where}", args
            ).fetchone()[0]

        feeds_created = count("event = 'feed_created'")
        articles_shared = count("event = 'article_shared'")
        page_views = count("event = 'page_view'")

        page_views_by_path = {"landing": 0, "settings": 0, "share": 0}
        for path, n in cur.execute(
            "SELECT path, COUNT(*) FROM events "
            "WHERE event = 'page_view' GROUP BY path"
        ).fetchall():
            if path in page_views_by_path:
                page_views_by_path[path] = n

        active_feeds = cur.execute(
            "SELECT COUNT(DISTINCT feed_hash) FROM events "
            "WHERE feed_hash IS NOT NULL"
        ).fetchone()[0]

        by_day = [
            {"day": day, "page_views": pv, "shares": sh, "feeds": fc}
            for (day, pv, sh, fc) in cur.execute(
                "SELECT strftime('%Y-%m-%d', ts, 'unixepoch') AS day, "
                "  SUM(event = 'page_view'), "
                "  SUM(event = 'article_shared'), "
                "  SUM(event = 'feed_created') "
                "FROM events GROUP BY day ORDER BY day"
            ).fetchall()
        ]

        top_feeds = [
            {"feed_hash": fh, "shares": sh}
            for (fh, sh) in cur.execute(
                "SELECT feed_hash, COUNT(*) AS shares FROM events "
                "WHERE event = 'article_shared' AND feed_hash IS NOT NULL "
                "GROUP BY feed_hash ORDER BY shares DESC LIMIT 20"
            ).fetchall()
        ]

        return {
            "feeds_created": feeds_created,
            "articles_shared": articles_shared,
            "page_views": page_views,
            "page_views_by_path": page_views_by_path,
            "active_feeds": active_feeds,
            "by_day": by_day,
            "top_feeds": top_feeds,
        }
    finally:
        conn.close()


def all_events(db_path) -> list[dict]:
    """Return all raw events ordered by ts. Never raises on a missing DB."""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT ts, event, feed_hash, path, props FROM events ORDER BY ts"
        ).fetchall()
        return [
            {"ts": ts, "event": ev, "feed_hash": fh, "path": p, "props": pr}
            for (ts, ev, fh, p, pr) in rows
        ]
    finally:
        conn.close()
