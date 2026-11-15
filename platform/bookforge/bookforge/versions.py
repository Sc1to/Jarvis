"""Earlier versions of the files a layer's work replaces: books/<book>/previous/<stamp>-<reason>/<path>.

Redoing a layer, a failed whole-book check and a ledger that starts over each replace or remove a file you may want back: the plan as it was before.
Git has it too, but not where you can reach it from the dashboard. Every such moment keeps a copy here first; the Documents tab lists them and
restores one in a click. Nothing here is ever deleted by the pipeline, except the oldest copies beyond KEEP.
"""

import shutil
from datetime import datetime, timezone
from pathlib import Path

from .bible import store
from .errors import BookforgeError

KEEP = 30  # snapshots kept per book; the oldest go first

# what each planning layer makes (relative to the series folder, where the book is books/<book>)
def layer_files(project, layer: str) -> list[Path]:
    book = project.book_dir
    files = {"ledger": [store.ledger_path(project)], "acts": [store.acts_path(project)], "chapters": [store.chapters_path(project), store.constants_path(project), store.tracks_path(project)],
             "scenes": [store.scenes_path(project), store.timeline_path(project), store.tracks_path(project)]}
    return [p for p in files.get(layer, []) if p.is_file() and p.is_relative_to(project.root)] if book else []


def keep(project, paths: list[Path], reason: str) -> str | None:
    """Copy the existing files to a new snapshot. Returns its name, or None when there was nothing to keep. Never raises: keeping a copy must not stop the work."""
    existing = [p for p in dict.fromkeys(paths) if p.is_file() and p.stat().st_size > 0]
    if not existing:
        return None
    try:
        name = f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{reason}"
        base = project.book_dir / "previous" / name
        for p in existing:
            target = base / p.relative_to(project.root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, target)
        _prune(project)
        return name
    except OSError:
        return None


def _prune(project) -> None:
    root = project.book_dir / "previous"
    folders = sorted(d for d in root.iterdir() if d.is_dir()) if root.is_dir() else []
    for old in folders[:-KEEP]:
        shutil.rmtree(old, ignore_errors=True)


def list_versions(project) -> list[dict]:
    """Newest first: [{name, reason, at, files: [relative paths]}]."""
    root = project.book_dir / "previous"
    out = []
    for d in sorted((x for x in root.iterdir() if x.is_dir()), reverse=True) if root.is_dir() else []:
        stamp, _, reason = d.name.partition("-")
        rest = d.name.split("-", 2)
        out.append({"name": d.name, "reason": rest[2] if len(rest) > 2 else "", "at": d.name[:15],
                    "files": sorted(str(f.relative_to(d)) for f in d.rglob("*") if f.is_file())})
    return out


def restore(project, name: str, only: str | None = None) -> list[str]:
    """Put a snapshot's files back (the current ones are kept first as their own snapshot). Returns the files restored."""
    base = project.book_dir / "previous" / name
    if not base.is_dir() or ".." in name or "/" in name:
        raise BookforgeError(f"no earlier version '{name}'")
    files = [f for f in base.rglob("*") if f.is_file() and (only is None or str(f.relative_to(base)) == only)]
    if not files:
        raise BookforgeError(f"'{name}' has no file {only}" if only else f"'{name}' is empty")
    keep(project, [project.root / f.relative_to(base) for f in files], "before-restore")
    done = []
    for f in files:
        target = project.root / f.relative_to(base)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, target)
        done.append(str(f.relative_to(base)))
    return done
