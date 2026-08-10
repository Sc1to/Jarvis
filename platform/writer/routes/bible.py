import json
import os

from fastapi import APIRouter, HTTPException

import db

router = APIRouter()


@router.get("/books/{book_id}/bible")
def get_bible(book_id: str):
    path = os.path.join(db.data_dir(book_id), "bible.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


@router.get("/books/{book_id}/bible/entity/{entity_id}")
def get_entity(book_id: str, entity_id: str):
    path = os.path.join(db.data_dir(book_id), "bible.json")
    if not os.path.exists(path):
        raise HTTPException(404, "No bible found")
    with open(path) as f:
        bible = json.load(f)
    entity = bible.get("ledger", {}).get(entity_id)
    if not entity:
        raise HTTPException(404, "Entity not found")
    return entity
