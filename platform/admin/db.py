import os
import sqlite3
from contextlib import contextmanager

DB_PATH = os.environ.get("DB_PATH", "/opt/platform/data/platform.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS apps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    route TEXT NOT NULL UNIQUE,
    port INTEGER,
    backend_port INTEGER,
    status TEXT DEFAULT 'active',
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS agents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    model TEXT NOT NULL,
    tools TEXT DEFAULT '[]',
    memory_scope TEXT DEFAULT 'session',
    ui_type TEXT DEFAULT 'none',
    ui_route TEXT,
    backend_port INTEGER,
    system_prompt TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS internet_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    agent_name TEXT,
    action TEXT,
    url TEXT,
    results_summary TEXT,
    used_in_output INTEGER DEFAULT 0,
    timestamp TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS platform_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service TEXT NOT NULL,
    event_type TEXT NOT NULL,
    message TEXT,
    metadata TEXT DEFAULT '{}',
    timestamp TEXT DEFAULT (datetime('now'))
);
"""


def init_db():
    with _open() as conn:
        conn.executescript(_SCHEMA)


@contextmanager
def _open():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_db():
    """FastAPI dependency — yields a committed-on-success connection."""
    with _open() as conn:
        yield conn


def next_agent_port(conn) -> int:
    """Return lowest unused port >= 8100."""
    used = {r[0] for r in conn.execute(
        "SELECT backend_port FROM agents WHERE backend_port IS NOT NULL"
    ).fetchall()}
    p = 8100
    while p in used:
        p += 1
    return p
