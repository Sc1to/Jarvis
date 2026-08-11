from dataclasses import dataclass

from .db import DB_PATH, _PROJECT_SCHEMA, connect


@dataclass
class Project:
    id: int
    name: str
    description: str | None
    created_at: str


@dataclass
class Decision:
    id: int
    project_id: int
    decision_type: str
    content: str
    rationale: str | None
    created_at: str


@dataclass
class Issue:
    id: int
    project_id: int
    description: str
    status: str
    resolution: str | None
    created_at: str
    resolved_at: str | None


class ProjectMemory:
    def __init__(self, db_path: str = DB_PATH):
        self._db = db_path
        with connect(self._db) as conn:
            conn.executescript(_PROJECT_SCHEMA)

    # ── Projects ──────────────────────────────────────────────────────────────

    def create_project(self, name: str, description: str = "") -> int:
        with connect(self._db) as conn:
            cur = conn.execute(
                "INSERT INTO autocoder_projects (name, description) VALUES (?,?)",
                (name, description),
            )
            return cur.lastrowid

    def get_project(self, project_id: int) -> Project | None:
        with connect(self._db) as conn:
            row = conn.execute(
                "SELECT * FROM autocoder_projects WHERE id=?", (project_id,)
            ).fetchone()
        if not row:
            return None
        return Project(**{k: row[k] for k in row.keys()})

    def get_project_by_name(self, name: str) -> Project | None:
        with connect(self._db) as conn:
            row = conn.execute(
                "SELECT * FROM autocoder_projects WHERE name=?", (name,)
            ).fetchone()
        if not row:
            return None
        return Project(**{k: row[k] for k in row.keys()})

    def list_projects(self) -> list[Project]:
        with connect(self._db) as conn:
            rows = conn.execute(
                "SELECT * FROM autocoder_projects ORDER BY name"
            ).fetchall()
        return [Project(**{k: r[k] for k in r.keys()}) for r in rows]

    def update_project(self, project_id: int, name: str, description: str = "") -> bool:
        with connect(self._db) as conn:
            cur = conn.execute(
                "UPDATE autocoder_projects SET name=?, description=? WHERE id=?",
                (name, description, project_id),
            )
            return cur.rowcount > 0

    def delete_project(self, project_id: int) -> bool:
        with connect(self._db) as conn:
            cur = conn.execute(
                "DELETE FROM autocoder_projects WHERE id=?", (project_id,)
            )
            return cur.rowcount > 0

    # ── Decisions ─────────────────────────────────────────────────────────────

    def save_decision(
        self,
        project_id: int,
        decision_type: str,
        content: str,
        rationale: str = "",
    ) -> int:
        with connect(self._db) as conn:
            cur = conn.execute(
                "INSERT INTO project_decisions (project_id, decision_type, content, rationale) VALUES (?,?,?,?)",
                (project_id, decision_type, content, rationale),
            )
            return cur.lastrowid

    def get_decisions(
        self, project_id: int, decision_type: str | None = None
    ) -> list[Decision]:
        with connect(self._db) as conn:
            if decision_type:
                rows = conn.execute(
                    "SELECT * FROM project_decisions WHERE project_id=? AND decision_type=? ORDER BY created_at",
                    (project_id, decision_type),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM project_decisions WHERE project_id=? ORDER BY created_at",
                    (project_id,),
                ).fetchall()
        return [Decision(**{k: r[k] for k in r.keys()}) for r in rows]

    # ── Issues ────────────────────────────────────────────────────────────────

    def save_open_issue(self, project_id: int, description: str) -> int:
        with connect(self._db) as conn:
            cur = conn.execute(
                "INSERT INTO project_issues (project_id, description) VALUES (?,?)",
                (project_id, description),
            )
            return cur.lastrowid

    def resolve_issue(self, issue_id: int, resolution: str) -> None:
        with connect(self._db) as conn:
            conn.execute(
                "UPDATE project_issues SET status='resolved', resolution=?, resolved_at=datetime('now') WHERE id=?",
                (resolution, issue_id),
            )

    def get_open_issues(self, project_id: int) -> list[Issue]:
        with connect(self._db) as conn:
            rows = conn.execute(
                "SELECT * FROM project_issues WHERE project_id=? AND status='open' ORDER BY created_at",
                (project_id,),
            ).fetchall()
        return [Issue(**{k: r[k] for k in r.keys()}) for r in rows]

    def get_all_issues(self, project_id: int) -> list[Issue]:
        with connect(self._db) as conn:
            rows = conn.execute(
                "SELECT * FROM project_issues WHERE project_id=? ORDER BY created_at",
                (project_id,),
            ).fetchall()
        return [Issue(**{k: r[k] for k in r.keys()}) for r in rows]
