import json
import logging
from typing import AsyncGenerator

import httpx
from fastapi.responses import StreamingResponse

import db

logger = logging.getLogger(__name__)


async def _gemini_tokens(model: str, messages: list[dict], system: str | None, user_id: str) -> AsyncGenerator[str, None]:
    api_key = db.get_user_key(user_id, "gemini")
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


async def _openrouter_tokens(model: str, messages: list[dict], system: str | None, user_id: str, json_mode: bool = False) -> AsyncGenerator[str, None]:
    api_key = db.get_user_key(user_id, "openrouter")
    if not api_key:
        raise ValueError("OpenRouter API key not configured in Settings")

    msgs = ([{"role": "system", "content": system}] if system else []) + messages
    body: dict = {"model": model, "stream": True, "messages": msgs}
    # response_format is not supported by all OpenRouter models;
    # system prompts already instruct JSON output, so we omit it.

    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream(
            "POST",
            "https://openrouter.ai/api/v1/chat/completions",
            json=body,
            headers={"Authorization": f"Bearer {api_key}", "HTTP-Referer": "http://localhost:8011"},
        ) as r:
            if r.status_code >= 400:
                raw = await r.aread()
                try:
                    err_obj = json.loads(raw)
                    err_msg = (err_obj.get("error") or {}).get("message") or err_obj.get("message") or raw.decode()
                except Exception:
                    err_msg = raw.decode()
                raise ValueError(f"OpenRouter {r.status_code}: {err_msg}")
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


async def _anthropic_tokens(model: str, messages: list[dict], system: str | None, user_id: str) -> AsyncGenerator[str, None]:
    api_key = db.get_user_key(user_id, "anthropic")
    if not api_key:
        raise ValueError("Anthropic API key not configured in Settings")

    body: dict = {
        "model": model,
        "max_tokens": 8192,
        "stream": True,
        "messages": [m for m in messages if m["role"] != "system"],
    }
    if system:
        body["system"] = system

    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream(
            "POST",
            "https://api.anthropic.com/v1/messages",
            json=body,
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
        ) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line.startswith("data: "):
                    continue
                raw = line[6:].strip()
                try:
                    d = json.loads(raw)
                    if d.get("type") == "content_block_delta":
                        text = d.get("delta", {}).get("text", "")
                        if text:
                            yield text
                except Exception:
                    pass


async def _openai_tokens(model: str, messages: list[dict], system: str | None, user_id: str) -> AsyncGenerator[str, None]:
    api_key = db.get_user_key(user_id, "openai")
    if not api_key:
        raise ValueError("OpenAI API key not configured in Settings")

    msgs = ([{"role": "system", "content": system}] if system else []) + messages
    body = {"model": model, "stream": True, "messages": msgs}

    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream(
            "POST",
            "https://api.openai.com/v1/chat/completions",
            json=body,
            headers={"Authorization": f"Bearer {api_key}"},
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


async def _ollama_tokens(model: str, messages: list[dict], system: str | None, user_id: str, json_mode: bool = False) -> AsyncGenerator[str, None]:
    host = db.get_setting("ollama_host") or "http://localhost:11434"
    msgs = ([{"role": "system", "content": system}] if system else []) + messages

    body: dict = {"model": model, "stream": True, "messages": msgs, "options": {"num_ctx": 32768}}
    if json_mode:
        body["format"] = "json"
    async with httpx.AsyncClient(timeout=600) as client:
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


def provider_tokens(provider: str, model: str, messages: list[dict], system: str | None = None, user_id: str = "local", json_mode: bool = False) -> AsyncGenerator[str, None]:
    if provider == "gemini":
        return _gemini_tokens(model, messages, system, user_id)
    if provider == "openrouter":
        return _openrouter_tokens(model, messages, system, user_id, json_mode=json_mode)
    if provider == "anthropic":
        return _anthropic_tokens(model, messages, system, user_id)
    if provider == "openai":
        return _openai_tokens(model, messages, system, user_id)
    if provider == "ollama":
        return _ollama_tokens(model, messages, system, user_id, json_mode=json_mode)
    raise ValueError(f"Unknown provider: {provider}")


def stream_chat(agent_key: str, messages: list[dict], system: str | None = None, user_id: str = "local") -> StreamingResponse:
    async def generate():
        provider = db.get_setting(f"agent_{agent_key}_provider")
        model = db.get_setting(f"agent_{agent_key}_model")

        if not provider or not model:
            msg = f"Agent \"{agent_key}\" has no model assigned. Go to Settings."
            yield f'data: {json.dumps({"type": "error", "message": msg})}\n\n'
            return
        try:
            async for token in provider_tokens(provider, model, messages, system, user_id):
                yield f'data: {json.dumps({"type": "token", "content": token})}\n\n'
            yield f'data: {json.dumps({"type": "done"})}\n\n'
        except Exception as e:
            msg = str(e) or f"{type(e).__name__}"
            logger.error("LLM stream error: %s", msg)
            yield f'data: {json.dumps({"type": "error", "message": msg})}\n\n'

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def call_llm(agent_key: str, messages: list[dict], system: str | None = None, user_id: str = "local") -> str:
    provider = db.get_setting(f"agent_{agent_key}_provider")
    model = db.get_setting(f"agent_{agent_key}_model")

    if not provider or not model:
        raise ValueError(f'Agent "{agent_key}" has no model assigned')

    result = ""
    async for token in provider_tokens(provider, model, messages, system, user_id):
        result += token
    return result
