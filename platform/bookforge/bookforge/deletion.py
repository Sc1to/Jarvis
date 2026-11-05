"""Deleting books and series.

A **book** is removed from its series: its folder `books/<book>/` goes, and so do that book's entries in the series-wide
bible files (`bible/tracks.yaml` plan and observed entries, `bible/timeline.yaml`), in the workbench's calibration scores
and threads. The shared parts stay: the cast and rules, the style, the banned phrases, the premise, and every other book.
It is a Git commit, so the book can be restored from history (`git revert`, or checking the folder out of the commit before).
Rules in `workbench/rules.yaml` scoped to the book are left alone and counted in the result (they no longer apply to anything).

A **series** is moved to `<data dir>/.trash/<name>-<stamp>/`, not deleted: the folder is its own Git repository, so Git
cannot bring it back. `restore` moves it back; `empty_trash` removes what is in the trash for good.
"""

import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import vcs
from .bible.store import dump_yaml
from .errors import BookforgeError
from .project import BOOK_ID_RE

TRASH = ".trash"
_STAMPED = re.compile(r"^(?P<name>.+)-(?P<stamp>\d{8}-\d{6})$")


class DeleteError(BookforgeError):
    pass


def _book_of(position: str) -> str:
    return str(position).split(".", 1)[0]


def _read(path: Path):
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None


# ── a book ────────────────────────────────────────────────────────────────────

def delete_book(root: Path, book: str, commit: bool = True) -> dict:
    root = Path(root)
    if not BOOK_ID_RE.match(book):
        raise DeleteError(f"invalid book id '{book}'")
    book_dir = root / "books" / book
    if not book_dir.is_dir():
        raise DeleteError(f"no book '{book}' in {root.name}")
    result = {"book": book, "tracks_removed": 0, "track_entries_removed": 0, "timeline_removed": 0,
              "calibration_removed": 0, "threads_removed": 0, "inactive_rules": 0}

    tracks_path = root / "bible" / "tracks.yaml"
    data = _read(tracks_path)
    if isinstance(data, dict) and isinstance(data.get("tracks"), list):
        kept = []
        for t in data["tracks"]:
            plan = [e for e in t.get("plan", []) if _book_of(e.get("from", "")) != book]
            observed = [o for o in t.get("observed", []) if _book_of(o.get("at", "")) != book]
            result["track_entries_removed"] += (len(t.get("plan", [])) - len(plan)) + (len(t.get("observed", [])) - len(observed))
            if plan:
                kept.append({**t, "plan": plan, "observed": observed})
            elif t.get("plan"):
                result["tracks_removed"] += 1  # a track that only this book used
            else:
                kept.append(t)
        tracks_path.write_text(dump_yaml({"tracks": kept}), encoding="utf-8")

    timeline_path = root / "bible" / "timeline.yaml"
    data = _read(timeline_path)
    if isinstance(data, dict) and isinstance(data.get("scenes"), list):
        kept = [s for s in data["scenes"] if _book_of(s.get("id", "")) != book]
        result["timeline_removed"] = len(data["scenes"]) - len(kept)
        timeline_path.write_text(dump_yaml({"scenes": kept}), encoding="utf-8")

    calibration_path = root / "workbench" / "calibration.yaml"
    data = _read(calibration_path)
    if isinstance(data, dict) and isinstance(data.get("scores"), dict):
        kept = {k: v for k, v in data["scores"].items() if _book_of(k) != book}
        result["calibration_removed"] = len(data["scores"]) - len(kept)
        calibration_path.write_text(yaml.safe_dump({"scores": kept}, sort_keys=True), encoding="utf-8")

    threads_path = root / "workbench" / "threads.yaml"
    data = _read(threads_path)
    if isinstance(data, dict) and isinstance(data.get("threads"), list):
        kept = [t for t in data["threads"] if _book_of(t.get("setup", "")) != book]
        result["threads_removed"] = len(data["threads"]) - len(kept)
        threads_path.write_text(yaml.safe_dump({"threads": kept}, sort_keys=False, allow_unicode=True), encoding="utf-8")

    rules = _read(root / "workbench" / "rules.yaml")
    if isinstance(rules, dict):
        result["inactive_rules"] = sum(1 for r in rules.get("rules", []) if r.get("scope") in ("book", "scene") and _book_of(r.get("target", "")) == book)

    shutil.rmtree(book_dir)
    if commit and vcs.is_repo(root):
        paths = [f"books/{book}", "bible/tracks.yaml", "bible/timeline.yaml", "workbench"]
        vcs.commit(root, f"delete book {book}: removed its folder and its entries in the shared bible files",
                   [p for p in paths if p.startswith("books") or (root / p).exists()])
    return result


# ── a series ──────────────────────────────────────────────────────────────────

def trash_dir(data_dir: Path) -> Path:
    return Path(data_dir) / TRASH


def trash_series(data_dir: Path, name: str) -> Path:
    """Move a series into the trash. Returns where it went."""
    data_dir = Path(data_dir)
    src = data_dir / name
    if not (src / "premise.md").is_file():
        raise DeleteError(f"no series '{name}'")
    dest = trash_dir(data_dir) / f"{name}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    n = 1
    while dest.exists():
        n += 1
        dest = trash_dir(data_dir) / f"{name}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{n}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    return dest


def list_trash(data_dir: Path) -> list[dict]:
    d = trash_dir(data_dir)
    out = []
    for p in sorted(d.iterdir(), reverse=True) if d.is_dir() else []:
        if not p.is_dir():
            continue
        m = _STAMPED.match(p.name)
        stamp = None
        if m:
            try:
                stamp = datetime.strptime(m.group("stamp"), "%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc).isoformat(timespec="seconds")
            except ValueError:
                stamp = None
        books = sorted(b.name for b in (p / "books").iterdir() if b.is_dir()) if (p / "books").is_dir() else []
        out.append({"name": p.name, "series": m.group("name") if m else p.name, "deleted": stamp, "books": books})
    return out


def restore(data_dir: Path, trash_name: str) -> str:
    """Move a trashed series back under its original name. Refuses if that name is in use."""
    src = trash_dir(data_dir) / trash_name
    if not src.is_dir():
        raise DeleteError(f"nothing in the trash called '{trash_name}'")
    m = _STAMPED.match(trash_name)
    original = m.group("name") if m else trash_name
    dest = Path(data_dir) / original
    if dest.exists():
        raise DeleteError(f"a series called '{original}' exists now; rename or delete it first, or restore this one by hand")
    shutil.move(str(src), str(dest))
    return original


def empty_trash(data_dir: Path) -> int:
    d = trash_dir(data_dir)
    n = 0
    for p in list(d.iterdir()) if d.is_dir() else []:
        shutil.rmtree(p) if p.is_dir() else p.unlink()
        n += 1
    return n
