import json
from dataclasses import dataclass
from uuid import uuid4

from .db import DB_PATH, _SESSION_SCHEMA, connect

VALID_EVENT_TYPES = frozenset({
    "task_start", "task_complete", "failure", "replan",
    "commit", "internet_access", "parked",
})
VALID_OUTCOMES = frozenset({"success", "parked", "failed"})


@dataclass
class Event:
    id: int
    session_id: str
    agent: str
    event_type: str
    content: str
    metadata: dict
    timestamp: str


@dataclass
class Session:
    id: str
    project_id: int | None
    description: str
    status: str
    outcome: str | None
    started_at: str
    closed_at: str | None


class SessionMemory:
    def __init__(self, db_path: str = DB_PATH):
        self._db = db_path
        with connect(self._db) as conn:
            conn.executescript(_SESSION_SCHEMA)

    # ── Write ─────────────────────────────────────────────────────────────────

    def create_session(self, project_id: int | None = None, description: str = "") -> str:
        session_id = str(uuid4())
        with connect(self._db) as conn:
            conn.execute(
                "INSERT INTO sessions (id, project_id, description) VALUES (?,?,?)",
                (session_id, project_id, description),
            )
        return session_id

    def log_event(
        self,
        session_id: str,
        agent: str,
        event_type: str,
        content: str = "",
        metadata: dict = None,
    ) -> int:
        if event_type not in VALID_EVENT_TYPES:
            raise ValueError(f"Invalid event_type: {event_type!r}. Must be one of {sorted(VALID_EVENT_TYPES)}")
        with connect(self._db) as conn:
            cur = conn.execute(
                "INSERT INTO session_events (session_id, agent, event_type, content, metadata) VALUES (?,?,?,?,?)",
                (session_id, agent, event_type, content, json.dumps(metadata or {})),
            )
            return cur.lastrowid

    def close_session(self, session_id: str, outcome: str) -> None:
        if outcome not in VALID_OUTCOMES:
            raise ValueError(f"Invalid outcome: {outcome!r}. Must be one of {sorted(VALID_OUTCOMES)}")
        with connect(self._db) as conn:
            conn.execute(
                "UPDATE sessions SET status='closed', outcome=?, closed_at=datetime('now') WHERE id=?",
                (outcome, session_id),
            )

    # ── Read ──────────────────────────────────────────────────────────────────

    def get_session(self, session_id: str) -> Session | None:
        with connect(self._db) as conn:
            row = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        if not row:
            return None
        return Session(**{k: row[k] for k in row.keys()})

    def get_session_log(self, session_id: str) -> list[Event]:
        with connect(self._db) as conn:
            rows = conn.execute(
                "SELECT * FROM session_events WHERE session_id=? ORDER BY id",
                (session_id,),
            ).fetchall()
        return [
            Event(
                id=r["id"],
                session_id=r["session_id"],
                agent=r["agent"],
                event_type=r["event_type"],
                content=r["content"] or "",
                metadata=json.loads(r["metadata"] or "{}"),
                timestamp=r["timestamp"],
            )
            for r in rows
        ]

    def list_sessions(self, project_id: int | None = None, limit: int = 20) -> list[Session]:
        with connect(self._db) as conn:
            if project_id is not None:
                rows = conn.execute(
                    "SELECT * FROM sessions WHERE project_id=? ORDER BY started_at DESC LIMIT ?",
                    (project_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM sessions ORDER BY started_at DESC LIMIT ?", (limit,)
                ).fetchall()
        return [Session(**{k: r[k] for k in r.keys()}) for r in rows]
