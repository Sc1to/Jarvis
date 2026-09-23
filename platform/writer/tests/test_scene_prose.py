"""Tests for PUT /books/{id}/phase3/chapter/{ch}/scene/{sc}/prose (author hand-edits)."""

import json
import os
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from git import Repo

WRITER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, WRITER_DIR)

BOOK = "book1"
CHAPTER = (
    "# Chapter 1\n\n"
    "## Scene 1\n\nFirst scene draft.\n\n---\n\n"
    "## Scene 2\n\nSecond scene draft.\n\n---\n\n"
    "## Scene 10\n\nTenth scene draft."
)


@pytest.fixture
def client(tmp_path, monkeypatch):
    import db
    from routes.phase3 import router

    monkeypatch.setattr(db, "DATA_ROOT", str(tmp_path))
    book_dir = tmp_path / BOOK
    book_dir.mkdir()
    (book_dir / "chapter_01.md").write_text(CHAPTER)
    meta = {"chapter": 1, "status": "written", "scenes": [
        {"scene": n, "word_count": 3, "qa_pass": True} for n in (1, 2, 10)
    ]}
    (book_dir / "chapter_01_meta.json").write_text(json.dumps(meta))
    repo = Repo.init(book_dir)
    repo.index.add(["chapter_01.md", "chapter_01_meta.json"])
    repo.index.commit("init")

    app = FastAPI()
    app.include_router(router)
    return TestClient(app), book_dir


def _put(c, scene, content):
    return c.put(f"/books/{BOOK}/phase3/chapter/1/scene/{scene}/prose", json={"content": content})


def test_save_replaces_only_target_scene(client):
    c, book_dir = client
    edited = "Hand-edited first scene.\n\nWith a second paragraph and a \\n backslash."
    resp = _put(c, 1, edited)
    assert resp.status_code == 200
    assert resp.json()["data"] == {"saved": True, "word_count": 11}

    content = (book_dir / "chapter_01.md").read_text()
    assert f"## Scene 1\n\n{edited}\n\n---\n\n## Scene 2" in content
    assert "Second scene draft." in content
    assert "Tenth scene draft." in content

    meta = json.loads((book_dir / "chapter_01_meta.json").read_text())
    s1 = next(s for s in meta["scenes"] if s["scene"] == 1)
    assert s1["author_edited"] is True and s1["word_count"] == 11
    assert "author_edited" not in next(s for s in meta["scenes"] if s["scene"] == 2)

    assert Repo(book_dir).head.commit.message == "Author edit: Chapter 1 Scene 1"


def test_scene_1_does_not_match_scene_10(client):
    c, book_dir = client
    assert _put(c, 10, "New tenth.").status_code == 200
    content = (book_dir / "chapter_01.md").read_text()
    assert content.endswith("## Scene 10\n\nNew tenth.")
    assert "First scene draft." in content


def test_unchanged_text_is_not_committed(client):
    c, book_dir = client
    resp = _put(c, 2, "  Second scene draft.  ")
    assert resp.json()["data"]["saved"] is False
    assert Repo(book_dir).head.commit.message == "init"


def test_rejects_empty_missing_and_approved(client):
    c, book_dir = client
    assert _put(c, 1, "   ").status_code == 400
    assert _put(c, 3, "Nope").status_code == 404
    assert c.put(f"/books/{BOOK}/phase3/chapter/9/scene/1/prose", json={"content": "x"}).status_code == 404

    meta_path = book_dir / "chapter_01_meta.json"
    meta = json.loads(meta_path.read_text())
    meta["status"] = "approved"
    meta_path.write_text(json.dumps(meta))
    assert _put(c, 1, "Too late").status_code == 409
