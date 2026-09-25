import json
import logging
from typing import AsyncGenerator

import httpx

import db

logger = logging.getLogger(__name__)


async def _gemini_tokens(model: str, messages: list[dict], system: str | None, user_id: str, usage: dict | None = None) -> AsyncGenerator[str, None]:
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
                    meta = d.get("usageMetadata")
                    if usage is not None and meta:
                        usage["input_tokens"] = meta.get("promptTokenCount")
                        usage["output_tokens"] = meta.get("candidatesTokenCount")
                except Exception:
                    pass


async def _openrouter_tokens(model: str, messages: list[dict], system: str | None, user_id: str, json_mode: bool = False, usage: dict | None = None) -> AsyncGenerator[str, None]:
    api_key = db.get_user_key(user_id, "openrouter")
    if not api_key:
        raise ValueError("OpenRouter API key not configured in Settings")

    msgs = ([{"role": "system", "content": system}] if system else []) + messages
    body: dict = {"model": model, "stream": True, "messages": msgs}
    if usage is not None:
        body["stream_options"] = {"include_usage": True}
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
                    choices = d.get("choices") or [{}]
                    text = choices[0].get("delta", {}).get("content", "") if choices else ""
                    if text:
                        yield text
                    u = d.get("usage")
                    if usage is not None and u:
                        usage["input_tokens"] = u.get("prompt_tokens")
                        usage["output_tokens"] = u.get("completion_tokens")
                except Exception:
                    pass


async def _anthropic_tokens(model: str, messages: list[dict], system: str | None, user_id: str, usage: dict | None = None) -> AsyncGenerator[str, None]:
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
                    elif usage is not None and d.get("type") == "message_start":
                        u = d.get("message", {}).get("usage", {})
                        if u.get("input_tokens") is not None:
                            usage["input_tokens"] = u.get("input_tokens")
                        if u.get("output_tokens") is not None:
                            usage["output_tokens"] = u.get("output_tokens")
                    elif usage is not None and d.get("type") == "message_delta":
                        u = d.get("usage", {})
                        if u.get("output_tokens") is not None:
                            usage["output_tokens"] = u.get("output_tokens")
                except Exception:
                    pass


async def _openai_tokens(model: str, messages: list[dict], system: str | None, user_id: str, usage: dict | None = None) -> AsyncGenerator[str, None]:
    api_key = db.get_user_key(user_id, "openai")
    if not api_key:
        raise ValueError("OpenAI API key not configured in Settings")

    msgs = ([{"role": "system", "content": system}] if system else []) + messages
    body = {"model": model, "stream": True, "messages": msgs}
    if usage is not None:
        body["stream_options"] = {"include_usage": True}

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
                    choices = d.get("choices") or [{}]
                    text = choices[0].get("delta", {}).get("content", "") if choices else ""
                    if text:
                        yield text
                    u = d.get("usage")
                    if usage is not None and u:
                        usage["input_tokens"] = u.get("prompt_tokens")
                        usage["output_tokens"] = u.get("completion_tokens")
                except Exception:
                    pass


async def _ollama_tokens(model: str, messages: list[dict], system: str | None, user_id: str, json_mode: bool = False, usage: dict | None = None) -> AsyncGenerator[str, None]:
    host = db.get_setting("ollama_host") or "http://localhost:11434"
    msgs = ([{"role": "system", "content": system}] if system else []) + messages

    body: dict = {"model": model, "stream": True, "messages": msgs, "options": {"num_ctx": 32768}}
    if json_mode:
        body["format"] = "json"
    async with httpx.AsyncClient(timeout=600) as client:
        async with client.stream("POST", f"{host}/api/chat", json=body) as r:
            if r.status_code >= 400:
                raw = await r.aread()
                try:
                    err_obj = json.loads(raw)
                    err_msg = err_obj.get("error") or raw.decode()
                except Exception:
                    err_msg = raw.decode()
                raise ValueError(f"Ollama {r.status_code}: {err_msg}")
            async for line in r.aiter_lines():
                if not line.strip():
                    continue
                try:
                    d = json.loads(line)
                    text = d.get("message", {}).get("content", "")
                    if text:
                        yield text
                    if usage is not None and d.get("done"):
                        usage["input_tokens"] = d.get("prompt_eval_count")
                        usage["output_tokens"] = d.get("eval_count")
                except Exception:
                    pass


def provider_tokens(provider: str, model: str, messages: list[dict], system: str | None = None, user_id: str = "local", json_mode: bool = False, usage: dict | None = None) -> AsyncGenerator[str, None]:
    if provider == "gemini":
        return _gemini_tokens(model, messages, system, user_id, usage=usage)
    if provider == "openrouter":
        return _openrouter_tokens(model, messages, system, user_id, json_mode=json_mode, usage=usage)
    if provider == "anthropic":
        return _anthropic_tokens(model, messages, system, user_id, usage=usage)
    if provider == "openai":
        return _openai_tokens(model, messages, system, user_id, usage=usage)
    if provider == "ollama":
        return _ollama_tokens(model, messages, system, user_id, json_mode=json_mode, usage=usage)
    raise ValueError(f"Unknown provider: {provider}")



async def call_llm(agent_key: str, messages: list[dict], system: str | None = None, user_id: str = "local", book_id: str | None = None) -> str:
    provider, model = db.resolve_agent(agent_key, book_id=book_id)

    if not provider or not model:
        raise ValueError(f'Agent "{agent_key}" has no model assigned')

    result = ""
    usage: dict = {}
    async for token in provider_tokens(provider, model, messages, system, user_id, usage=usage):
        result += token
    db.log_llm_usage(
        agent_key, provider=provider, model=model,
        input_tokens=usage.get("input_tokens"), output_tokens=usage.get("output_tokens"),
        book_id=book_id,
    )
    return result
