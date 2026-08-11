import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from collections import defaultdict
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from memory.session import SessionMemory
from memory.project import ProjectMemory
from memory.db import connect, DB_PATH as _DEFAULT_DB_PATH
from health import health_payload

START_TIME = time.time()
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

DB_PATH = os.environ.get("DB_PATH", _DEFAULT_DB_PATH)
PROJECTS_PATH = os.environ.get("PROJECTS_PATH", "/opt/platform/data/projects")
CONDUCTOR_URL = os.environ.get("CONDUCTOR_URL", "http://localhost:8001")

session_mem = SessionMemory(db_path=DB_PATH)
project_mem = ProjectMemory(db_path=DB_PATH)

# session_id → list of active WebSocket connections
_ws_clients: dict[str, list[WebSocket]] = defaultdict(list)

# agent_name → {status, current_task, last_active}
_agent_status: dict[str, dict] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
def health():
    return health_payload(START_TIME, "1.0.0")


# ── Sessions ──────────────────────────────────────────────────────────────────

@app.get("/sessions")
def list_sessions():
    sessions = session_mem.list_sessions(limit=50)
    return {"data": [_session_dict(s) for s in sessions], "status": "ok"}


@app.get("/sessions/{session_id}")
def get_session(session_id: str):
    s = session_mem.get_session(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"data": _session_dict(s), "status": "ok"}


@app.get("/sessions/{session_id}/log")
def get_session_log(session_id: str):
    events = session_mem.get_session_log(session_id)
    return {"data": [_event_dict(e) for e in events], "status": "ok"}


@app.get("/sessions/{session_id}/internet")
def get_session_internet(session_id: str):
    import sqlite3
    with connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM internet_log WHERE session_id=? ORDER BY timestamp",
            (session_id,),
        ).fetchall()
    return {"data": [dict(r) for r in rows], "status": "ok"}


@app.get("/sessions/{session_id}/internet/{entry_id}")
def get_internet_entry(session_id: str, entry_id: int):
    import sqlite3
    with connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM internet_log WHERE id=? AND session_id=?",
            (entry_id, session_id),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Entry not found")
    return {"data": dict(row), "status": "ok"}


# ── Ollama models ─────────────────────────────────────────────────────────────

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")

@app.get("/ollama/models")
async def list_ollama_models():
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{OLLAMA_URL}/api/tags")
            data = resp.json()
            names = [m["name"] for m in data.get("models", [])]
            return {"data": names, "status": "ok"}
    except Exception as e:
        return {"data": [], "status": "error", "detail": str(e)}


# ── Projects ──────────────────────────────────────────────────────────────────

@app.get("/projects")
def list_projects():
    projects = project_mem.list_projects()
    return {"data": [_project_dict(p) for p in projects], "status": "ok"}


@app.post("/projects")
def create_project(body: dict):
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    description = (body.get("description") or "").strip()
    project_id = project_mem.create_project(name, description)
    p = project_mem.get_project(project_id)
    return {"data": _project_dict(p), "status": "ok"}


