import os
import shutil

from fastapi import APIRouter, HTTPException
from git import Repo
from pydantic import BaseModel

import db

router = APIRouter()


class CreateBookBody(BaseModel):
    title: str


@router.get("/books")
def list_books():
    return db.list_books()


@router.post("/books", status_code=201)
def create_book(body: CreateBookBody):
    title = body.title.strip()
    if not title:
        raise HTTPException(400, "title required")
    book = db.create_book(title)
    book_dir = db.ensure_data_dir(book["id"])
    repo = Repo.init(book_dir)
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Novellist")
        cw.set_value("user", "email", "novellist@local")
    return book


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
