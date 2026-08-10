import asyncio
import logging
import os
import sys
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from memory.session import SessionMemory
from memory.project import ProjectMemory
from memory.db import DB_PATH as _DEFAULT_DB_PATH
from health import health_payload
from pipeline import start_pipeline, pause_pipeline, resume_pipeline

START_TIME = time.time()
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

DB_PATH = os.environ.get("DB_PATH", _DEFAULT_DB_PATH)
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "http://localhost:8050")

session_mem = SessionMemory(db_path=DB_PATH)
project_mem = ProjectMemory(db_path=DB_PATH)


def _recover_sessions():
    sessions = session_mem.list_sessions(limit=100)
    for s in sessions:
        if s.status == "running":
            try:
                session_mem.log_event(s.id, "conductor", "parked",
                    content="Conductor restarted — session parked automatically")
                session_mem.close_session(s.id, "parked")
                logger.info("Parked interrupted session %s", s.id)
            except Exception as e:
                logger.error("Failed to park session %s: %s", s.id, e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _recover_sessions()
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
def health():
    return health_payload(START_TIME, "1.0.0")


@app.post("/session/start")
async def start_session(body: dict):
    project_id = body.get("project_id")
    requirements = body.get("requirements_document", "").strip()

    if not requirements:
        raise HTTPException(status_code=400, detail="requirements_document is required")

    session_id = session_mem.create_session(
        project_id=project_id,
        description=f"Autocoder: {requirements[:80]}",
    )

    asyncio.create_task(start_pipeline(
        session_id=session_id,
        project_id=project_id,
        requirements=requirements,
        session_mem=session_mem,
        project_mem=project_mem,
        dashboard_url=DASHBOARD_URL,
    ))

    logger.info(f"Started session {session_id}")
    return {"data": {"session_id": session_id}, "status": "ok"}


@app.get("/session/{session_id}/status")
def get_session_status(session_id: str):
    s = session_mem.get_session(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"data": {"session_id": session_id, "status": s.status, "outcome": s.outcome}, "status": "ok"}


@app.post("/session/{session_id}/pause")
def pause_session(session_id: str):
    pause_pipeline(session_id)
    return {"status": "ok", "data": {"session_id": session_id, "paused": True}}


@app.post("/session/{session_id}/resume")
def resume_session(session_id: str):
    resume_pipeline(session_id)
    return {"status": "ok", "data": {"session_id": session_id, "paused": False}}
