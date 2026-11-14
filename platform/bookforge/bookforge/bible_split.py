"""Give each book of an older series its own bible.

An older series keeps one `bible/` (cast and rules, state tracks, timeline) at its root, shared by every book. Each book now has its own
(`books/<book>/bible/`), so a sequel can change a character without touching the first book. `split_bible` gives every book a copy of
the shared cast and its own part of the tracks and the timeline (the entries whose positions belong to it), then removes the shared
folder. What is there is committed first, so the step can be undone with Git.
"""

import shutil
from pathlib import Path

import yaml

from . import vcs
from .bible.store import dump_yaml
from .books import book_ids
from .errors import BookforgeError


def has_shared_bible(root: Path) -> bool:
    return (Path(root) / "bible").is_dir()


def _read(path: Path):
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}


def _book_of(position: str) -> str:
    return str(position).split(".", 1)[0]


def split_bible(root: Path, commit: bool = True) -> dict:
    """Copy the shared bible into every book (tracks and timeline filtered to that book), remove the shared one. Returns counts per book."""
    root = Path(root)
    if not has_shared_bible(root):
        raise BookforgeError("this series already has a bible per book: nothing to split")
    books = book_ids(root)
    if not books:
        raise BookforgeError("the series has no books")
    if commit and vcs.is_repo(root):
        vcs.commit(root, "series: before giving each book its own bible (everything as it was)")
    shared = root / "bible"
    constants_text = (shared / "constants.yaml").read_text(encoding="utf-8") if (shared / "constants.yaml").is_file() else "{}\n"
    tracks = _read(shared / "tracks.yaml").get("tracks") or []
    timeline = _read(shared / "timeline.yaml").get("scenes") or []
    summary: dict[str, dict] = {}
    for book in books:
        target = root / "books" / book / "bible"
        target.mkdir(parents=True, exist_ok=True)
        (target / "constants.yaml").write_text(constants_text, encoding="utf-8")
        mine = []
        for t in tracks:
            plan = [e for e in t.get("plan") or [] if _book_of(e.get("from", "")) == book]
            observed = [o for o in t.get("observed") or [] if _book_of(o.get("at", "")) == book]
            if plan or (t.get("starts_as") and not t.get("plan")):
                mine.append({**t, "plan": plan, "observed": observed})
        scenes = [s for s in timeline if _book_of(s.get("id", "")) == book]
        (target / "tracks.yaml").write_text(dump_yaml({"tracks": mine}), encoding="utf-8")
        (target / "timeline.yaml").write_text(dump_yaml({"scenes": scenes}), encoding="utf-8")
        summary[book] = {"tracks": len(mine), "timeline": len(scenes)}
    shutil.rmtree(shared)
    if commit and vcs.is_repo(root):
        vcs.commit(root, "series: each book now has its own bible (" + ", ".join(books) + ")")
    return summary
