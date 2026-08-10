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


_SEED = """
INSERT OR IGNORE INTO apps (name, description, route, backend_port) VALUES
    ('Chat',             'AI chat interface',                        '/chat',      8010),
    ('Writer',           'AI writing assistant',                     '/writer',    8011),
    ('Coding Assistant', 'AI coding and GitHub integration',         '/coding',    8012),
    ('Autocoder',        'Autonomous multi-agent development system','/autocoder', 8050);
"""


def init_db():
    with _open() as conn:
        conn.executescript(_SCHEMA)
        conn.executescript(_SEED)
        # Idempotent migrations — ignored if columns already exist
        for sql in [
            "ALTER TABLE agents ADD COLUMN app_id INTEGER REFERENCES apps(id)",
            "ALTER TABLE agents ADD COLUMN calls TEXT DEFAULT '[]'",
            "CREATE UNIQUE INDEX IF NOT EXISTS agents_name_unique ON agents(name)",
        ]:
            try:
                conn.execute(sql)
            except Exception:
                pass
        _seed_writer_agents(conn)


def _seed_writer_agents(conn):
    writer_id = conn.execute("SELECT id FROM apps WHERE name='Writer'").fetchone()
    if not writer_id:
        return
    wid = writer_id[0]
    agents = [
        ("platform_writer_story_architect",  "Phase 1A: North Star conversation",      '["platform_writer_bible_agent"]'),
        ("platform_writer_bible_agent",       "Phase 1B: Tiered bible iteration",       '[]'),
        ("platform_writer_research_agent",    "Phase 2: Research & entity completion",  '[]'),
        ("platform_writer_writer_agent",      "Phase 3: Scene prose generation",        '["platform_writer_qa_agent"]'),
        ("platform_writer_qa_agent",          "Phase 3: Scene quality & consistency",   '["platform_writer_bible_updater"]'),
        ("platform_writer_bible_updater",     "Phase 3: Bible update & Git commit",     '[]'),
    ]
    for name, desc, calls in agents:
        conn.execute(
            "INSERT OR IGNORE INTO agents (name, description, model, app_id, calls) VALUES (?,?,?,?,?)",
            (name, desc, "", wid, calls),
        )


@contextmanager
def _open():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
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
