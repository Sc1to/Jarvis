import json
import logging
import os
import sys
import time

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from health import health_payload

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
DEFAULT_MODEL = "qwen2.5:14b"
VERSION = "0.1.0"
_start = time.time()

_CHAT_DEFAULT = ""  # chat has no system prompt by default
_overrides: dict[str, str] = {}

app = FastAPI(title="Chat")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    model: str = DEFAULT_MODEL
    history: list[dict] = []


@app.get("/prompts")
def get_prompts():
    return {"chat_assistant": _overrides.get("chat_assistant", _CHAT_DEFAULT)}


@app.patch("/prompts/{key}")
def set_prompt(key: str, body: dict):
    _overrides[key] = body["system_prompt"]
    return {"status": "ok"}


@app.get("/health")
async def health():
    return health_payload(_start, VERSION)


@app.get("/models")
async def models():
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{OLLAMA_URL}/api/tags")
            r.raise_for_status()
            return {"data": r.json(), "status": "ok"}
    except Exception as e:
        logger.error("Ollama unreachable: %s", e)
        return {"error": str(e), "status": "error", "detail": "Ollama unavailable"}


@app.post("/chat")
async def chat(req: ChatRequest):
    system = _overrides.get("chat_assistant", _CHAT_DEFAULT)
    messages = ([{"role": "system", "content": system}] if system else []) + req.history + [{"role": "user", "content": req.message}]

    async def stream():
        try:
            async with httpx.AsyncClient(timeout=120) as c:
                async with c.stream(
                    "POST",
                    f"{OLLAMA_URL}/api/chat",
                    json={"model": req.model, "messages": messages, "stream": True},
                ) as r:
                    async for line in r.aiter_lines():
                        if line:
                            yield f"data: {line}\n\n"
        except httpx.ConnectError:
            err = json.dumps({"error": "Ollama is not running — check: systemctl status ollama"})
            yield f"data: {err}\n\n"
        except Exception as e:
            logger.error("Stream error: %s", e)
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")
