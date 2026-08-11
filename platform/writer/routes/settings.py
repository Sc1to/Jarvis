from fastapi import APIRouter, Depends
import db
from deps import current_user

router = APIRouter()

_API_KEY_PROVIDERS = {"gemini", "openrouter", "anthropic", "openai"}


@router.get("/settings")
def get_settings(user: str = Depends(current_user)):
    settings = db.get_all_settings()
    # Overlay this user's API keys on top of global settings
    for provider, api_key in db.get_user_keys(user).items():
        settings[f"{provider}_api_key"] = api_key
    return settings


@router.post("/settings")
def update_settings(updates: dict, user: str = Depends(current_user)):
    for k, v in updates.items():
        if not isinstance(v, str):
            continue
        # e.g. "gemini_api_key" → provider "gemini"
        provider = k.removesuffix("_api_key")
        if provider in _API_KEY_PROVIDERS:
            db.set_user_key(user, provider, v)
        else:
            db.set_setting(k, v)
    return {"ok": True}
