from fastapi import APIRouter, HTTPException
import httpx
import db

router = APIRouter()


@router.get("/models/gemini")
async def gemini_models():
    api_key = db.get_setting("gemini_api_key")
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
async def openrouter_models():
    api_key = db.get_setting("openrouter_api_key")
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
