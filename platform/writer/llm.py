import json
import logging
from typing import AsyncGenerator

import httpx
from fastapi.responses import StreamingResponse

import db

logger = logging.getLogger(__name__)


async def _gemini_tokens(model: str, messages: list[dict], system: str | None) -> AsyncGenerator[str, None]:
    api_key = db.get_setting("gemini_api_key")
    if not api_key:
        raise ValueError("Gemini API key not configured in Settings")

    contents = [
        {"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
        for m in messages if m["role"] != "system"
    ]
    body: dict = {"contents": contents}
    if system:
        body["system_instruction"] = {"parts": [{"text": system}]}

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?alt=sse&key={api_key}"
    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream("POST", url, json=body) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line.startswith("data: "):
                    continue
                raw = line[6:].strip()
                if raw == "[DONE]":
                    return
                try:
                    d = json.loads(raw)
                    text = d.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                    if text:
                        yield text
                except Exception:
                    pass


async def _openrouter_tokens(model: str, messages: list[dict], system: str | None) -> AsyncGenerator[str, None]:
    api_key = db.get_setting("openrouter_api_key")
    if not api_key:
        raise ValueError("OpenRouter API key not configured in Settings")

    msgs = ([{"role": "system", "content": system}] if system else []) + messages
    body = {"model": model, "stream": True, "messages": msgs}

    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream(
            "POST",
            "https://openrouter.ai/api/v1/chat/completions",
            json=body,
            headers={"Authorization": f"Bearer {api_key}", "HTTP-Referer": "http://localhost:8011"},
        ) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line.startswith("data: "):
                    continue
                raw = line[6:].strip()
                if raw == "[DONE]":
                    return
                try:
                    d = json.loads(raw)
                    text = d.get("choices", [{}])[0].get("delta", {}).get("content", "")
                    if text:
                        yield text
                except Exception:
                    pass


async def _ollama_tokens(model: str, messages: list[dict], system: str | None) -> AsyncGenerator[str, None]:
    host = db.get_setting("ollama_host") or "http://localhost:11434"
    msgs = ([{"role": "system", "content": system}] if system else []) + messages
    body = {"model": model, "stream": True, "messages": msgs}

    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream("POST", f"{host}/api/chat", json=body) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line.strip():
                    continue
                try:
                    d = json.loads(line)
                    text = d.get("message", {}).get("content", "")
                    if text:
                        yield text
                except Exception:
                    pass


def _provider_tokens(provider: str, model: str, messages: list[dict], system: str | None) -> AsyncGenerator[str, None]:
    if provider == "gemini":
        return _gemini_tokens(model, messages, system)
    if provider == "openrouter":
        return _openrouter_tokens(model, messages, system)
    if provider == "ollama":
        return _ollama_tokens(model, messages, system)
    raise ValueError(f"Unknown provider: {provider}")


def stream_chat(agent_key: str, messages: list[dict], system: str | None = None) -> StreamingResponse:
    async def generate():
        provider = db.get_setting(f"agent_{agent_key}_provider")
        model = db.get_setting(f"agent_{agent_key}_model")

        if not provider or not model:
            yield f'data: {json.dumps({"type": "error", "message": f"Agent \"{agent_key}\" has no model assigned. Go to Settings."})}\n\n'
            return
        try:
            async for token in _provider_tokens(provider, model, messages, system):
                yield f'data: {json.dumps({"type": "token", "content": token})}\n\n'
            yield f'data: {json.dumps({"type": "done"})}\n\n'
        except Exception as e:
            logger.error("LLM stream error: %s", e)
            yield f'data: {json.dumps({"type": "error", "message": str(e)})}\n\n'

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def call_llm(agent_key: str, messages: list[dict], system: str | None = None) -> str:
    provider = db.get_setting(f"agent_{agent_key}_provider")
    model = db.get_setting(f"agent_{agent_key}_model")

    if not provider or not model:
        raise ValueError(f'Agent "{agent_key}" has no model assigned')

    result = ""
    async for token in _provider_tokens(provider, model, messages, system):
        result += token
    return result
