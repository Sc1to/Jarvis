from fastapi import APIRouter
import db

router = APIRouter()


@router.get("/settings")
def get_settings():
    return db.get_all_settings()


@router.post("/settings")
def update_settings(updates: dict):
    for k, v in updates.items():
        if isinstance(v, str):
            db.set_setting(k, v)
    return {"ok": True}
