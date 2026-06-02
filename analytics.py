"""Self-hosted analytics for Feed Me.

A single SQLite table on the Fly volume. No third party, no runtime dependency
beyond the standard library. Per-feed identity is a one-way hash so analytics
data can never reveal a private feed URL.

The DB lives in its own subdirectory (DATA_DIR/_analytics/) so the
/data/<secret>/ feed level stays pure for any feed-enumeration code.
"""
import hashlib
import json
import sqlite3
import time
from pathlib import Path

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


def track(db_path, event, *, feed_hash=None, path=None, props=None, ts=None) -> None:
    """Insert one event. MUST never raise — analytics can't break a request."""
    try:
        conn = _connect(db_path)
        with conn:
            conn.execute(
                "INSERT INTO events (ts, event, feed_hash, path, props) "
                "VALUES (?, ?, ?, ?, ?)",
                (ts if ts is not None else int(time.time()),
                 event, feed_hash, path,
                 json.dumps(props) if props else None),
            )
        conn.close()
    except Exception:
        pass  # swallow — never propagate analytics failure to the caller
