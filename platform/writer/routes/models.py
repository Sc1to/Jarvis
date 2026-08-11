from fastapi import APIRouter, Depends, HTTPException
import httpx
import db
from deps import current_user

router = APIRouter()


@router.get("/models/gemini")
async def gemini_models(user: str = Depends(current_user)):
    api_key = db.get_user_key(user, "gemini")
    if not api_key:
        raise HTTPException(400, "No Gemini API key configured")
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}")
            data = r.json()
        return [
            {"id": m["name"].replace("models/", ""), "name": m["displayName"]}
            for m in data.get("models", [])
            if "generateContent" in m.get("supportedGenerationMethods", [])
        ]
    except Exception:
        raise HTTPException(502, "Failed to fetch Gemini models")


@router.get("/models/openrouter")
async def openrouter_models(user: str = Depends(current_user)):
    api_key = db.get_user_key(user, "openrouter")
    if not api_key:
        raise HTTPException(400, "No OpenRouter API key configured")
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(
                "https://openrouter.ai/api/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            data = r.json()
        return [
            {"id": m["id"], "name": m["name"], "free": m.get("pricing", {}).get("prompt") == "0"}
            for m in data.get("data", [])
        ]
    except Exception:
        raise HTTPException(502, "Failed to fetch OpenRouter models")


@router.get("/models/anthropic")
async def anthropic_models(user: str = Depends(current_user)):
    api_key = db.get_user_key(user, "anthropic")
    if not api_key:
        raise HTTPException(400, "No Anthropic API key configured")
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(
                "https://api.anthropic.com/v1/models",
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
            )
            data = r.json()
        return [{"id": m["id"], "name": m.get("display_name", m["id"])} for m in data.get("data", [])]
    except Exception:
        raise HTTPException(502, "Failed to fetch Anthropic models")


_OPENAI_CHAT_PREFIXES = ("gpt-", "o1", "o3", "o4", "chatgpt-")


@router.get("/models/openai")
async def openai_models(user: str = Depends(current_user)):
    api_key = db.get_user_key(user, "openai")
    if not api_key:
        raise HTTPException(400, "No OpenAI API key configured")
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            data = r.json()
        models = [
            {"id": m["id"], "name": m["id"]}
            for m in data.get("data", [])
            if any(m["id"].startswith(p) for p in _OPENAI_CHAT_PREFIXES)
        ]
        return sorted(models, key=lambda m: m["id"])
    except Exception:
        raise HTTPException(502, "Failed to fetch OpenAI models")


@router.get("/models/ollama")
async def ollama_models():
    host = db.get_setting("ollama_host") or "http://localhost:11434"
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{host}/api/tags")
            data = r.json()
        return [{"id": m["name"], "name": m["name"]} for m in data.get("models", [])]
    except Exception:
        raise HTTPException(502, "Ollama not reachable")
