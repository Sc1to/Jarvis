import json
import os
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import db

router = APIRouter()


def _series_bible_path(series_id: str) -> str:
    return os.path.join(db.series_data_dir(series_id), "series_bible.json")


def _read_series_bible(series_id: str) -> dict:
    p = _series_bible_path(series_id)
    if not os.path.exists(p):
        return {"metadata": {}, "ledger": {}}
    with open(p) as f:
        return json.load(f)


def _write_series_bible(series_id: str, bible: dict) -> None:
    p = _series_bible_path(series_id)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        json.dump(bible, f, indent=2)


# ── CRUD ──────────────────────────────────────────────────────────────────────

class CreateSeriesBody(BaseModel):
    title: str


@router.get("/series")
def list_series():
    return db.list_series()


@router.post("/series", status_code=201)
def create_series(body: CreateSeriesBody):
    title = body.title.strip()
    if not title:
        raise HTTPException(400, "title required")
    series = db.create_series(title)
    db.ensure_series_data_dir(series["id"])
    _write_series_bible(series["id"], {
        "metadata": {
            "series_id": series["id"],
            "title": series["title"],
            "last_updated": datetime.now(timezone.utc).isoformat(),
        },
        "ledger": {},
    })
    return series


@router.get("/series/{series_id}")
def get_series(series_id: str):
    series = db.get_series(series_id)
    if not series:
        raise HTTPException(404, "Not found")
    return {**series, "books": db.list_books_in_series(series_id)}


@router.delete("/series/{series_id}")
def delete_series_route(series_id: str):
    if not db.get_series(series_id):
        raise HTTPException(404, "Not found")
    db.delete_series(series_id)
    return {"ok": True}


# ── Series Bible ──────────────────────────────────────────────────────────────

@router.get("/series/{series_id}/bible")
def get_series_bible(series_id: str):
    if not db.get_series(series_id):
        raise HTTPException(404, "Not found")
    return _read_series_bible(series_id)


class EntityBody(BaseModel):
    entity_id: str
    data: dict


@router.post("/series/{series_id}/bible/entity")
def upsert_series_entity(series_id: str, body: EntityBody):
    if not db.get_series(series_id):
        raise HTTPException(404, "Not found")
    bible = _read_series_bible(series_id)
    bible["ledger"][body.entity_id] = body.data
    bible.setdefault("metadata", {})["last_updated"] = datetime.now(timezone.utc).isoformat()
    _write_series_bible(series_id, bible)
    return {"ok": True, "entity_id": body.entity_id}


# ── North Star & Style Sheet ──────────────────────────────────────────────────

def read_series_text(series_id: str, filename: str) -> str:
    p = os.path.join(db.series_data_dir(series_id), filename)
    return open(p).read() if os.path.exists(p) else ""


def _write_series_text(series_id: str, filename: str, content: str) -> None:
    d = db.series_data_dir(series_id)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, filename), "w") as f:
        f.write(content)


class TextBody(BaseModel):
    content: str


@router.get("/series/{series_id}/north-star")
def get_series_north_star(series_id: str):
    if not db.get_series(series_id):
        raise HTTPException(404, "Not found")
    return {"content": read_series_text(series_id, "north_star.md")}


@router.post("/series/{series_id}/north-star")
def save_series_north_star(series_id: str, body: TextBody):
    if not db.get_series(series_id):
        raise HTTPException(404, "Not found")
    _write_series_text(series_id, "north_star.md", body.content)
    return {"ok": True}


@router.get("/series/{series_id}/style-sheet")
def get_series_style_sheet(series_id: str):
    if not db.get_series(series_id):
        raise HTTPException(404, "Not found")
    return {"content": read_series_text(series_id, "style_sheet.md")}


@router.post("/series/{series_id}/style-sheet")
def save_series_style_sheet(series_id: str, body: TextBody):
    if not db.get_series(series_id):
        raise HTTPException(404, "Not found")
    _write_series_text(series_id, "style_sheet.md", body.content)
    return {"ok": True}


# ── Sync book → series ────────────────────────────────────────────────────────

@router.post("/books/{book_id}/sync-to-series")
def sync_book_to_series(book_id: str):
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(404, "Book not found")
    series_id = book.get("series_id")
    if not series_id:
        raise HTTPException(400, "Book is not part of a series")

    book_bible_path = os.path.join(db.data_dir(book_id), "bible.json")
    if not os.path.exists(book_bible_path):
        raise HTTPException(400, "Book has no bible.json yet — complete at least Phase 2 first")

    with open(book_bible_path) as f:
        book_bible = json.load(f)

    book_ledger = book_bible.get("ledger", {})
    series_bible = _read_series_bible(series_id)
    series_ledger = series_bible.get("ledger", {})

    added, updated = [], []
    for entity_id, entity in book_ledger.items():
        if entity_id not in series_ledger:
            added.append(entity_id)
        else:
            updated.append(entity_id)
        series_ledger[entity_id] = entity

    series_bible["ledger"] = series_ledger
    series_bible.setdefault("metadata", {})["last_updated"] = datetime.now(timezone.utc).isoformat()
    _write_series_bible(series_id, series_bible)

    return {"ok": True, "added": added, "updated": updated}
