import asyncio
import json
import os
import time
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI()
_start = time.time()
DELAY = int(os.getenv("MOCK_DELAY_MS", "50")) / 1000.0

MODELS = [
    {"name": "qwen2.5:14b", "size": 9000000000},
    {"name": "qwen2.5-coder:32b", "size": 20000000000},
    {"name": "qwen2.5:72b-instruct-q4_K_M", "size": 44000000000},
]


def _log(endpoint: str, model: str = "", prompt: str = "") -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    prompt_preview = repr(prompt[:100].replace("\n", " ")) if prompt else ""
    print(f"[{ts}] {endpoint:<30} model={model:<30} prompt={prompt_preview}", flush=True)


def _last_user_msg(messages: list) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            c = msg.get("content", "")
            return (c if isinstance(c, str) else str(c))[:100]
    return ""


def _mock_content(model: str, prompt: str) -> str:
    return (
        f"MOCK RESPONSE [{model}]: This is a placeholder response from the mock LLM service. "
        f"Real model will be connected when testing is complete. "
        f"Input received: {prompt[:100]}"
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/api/tags")
async def api_tags():
    _log("GET /api/tags")
    return {"models": MODELS}


@app.get("/api/ps")
async def api_ps():
    _log("GET /api/ps")
    return {"models": [MODELS[0]]}


@app.post("/api/chat")
async def api_chat(request: Request):
    body = await request.json()
    model = body.get("model", "unknown")
    messages = body.get("messages", [])
    stream = body.get("stream", False)
    prompt = _last_user_msg(messages)
    _log("POST /api/chat", model, prompt)

    content = _mock_content(model, prompt)

    if not stream:
        return {"message": {"role": "assistant", "content": content}, "done": True}

    async def ndjson_stream():
        for word in content.split():
            yield json.dumps({"message": {"role": "assistant", "content": word + " "}, "done": False}) + "\n"
            await asyncio.sleep(DELAY)
        yield json.dumps({"message": {"role": "assistant", "content": ""}, "done": True}) + "\n"

    return StreamingResponse(ndjson_stream(), media_type="application/x-ndjson")


@app.post("/api/pull")
async def api_pull(request: Request):
    body = await request.json()
    model = body.get("name", "unknown")
    _log("POST /api/pull", model)

    async def pull_stream():
        steps = [
            ("pulling manifest", 0),
            ("pulling layers", 33),
            ("verifying sha256 digest", 66),
            ("writing manifest", 90),
            ("success", 100),
        ]
        for status, pct in steps:
            yield json.dumps({"status": status, "completed": pct, "total": 100}) + "\n"
            await asyncio.sleep(0.6)

    return StreamingResponse(pull_stream(), media_type="application/x-ndjson")


@app.delete("/api/delete")
async def api_delete(request: Request):
    body = await request.json()
    _log("DELETE /api/delete", body.get("name", ""))
    return JSONResponse(status_code=200, content={})


@app.post("/v1/chat/completions")
async def openai_chat(request: Request):
    body = await request.json()
    model = body.get("model", "unknown")
    messages = body.get("messages", [])
    stream = body.get("stream", False)
    prompt = _last_user_msg(messages)
    _log("POST /v1/chat/completions", model, prompt)

    content = _mock_content(model, prompt)

    if not stream:
        return {
            "id": "mock-1",
            "object": "chat.completion",
            "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        }

    async def sse_stream():
        for word in content.split():
            chunk = {
                "id": "mock-1",
                "object": "chat.completion.chunk",
                "model": model,
                "choices": [{"index": 0, "delta": {"content": word + " "}, "finish_reason": None}],
            }
            yield f"data: {json.dumps(chunk)}\n\n"
            await asyncio.sleep(DELAY)
        yield "data: [DONE]\n\n"

    return StreamingResponse(sse_stream(), media_type="text/event-stream")


@app.get("/health")
async def health():
    return {"status": "ok", "version": "mock-1.0", "uptime_seconds": int(time.time() - _start)}


# ── Startup banner ─────────────────────────────────────────────────────────────
print("=" * 60, flush=True)
print("MOCK OLLAMA RUNNING — not a real LLM", flush=True)
print(f"  Port  : 11434", flush=True)
print(f"  Delay : {int(DELAY * 1000)}ms between stream words", flush=True)
print(f"  Models: {', '.join(m['name'] for m in MODELS)}", flush=True)
print("=" * 60, flush=True)
