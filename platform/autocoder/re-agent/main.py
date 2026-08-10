"""
RE-agent: Requirements Elicitation agent.
Conversational agent that produces a structured requirements document.
Not a task-based agent — runs as a dialogue until requirements are finalised.
"""

import json
import logging
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from memory.session import SessionMemory
from memory.project import ProjectMemory
from memory.crossrun import CrossRunMemory
from memory.db import DB_PATH as _DEFAULT_DB_PATH

START_TIME = time.time()
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

DB_PATH = os.environ.get("DB_PATH", _DEFAULT_DB_PATH)
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL = os.environ.get("MODEL_RE_AGENT", "qwen2.5:14b")

session_mem = SessionMemory(db_path=DB_PATH)
project_mem = ProjectMemory(db_path=DB_PATH)
cross_mem = CrossRunMemory()

SYSTEM_PROMPT = """You are a requirements analyst. Your job is to fully understand what the user wants to build before handing off to a development pipeline.

Your conversation should:
1. Understand the core problem being solved
2. Define scope clearly — what is included and what is not
3. Surface and resolve ambiguities — never let the user be vague if it matters
4. Define acceptance criteria — how will we know it is done
5. Understand technical constraints — existing codebase, preferred stack, integrations needed
6. Read back your understanding and get explicit confirmation before finalising

You are the quality gate. The pipeline cannot start until you are satisfied the requirements are complete enough for autonomous execution. Be thorough. Ask uncomfortable questions. A missed requirement discovered overnight costs hours.

After each exchange, update the requirements document. When all sections are complete and the user has confirmed, signal completion.

Current requirements document state: {requirements_state}

User preferences from past sessions: {preferences}"""

_EMPTY_REQUIREMENTS = {
    "objective": "",
    "scope": {"included": [], "excluded": []},
    "constraints": [],
    "acceptance_criteria": [],
    "tech_context": "",
    "open_questions": [],
}

# In-memory sessions: session_id → {messages, requirements, confirmed}
_sessions: dict[str, dict] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
def health():
    return {"status": "ok", "version": "1.0.0", "uptime_seconds": int(time.time() - START_TIME)}


@app.post("/session/start")
async def start_session(body: dict):
    project_id = body.get("project_id")
    session_id = str(uuid.uuid4())

    # Load project context if available
    project_context = ""
    if project_id:
        p = project_mem.get_project(project_id)
        if p:
            decisions = project_mem.get_decisions(project_id)
            issues = project_mem.get_open_issues(project_id)
            project_context = f"\nProject: {p.name}\nDescription: {p.description}\n"
            if decisions:
                project_context += f"Past decisions: {', '.join(d.content for d in decisions[:5])}\n"
            if issues:
                project_context += f"Open issues: {', '.join(i.description for i in issues[:5])}\n"

    # Load cross-run preferences
    preferences = ""
    if cross_mem.available:
        prefs = cross_mem.query_preferences("coding style preferences", n_results=3)
        if prefs:
            preferences = "\n".join(p.content for p in prefs)

    _sessions[session_id] = {
        "project_id": project_id,
        "requirements": dict(_EMPTY_REQUIREMENTS),
        "confirmed": False,
        "messages": [],
        "project_context": project_context,
        "preferences": preferences,
    }

    greeting = await _chat(session_id, None)  # Initial greeting (no user message)
    return {"data": {"session_id": session_id, "message": greeting}, "status": "ok"}


@app.post("/session/{session_id}/message")
async def send_message(session_id: str, body: dict):
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    user_message = body.get("message", "").strip()
    if not user_message:
        raise HTTPException(status_code=400, detail="message is required")

    response = await _chat(session_id, user_message)
    sess = _sessions[session_id]

    is_complete = _check_complete(sess["requirements"])
    return {
        "data": {
            "response": response,
            "is_complete": is_complete,
            "requirements_document": sess["requirements"] if is_complete else None,
        },
        "status": "ok",
    }


@app.get("/session/{session_id}/requirements")
def get_requirements(session_id: str):
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"data": _sessions[session_id]["requirements"], "status": "ok"}


@app.post("/session/{session_id}/finalise")
def finalise_session(session_id: str):
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    sess = _sessions[session_id]
    sess["confirmed"] = True
    return {"data": {"requirements_document": sess["requirements"]}, "status": "ok"}


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _chat(session_id: str, user_message: str | None) -> str:
    sess = _sessions[session_id]
    messages = sess["messages"]

    if user_message:
        messages.append({"role": "user", "content": user_message})

    system = SYSTEM_PROMPT.format(
        requirements_state=json.dumps(sess["requirements"], indent=2),
        preferences=sess["preferences"] or "None recorded yet",
    )
    if sess["project_context"]:
        system += f"\n\n{sess['project_context']}"

    full_messages = [{"role": "system", "content": system}]
    if not messages:
        # Initial turn — prompt the model to greet
        full_messages.append({
            "role": "user",
            "content": "Please greet the user and ask them what they want to build. Be warm and direct.",
        })
    else:
        full_messages.extend(messages)

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{OLLAMA_URL}/api/chat",
                json={"model": MODEL, "messages": full_messages, "stream": False},
            )
            response_text = resp.json().get("message", {}).get("content", "")
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        response_text = "I'm having trouble connecting to the model right now. Please try again."

    messages.append({"role": "assistant", "content": response_text})

    # Try to extract requirements update from response
    _update_requirements(sess, response_text)

    return response_text


def _update_requirements(sess: dict, response_text: str) -> None:
    """Heuristically extract requirements from the assistant's response."""
    # If the model embedded JSON, parse it
    if "```json" in response_text:
        try:
            block = response_text.split("```json")[1].split("```")[0]
            data = json.loads(block)
            if isinstance(data, dict):
                req = sess["requirements"]
                for key in ("objective", "tech_context"):
                    if key in data and data[key]:
                        req[key] = data[key]
                for key in ("constraints", "acceptance_criteria", "open_questions"):
                    if key in data and isinstance(data[key], list):
                        req[key] = data[key]
                if "scope" in data and isinstance(data["scope"], dict):
                    req["scope"].update(data["scope"])
        except Exception:
            pass


def _check_complete(requirements: dict) -> bool:
    r = requirements
    return (
        bool(r.get("objective"))
        and bool(r.get("tech_context"))
        and bool(r.get("acceptance_criteria"))
        and bool(r.get("constraints"))
        and not r.get("open_questions")
    )