@app.get("/projects/{project_id}")
def get_project(project_id: int):
    p = project_mem.get_project(project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    decisions = project_mem.get_decisions(project_id)
    issues = project_mem.get_open_issues(project_id)
    return {
        "data": {
            **_project_dict(p),
            "decisions": [_decision_dict(d) for d in decisions],
            "open_issues": [_issue_dict(i) for i in issues],
        },
        "status": "ok",
    }


@app.get("/projects/{project_id}/sessions")
def get_project_sessions(project_id: int):
    sessions = session_mem.list_sessions(project_id=project_id, limit=20)
    return {"data": [_session_dict(s) for s in sessions], "status": "ok"}


@app.post("/projects/{project_id}/export")
def export_project(project_id: int, body: dict):
    dest = (body.get("dest_path") or "").strip()
    if not dest:
        raise HTTPException(status_code=400, detail="dest_path is required")
    p = project_mem.get_project(project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    src = os.path.join(PROJECTS_PATH, p.name)
    if not os.path.isdir(src):
        raise HTTPException(status_code=404, detail="Project directory not found on disk")
    try:
        shutil.copytree(src, dest)
        return {"data": {"dest_path": dest}, "status": "ok"}
    except FileExistsError:
        raise HTTPException(status_code=409, detail=f"Destination already exists: {dest}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Agent status ──────────────────────────────────────────────────────────────

@app.get("/agents/status")
def get_agents_status():
    names = ["conductor", "re-agent", "backend", "frontend", "db", "tester", "refactorer"]
    result = []
    for name in names:
        info = _agent_status.get(name, {})
        result.append({
            "agent_name": name,
            "status": info.get("status", "idle"),
            "current_task": info.get("current_task"),
            "last_active": info.get("last_active"),
        })
    return {"data": result, "status": "ok"}


# ── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/ws/session/{session_id}")
async def ws_session(websocket: WebSocket, session_id: str):
    await websocket.accept()
    _ws_clients[session_id].append(websocket)
    try:
        while True:
            await websocket.receive_text()  # keeps the connection alive
    except WebSocketDisconnect:
        _ws_clients[session_id].remove(websocket)


# ── Internal event relay (Conductor POSTs here) ───────────────────────────────

@app.post("/internal/event")
async def receive_event(payload: dict):
    import datetime
    session_id = payload.get("session_id")
    agent = payload.get("agent")
    status = payload.get("status")
    current_task = payload.get("current_task")

    if agent:
        _agent_status[agent] = {
            "status": status or "active",
            "current_task": current_task,
            "last_active": datetime.datetime.utcnow().isoformat(),
        }

    if session_id:
        dead = []
        for ws in list(_ws_clients.get(session_id, [])):
            try:
                await ws.send_text(json.dumps(payload))
            except Exception:
                dead.append(ws)
        for ws in dead:
            _ws_clients[session_id].remove(ws)

    return {"status": "ok"}


# ── Session start (proxies to Conductor) ──────────────────────────────────────

@app.post("/session/start")
async def start_session(body: dict):
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{CONDUCTOR_URL}/session/start", json=body)
            return resp.json()
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="Conductor service unavailable")


# ── Git ───────────────────────────────────────────────────────────────────────

@app.get("/projects/{project_id}/commits")
def get_project_commits(project_id: int):
    p = project_mem.get_project(project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    repo_path = os.path.join(PROJECTS_PATH, p.name)
    if not os.path.isdir(os.path.join(repo_path, ".git")):
        return {"data": [], "status": "ok"}
    result = subprocess.run(
        ["git", "log", "--pretty=format:%H|%s|%ai|%an", "-20"],
        cwd=repo_path, capture_output=True, text=True,
    )
    commits = []
    for line in result.stdout.strip().splitlines():
        parts = line.split("|", 3)
        if len(parts) >= 2:
            commits.append({
                "hash": parts[0],
                "message": parts[1],
                "timestamp": parts[2] if len(parts) > 2 else "",
                "author": parts[3] if len(parts) > 3 else "",
            })
    return {"data": commits, "status": "ok"}


@app.get("/projects/{project_id}/commits/{commit_hash}/diff")
def get_commit_diff(project_id: int, commit_hash: str):
    p = project_mem.get_project(project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    repo_path = os.path.join(PROJECTS_PATH, p.name)
    result = subprocess.run(
        ["git", "show", "--stat", commit_hash],
        cwd=repo_path, capture_output=True, text=True,
    )
    return {"data": {"diff": result.stdout[:20000]}, "status": "ok"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _session_dict(s):
    return {
        "id": s.id, "project_id": s.project_id, "description": s.description,
        "status": s.status, "outcome": s.outcome,
        "started_at": s.started_at, "closed_at": s.closed_at,
    }


def _event_dict(e):
    return {
        "id": e.id, "session_id": e.session_id, "agent": e.agent,
        "event_type": e.event_type, "content": e.content,
        "metadata": e.metadata, "timestamp": e.timestamp,
    }


def _project_dict(p):
    return {"id": p.id, "name": p.name, "description": p.description, "created_at": p.created_at}


def _decision_dict(d):
    return {
        "id": d.id, "decision_type": d.decision_type,
        "content": d.content, "rationale": d.rationale, "created_at": d.created_at,
    }


def _issue_dict(i):
    return {
        "id": i.id, "description": i.description, "status": i.status,
        "resolution": i.resolution, "created_at": i.created_at,
    }
