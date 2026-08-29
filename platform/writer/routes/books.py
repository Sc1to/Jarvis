import json
import os
import shutil

from fastapi import APIRouter, HTTPException
from git import Repo
from pydantic import BaseModel

import db

router = APIRouter()


class CreateBookBody(BaseModel):
    title: str
    series_id: str | None = None
    series_order: int | None = None


@router.get("/books")
def list_books():
    return db.list_books()


@router.post("/books", status_code=201)
def create_book(body: CreateBookBody):
    title = body.title.strip()
    if not title:
        raise HTTPException(400, "title required")
    if body.series_id and not db.get_series(body.series_id):
        raise HTTPException(404, "Series not found")
    book = db.create_book(title, series_id=body.series_id, series_order=body.series_order)
    book_dir = db.ensure_data_dir(book["id"])
    repo = Repo.init(book_dir)
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Novellist")
        cw.set_value("user", "email", "novellist@local")
    if body.series_id:
        _seed_skeleton_from_series(book["id"], body.series_id)
    return book


def _seed_skeleton_from_series(book_id: str, series_id: str) -> None:
    series_bible_path = os.path.join(db.series_data_dir(series_id), "series_bible.json")
    if not os.path.exists(series_bible_path):
        return
    with open(series_bible_path) as f:
        series_bible = json.load(f)
    ledger = series_bible.get("ledger", {})
    if not ledger:
        return
    entities = [
        {
            "id": eid,
            "type": entity.get("type"),
            "name": entity.get("name"),
            "series_source": True,
            "series_facts": entity.get("series_facts", {}),
            "book_facts": {},
            "eventLog": [],
        }
        for eid, entity in ledger.items()
    ]
    skeleton = {"acts": [], "entities": entities}
    skeleton_path = os.path.join(db.data_dir(book_id), "bible_skeleton.json")
    with open(skeleton_path, "w") as f:
        json.dump(skeleton, f, indent=2)


@router.get("/books/{book_id}")
def get_book(book_id: str):
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(404, "Not found")
    return book


@router.delete("/books/{book_id}")
def delete_book_route(book_id: str):
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(404, "Not found")
    db.delete_book(book_id)
    book_dir = db.data_dir(book_id)
    if os.path.exists(book_dir):
        shutil.rmtree(book_dir)
    return {"ok": True}
