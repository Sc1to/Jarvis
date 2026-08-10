import json
import logging
import os
import sys
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from health import health_payload

START_TIME = time.time()
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("DEFAULT_MODEL", "qwen2.5:72b-instruct-q4_K_M")


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
def health():
    return health_payload(START_TIME, "1.0.0")


@app.get("/models")
async def list_models():
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{OLLAMA_URL}/api/tags")
            return r.json()
    except Exception:
        return {"models": []}


# ── Streaming helper ──────────────────────────────────────────────────────────

def _sse_stream(messages: list[dict], model: str) -> StreamingResponse:
    async def generate():
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                async with client.stream("POST", f"{OLLAMA_URL}/api/chat", json={
                    "model": model,
                    "messages": messages,
                    "stream": True,
                }) as resp:
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            chunk = data.get("message", {}).get("content", "")
                            if chunk:
                                yield f"data: {json.dumps({'text': chunk})}\n\n"
                            if data.get("done"):
                                yield "data: [DONE]\n\n"
                        except Exception:
                            continue
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/write")
async def write(body: dict):
    prompt = body.get("prompt", "")
    context = body.get("context", "")
    model = body.get("model", DEFAULT_MODEL)
    document_so_far = body.get("document_so_far", "")

    user_content = prompt
    if document_so_far:
        user_content = f"Existing document:\n{document_so_far}\n\nTask:\n{prompt}"
    if context:
        user_content = f"Context: {context}\n\n{user_content}"

    return _sse_stream([
        {"role": "system", "content": "You are a writing assistant. Write clear, engaging prose that matches the style and tone of any existing document provided. Return only the written text — no preamble."},
        {"role": "user", "content": user_content},
    ], model)


@app.post("/continue")
async def continue_writing(body: dict):
    document = body.get("document_so_far", "")
    model = body.get("model", DEFAULT_MODEL)

    return _sse_stream([
        {"role": "system", "content": "You are a writing assistant. Continue the provided document naturally, matching its style, voice, and tone exactly. Do not repeat what has already been written. Write only the continuation — no preamble."},
        {"role": "user", "content": f"Continue this:\n\n{document}"},
    ], model)


@app.post("/edit")
async def edit_selection(body: dict):
    selection = body.get("selection", "")
    instruction = body.get("instruction", "")
    full_document = body.get("full_document", "")
    model = body.get("model", DEFAULT_MODEL)

    context = f"Full document for context (do not reproduce it):\n{full_document[:2000]}\n\n" if full_document else ""

    return _sse_stream([
        {"role": "system", "content": "You are a writing editor. Edit the provided text according to the instruction. Return only the edited text — no preamble, no explanation, no surrounding quotes."},
        {"role": "user", "content": f"{context}Text to edit:\n{selection}\n\nInstruction: {instruction}"},
    ], model)


@app.post("/suggest")
async def suggest(body: dict):
    document = body.get("document_so_far", "")
    model = body.get("model", DEFAULT_MODEL)

    if not document.strip():
        return {"suggestions": []}

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(f"{OLLAMA_URL}/api/chat", json={
                "model": model,
                "messages": [
                    {"role": "system", "content": 'You are a writing coach. Give 3-5 short, actionable improvement suggestions for the document. Return ONLY a JSON array of strings, nothing else: ["suggestion 1", "suggestion 2", ...]'},
                    {"role": "user", "content": f"Suggest improvements for:\n\n{document[:3000]}"},
                ],
                "stream": False,
            })
            text = r.json().get("message", {}).get("content", "[]")
            if "[" in text:
                text = text[text.index("["):text.rindex("]") + 1]
            suggestions = json.loads(text)
            return {"suggestions": suggestions if isinstance(suggestions, list) else []}
    except Exception as e:
        logger.error(f"suggest failed: {e}")
        return {"suggestions": [], "error": str(e)}
