import json
import os

from fastapi import APIRouter
from git import Repo, InvalidGitRepositoryError
from pydantic import BaseModel

import db

router = APIRouter()


@router.get("/books/{book_id}/git/log")
def git_log(book_id: str):
    book_dir = db.data_dir(book_id)
    if not os.path.exists(os.path.join(book_dir, ".git")):
        return []
    try:
        repo = Repo(book_dir)
        commits = []
        for c in repo.iter_commits(max_count=100):
            commits.append({
                "hash": c.hexsha,
                "date": c.committed_datetime.isoformat(),
                "message": c.message.strip(),
                "author_name": c.author.name,
                "author_email": c.author.email,
            })
        return commits
    except Exception:
        return []


@router.get("/books/{book_id}/git/diff/{commit}")
def git_diff(book_id: str, commit: str):
    diff_path = os.path.join(db.data_dir(book_id), "bible_diff.json")
    if not os.path.exists(diff_path):
        return None
    with open(diff_path) as f:
        return json.load(f)


class RestoreBody(BaseModel):
    sha: str


@router.post("/books/{book_id}/git/restore")
def git_restore(book_id: str, body: RestoreBody):
    book_dir = db.data_dir(book_id)
    if not os.path.exists(os.path.join(book_dir, ".git")):
        return {"error": "no git repo"}
    try:
        repo = Repo(book_dir)
        commit = repo.commit(body.sha)
    except Exception:
        return {"error": "commit not found"}
    first_line = commit.message.strip().split("\n")[0]
    repo.git.checkout(body.sha, "--", ".")
    try:
        repo.git.add("-A")
        repo.git.commit(m=f"Restored to: {first_line}")
    except Exception:
        pass  # nothing to commit if state was already identical
    return {"ok": True}
