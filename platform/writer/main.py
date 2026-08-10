import logging
import os
import sys
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from health import health_payload

import db
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


@app.get("/health")
def health():
    return health_payload(_start, VERSION)
