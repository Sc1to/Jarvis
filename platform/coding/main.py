import json
import logging
import os
import sqlite3
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from agent import run_agent, SYSTEM_PROMPT as _CODING_DEFAULT, _overrides as _coding_overrides

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from health import health_payload

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
DEFAULT_MODEL = "qwen2.5-coder:32b"

START_TIME = time.time()
DB_PATH = "/opt/platform/data/platform.db"
PROJECTS_BASE = "/opt/platform/data/projects"
log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS user_projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    local_path TEXT NOT NULL,
    github_repo TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
"""


@asynccontextmanager
async def lifespan(_app: FastAPI):
    with _db() as conn:
        conn.executescript(_SCHEMA)
    yield


app = FastAPI(title="Platform Coding Assistant", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ── DB ────────────────────────────────────────────────────────────────────────

class _db:
    def __enter__(self):
        self._conn = sqlite3.connect(DB_PATH)
        self._conn.row_factory = sqlite3.Row
        return self._conn

    def __exit__(self, exc, *_):
        if exc:
            self._conn.rollback()
        else:
            self._conn.commit()
        self._conn.close()


def get_db():
    with _db() as conn:
        yield conn


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/prompts")
def get_prompts():
    return {"coding_assistant": _coding_overrides.get("coding_assistant", _CODING_DEFAULT)}


@app.patch("/prompts/{key}")
def set_prompt(key: str, body: dict):
    _coding_overrides[key] = body["system_prompt"]
    return {"status": "ok"}


@app.get("/health")
def health():
    return health_payload(START_TIME, "0.1.0", model=DEFAULT_MODEL)


# ── GitHub token ──────────────────────────────────────────────────────────────

@app.get("/github/token-status")
def token_status(db=Depends(get_db)):
    row = db.execute("SELECT value FROM config WHERE key='github_token'").fetchone()
    return {"configured": bool(row and row["value"])}


@app.post("/github/token")
def save_token(body: dict, db=Depends(get_db)):
    token = body.get("token", "").strip()
    if not token:
        raise HTTPException(400, "Token required")
    db.execute(
        "INSERT OR REPLACE INTO config (key, value, updated_at) VALUES ('github_token', ?, datetime('now'))",
        (token,),
    )
    return {"status": "ok"}


# ── Projects ──────────────────────────────────────────────────────────────────

@app.get("/projects")
def list_projects(db=Depends(get_db)):
    return [dict(r) for r in db.execute("SELECT * FROM user_projects ORDER BY name").fetchall()]


@app.post("/projects", status_code=201)
def create_project(body: dict, db=Depends(get_db)):
    name = body["name"].strip()
    local_path = body.get("local_path", "").strip()
    github_repo = body.get("github_repo", "").strip() or None

    if not local_path:
        local_path = str(Path(PROJECTS_BASE) / name.lower().replace(" ", "-"))

    # If GitHub repo given and local path doesn't exist, clone it
    if github_repo and not Path(local_path).exists():
        token_row = db.execute("SELECT value FROM config WHERE key='github_token'").fetchone()
        if token_row and token_row["value"]:
            url = f"https://{token_row['value']}@github.com/{github_repo}.git"
        else:
            url = f"https://github.com/{github_repo}.git"
        try:
            Path(local_path).parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "clone", url, local_path], check=True, timeout=60)
        except Exception as e:
            raise HTTPException(500, f"Clone failed: {e}")
    elif not Path(local_path).exists():
        Path(local_path).mkdir(parents=True, exist_ok=True)

    try:
        db.execute(
            "INSERT INTO user_projects (name, local_path, github_repo) VALUES (?,?,?)",
            (name, local_path, github_repo),
        )
    except Exception as e:
        raise HTTPException(400, str(e))
    return {"status": "ok"}


@app.delete("/projects/{project_id}")
def delete_project(project_id: int, db=Depends(get_db)):
    if not db.execute("SELECT 1 FROM user_projects WHERE id=?", (project_id,)).fetchone():
        raise HTTPException(404, "Project not found")
    db.execute("DELETE FROM user_projects WHERE id=?", (project_id,))
    return {"status": "ok"}


# ── File tree ─────────────────────────────────────────────────────────────────

_IGNORE = {".git", "node_modules", "__pycache__", "venv", ".venv", "dist", ".next", "target", ".mypy_cache"}


def _tree(root: Path, current: Path, depth: int = 0) -> dict:
    node: dict = {"name": current.name, "type": "directory", "children": []}
    if depth > 5:
        return node
    try:
        entries = sorted(current.iterdir(), key=lambda p: (p.is_file(), p.name))
        for e in entries:
            if e.name in _IGNORE or e.name.startswith("."):
                continue
            rel = str(e.relative_to(root))
            if e.is_dir():
                node["children"].append(_tree(root, e, depth + 1))
            else:
                node["children"].append({"name": e.name, "type": "file", "path": rel})
    except PermissionError:
        pass
    return node


@app.get("/projects/{project_id}/tree")
def file_tree(project_id: int, db=Depends(get_db)):
    row = db.execute("SELECT local_path FROM user_projects WHERE id=?", (project_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Project not found")
    root = Path(row["local_path"])
    if not root.exists():
        raise HTTPException(404, "Local path not found")
    return _tree(root, root)


# ── Git status ────────────────────────────────────────────────────────────────

@app.get("/projects/{project_id}/git-status")
def git_status(project_id: int, db=Depends(get_db)):
    row = db.execute("SELECT local_path FROM user_projects WHERE id=?", (project_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Project not found")
    path = row["local_path"]

    def run(*cmd):
        r = subprocess.run(cmd, cwd=path, capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else ""

    branch = run("git", "rev-parse", "--abbrev-ref", "HEAD")
    status_lines = run("git", "status", "--porcelain").splitlines()
    log_lines = run("git", "log", "--oneline", "-10").splitlines()

    staged = [l[3:] for l in status_lines if l and l[0] in "MADRC"]
    unstaged = [l[3:] for l in status_lines if l and l[1] in "MD?" and l[0] == " "]
    untracked = [l[3:] for l in status_lines if l.startswith("??")]

    return {
        "branch": branch or "unknown",
        "staged": staged,
        "unstaged": unstaged + untracked,
        "commits": log_lines,
    }


# ── Push ─────────────────────────────────────────────────────────────────────

@app.post("/projects/{project_id}/push")
def push(project_id: int, body: dict, db=Depends(get_db)):
    row = db.execute("SELECT local_path FROM user_projects WHERE id=?", (project_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Project not found")
    remote = body.get("remote", "origin")
    branch = body.get("branch", "main")
    try:
        r = subprocess.run(
            ["git", "push", remote, branch],
            cwd=row["local_path"], capture_output=True, text=True, timeout=60,
        )
        if r.returncode != 0:
            raise HTTPException(500, r.stderr.strip())
        return {"status": "ok", "output": r.stdout.strip()}
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Create PR ─────────────────────────────────────────────────────────────────

@app.post("/projects/{project_id}/create-pr")
def create_pr(project_id: int, body: dict, db=Depends(get_db)):
    row = db.execute("SELECT github_repo FROM user_projects WHERE id=?", (project_id,)).fetchone()
    if not row or not row["github_repo"]:
        raise HTTPException(400, "Project has no linked GitHub repo")
    token_row = db.execute("SELECT value FROM config WHERE key='github_token'").fetchone()
    if not token_row or not token_row["value"]:
        raise HTTPException(400, "GitHub token not configured")
    try:
        from tools.github_tool import GitHubTool
        t = GitHubTool()
        r = t.create_pr(
            repo=row["github_repo"],
            title=body["title"],
            body=body.get("body", ""),
            head_branch=body["head_branch"],
            base_branch=body.get("base_branch", "main"),
        )
        return {"status": "ok", "url": r.output, "pr_number": r.metadata.get("pr_number")}
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Agent chat ────────────────────────────────────────────────────────────────

@app.post("/chat")
async def chat(body: dict, db=Depends(get_db)):
    project_id = body.get("project_id")
    message = body.get("message", "").strip()
    history = body.get("history", [])
    model = body.get("model", "qwen2.5-coder:32b")

    if not message:
        raise HTTPException(400, "message required")

    project_path = None
    if project_id:
        row = db.execute("SELECT local_path FROM user_projects WHERE id=?", (project_id,)).fetchone()
        if row:
            project_path = row["local_path"]

    # Fall back to a simple chat if no project (no tool access)
    if not project_path:
        async def simple_stream():
            async with httpx.AsyncClient(timeout=120) as client:
                msgs = [{"role": "system", "content": "You are a helpful coding assistant."}]
                msgs.extend(history)
                msgs.append({"role": "user", "content": message})
                async with client.stream("POST", f"{OLLAMA_URL}/api/chat",
                    json={"model": model, "messages": msgs, "stream": True}) as r:
                    import json as _json
                    async for line in r.aiter_lines():
                        if not line:
                            continue
                        try:
                            chunk = _json.loads(line)
                            text = chunk.get("message", {}).get("content", "")
                            if text:
                                yield f"data: {_json.dumps({'type': 'text', 'text': text})}\n\n"
                        except Exception:
                            pass
            yield 'data: {"type": "done"}\n\n'

        return StreamingResponse(simple_stream(), media_type="text/event-stream")

    return StreamingResponse(
        run_agent(message, history, project_path, model),
        media_type="text/event-stream",
    )
