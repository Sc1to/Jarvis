import logging
import os
import sys
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from health import health_payload

import db
import prompt_store
from routes.phase1 import (STORY_ARCHITECT_SYSTEM, SYNTHESIS_PROMPT, BIBLE_AGENT_SYSTEM,
                             TIER_INSTRUCTIONS, TIER_LABELS)
from routes.phase2 import CONSOLIDATOR_SYSTEM, RESEARCH_SYSTEM
from routes.phase3 import SCENE_PLANNER_SYSTEM, WRITER_SYSTEM, QA_SYSTEM, BIBLE_UPDATER_SYSTEM
from routes.settings import router as settings_router
from routes.books import router as books_router
from routes.models import router as models_router
from routes.bible import router as bible_router
from routes.git import router as git_router
from routes.phase1 import router as phase1_router
from routes.phase2 import router as phase2_router
from routes.phase3 import router as phase3_router

logging.basicConfig(level=logging.INFO)
VERSION = "1.0.0"
_start = time.time()

app = FastAPI(title="Writer")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

db._get_conn()  # initialize DB on startup

app.include_router(settings_router, prefix="/api")
app.include_router(books_router, prefix="/api")
app.include_router(models_router, prefix="/api")
app.include_router(bible_router, prefix="/api")
app.include_router(git_router, prefix="/api")
app.include_router(phase1_router, prefix="/api")
app.include_router(phase2_router, prefix="/api")
app.include_router(phase3_router, prefix="/api")


_WRITER_DEFAULTS = {
    "story_architect": STORY_ARCHITECT_SYSTEM,
    "synthesis": SYNTHESIS_PROMPT,
    "bible_agent": BIBLE_AGENT_SYSTEM,
    **{f"tier_{label.lower()}": TIER_INSTRUCTIONS[i] for i, label in enumerate(TIER_LABELS)},
    "consolidator": CONSOLIDATOR_SYSTEM,
    "research": RESEARCH_SYSTEM,
    "scene_planner": SCENE_PLANNER_SYSTEM,
    "writer": WRITER_SYSTEM,
    "qa": QA_SYSTEM,
    "bible_updater": BIBLE_UPDATER_SYSTEM,
}


@app.get("/prompts")
def get_prompts():
    return prompt_store.all_effective(_WRITER_DEFAULTS)


@app.patch("/prompts/{key}")
def set_prompt(key: str, body: dict):
    if key not in _WRITER_DEFAULTS:
        from fastapi import HTTPException
        raise HTTPException(404, f"Unknown prompt key: {key}")
    prompt_store.set_(key, body["system_prompt"])
    return {"status": "ok"}


@app.get("/health")
def health():
    return health_payload(_start, VERSION)
