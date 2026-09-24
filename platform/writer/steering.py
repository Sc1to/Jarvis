"""
Per-book steering: the author's length target and standing notes.

Stored in <book_dir>/steering.json so it is versioned with the book:
  {
    "target_chapter_words": 3000 | null,
    "book_notes": "...",                 # apply to every scene in the book
    "chapter_notes": {"3": "..."}        # apply to every scene in that chapter
  }
"""
import json
import os
import re

import db

FILE_NAME = "steering.json"

# Per-scene target when the author has not set a chapter target.
DEFAULT_SCENE_WORDS = 750
MIN_SCENE_WORDS = 150
# A scene longer than target × LENGTH_TOLERANCE is too long.
LENGTH_TOLERANCE = 1.25


def _path(book_id: str) -> str:
    return os.path.join(db.data_dir(book_id), FILE_NAME)


def read(book_id: str) -> dict:
    data: dict = {}
    p = _path(book_id)
    if os.path.exists(p):
        try:
            with open(p) as f:
                data = json.load(f)
        except Exception:
            data = {}
    return normalise(data)


def write(book_id: str, data: dict) -> dict:
    clean = normalise(data)
    with open(_path(book_id), "w") as f:
        json.dump(clean, f, indent=2)
    return clean


def normalise(data: dict) -> dict:
    target = data.get("target_chapter_words")
    return {
        "target_chapter_words": int(target) if isinstance(target, (int, float)) and target > 0 else None,
        "book_notes": (data.get("book_notes") or "").strip(),
        "chapter_notes": {
            str(k): v.strip() for k, v in (data.get("chapter_notes") or {}).items()
            if isinstance(v, str) and v.strip()
        },
    }


def notes_for(book_id: str, chapter: int) -> str:
    """Combined standing notes for a chapter: book-wide first, then chapter-specific."""
    s = read(book_id)
    parts = []
    if s["book_notes"]:
        parts.append(f"Whole book:\n{s['book_notes']}")
    ch = s["chapter_notes"].get(str(chapter))
    if ch:
        parts.append(f"This chapter:\n{ch}")
    return "\n\n".join(parts)


def scene_word_target(book_id: str, scene_count: int) -> int:
    """Per-scene word target: the chapter target split evenly across its scenes."""
    target = read(book_id)["target_chapter_words"]
    if not target or scene_count <= 0:
        return DEFAULT_SCENE_WORDS
    return max(MIN_SCENE_WORDS, round(target / scene_count))


def word_limit(target: int) -> int:
    return int(target * LENGTH_TOLERANCE)


def planned_scene_count(book_id: str, chapter: int) -> int:
    """Number of scenes planned for a chapter: saved scene plan, else '### Scene N' headings in tier4."""
    book_dir = db.data_dir(book_id)
    plan_path = os.path.join(book_dir, f"chapter_{chapter:02d}_plan.json")
    if os.path.exists(plan_path):
        try:
            with open(plan_path) as f:
                plan = json.load(f)
            if isinstance(plan, list) and plan:
                return len(plan)
        except Exception:
            pass
    tier4_path = os.path.join(book_dir, "tier4", f"chapter_{chapter:02d}.md")
    if os.path.exists(tier4_path):
        with open(tier4_path) as f:
            return len(set(re.findall(r"^### Scene (\d+)", f.read(), re.MULTILINE)))
    return 0
