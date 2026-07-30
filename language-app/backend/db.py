"""SQLite persistence for Lingua. Deliberately dependency-free (stdlib sqlite3)
so this app never needs ARIA's Supabase/Postgres stack — it is a standalone product."""

from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import threading
from collections.abc import Iterator
from datetime import UTC, datetime

from .config import settings

_lock = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT,
    display_name TEXT NOT NULL,
    native_lang TEXT NOT NULL,
    target_lang TEXT NOT NULL,
    level TEXT NOT NULL DEFAULT 'A1',
    interests TEXT NOT NULL DEFAULT '[]',
    xp INTEGER NOT NULL DEFAULT 0,
    streak_days INTEGER NOT NULL DEFAULT 0,
    hearts INTEGER NOT NULL DEFAULT 5,
    created_at TEXT NOT NULL,
    last_active_date TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vocab_progress (
    user_id TEXT NOT NULL,
    vocab_key TEXT NOT NULL,
    ease_factor REAL NOT NULL DEFAULT 2.5,
    interval_days REAL NOT NULL DEFAULT 0,
    repetitions INTEGER NOT NULL DEFAULT 0,
    due_at TEXT NOT NULL,
    last_result TEXT NOT NULL DEFAULT '',
    mistake_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, vocab_key)
);

CREATE TABLE IF NOT EXISTS lesson_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    unit_id TEXT NOT NULL,
    score REAL NOT NULL,
    completed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS unit_mastery (
    user_id TEXT NOT NULL,
    unit_id TEXT NOT NULL,
    best_score REAL NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    mastered INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, unit_id)
);

CREATE TABLE IF NOT EXISTS conversation_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(settings.db_path), exist_ok=True)
    conn = sqlite3.connect(settings.db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


_conn: sqlite3.Connection | None = None


def _migrate(conn: sqlite3.Connection) -> None:
    """Adds columns/indexes introduced after a table already existed on disk.
    CREATE TABLE IF NOT EXISTS alone won't retrofit a pre-existing users.db."""
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "email" not in existing_cols:
        conn.execute("ALTER TABLE users ADD COLUMN email TEXT")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email) WHERE email IS NOT NULL")
    conn.commit()


def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        with _lock:
            if _conn is None:
                _conn = _connect()
                _conn.executescript(_SCHEMA)
                _conn.commit()
                _migrate(_conn)
    return _conn


@contextlib.contextmanager
def cursor() -> Iterator[sqlite3.Cursor]:
    conn = get_conn()
    with _lock:
        cur = conn.cursor()
        try:
            yield cur
            conn.commit()
        finally:
            cur.close()


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def today_str() -> str:
    return datetime.now(UTC).date().isoformat()


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    if "interests" in d:
        d["interests"] = json.loads(d["interests"] or "[]")
    return d


def reset_for_tests(db_path: str) -> None:
    """Used by the test-suite to point at an isolated temp db."""
    global _conn
    object.__setattr__(settings, "db_path", db_path)
    _conn = None
