"""Bookforge service shell (Phase 14, milestone 14.0).

Only the platform plumbing exists so far: health check, response envelope and
error handling. The pipeline itself arrives in milestones 14.1 onward.
"""

import logging
import os
import sys
import time

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from health import health_payload  # noqa: E402

from bookforge import __version__  # noqa: E402

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("platform_bookforge")

VERSION = __version__
MILESTONE = "14.0"
DATA_DIR = os.environ.get("BOOKFORGE_DATA_DIR", "/opt/platform/data/bookforge")
_start = time.time()

app = FastAPI(title="Bookforge")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _error(status_code: int, error: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": error, "status": "error", "detail": detail})


@app.exception_handler(StarletteHTTPException)
async def _http_error(_: Request, exc: StarletteHTTPException):
    return _error(exc.status_code, "http_error", str(exc.detail))


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, exc: RequestValidationError):
    return _error(422, "validation_error", str(exc.errors()))


@app.exception_handler(Exception)
async def _unhandled_error(_: Request, exc: Exception):
    log.exception("Unhandled error")
    return _error(500, "internal_error", str(exc))


@app.get("/health")
def health():
    return health_payload(_start, VERSION)


@app.get("/api/status")
def status():
    try:
        return {
            "data": {
                "service": "platform-bookforge",
                "version": VERSION,
                "milestone": MILESTONE,
                "data_dir": DATA_DIR,
                "data_dir_exists": os.path.isdir(DATA_DIR),
            },
            "status": "ok",
        }
    except Exception as e:  # defensive: endpoints never return a raw 500
        log.exception("status failed")
        return _error(500, "status_failed", str(e))
