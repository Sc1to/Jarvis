"""Reading and writing the bible and structure files (YAML, written from validated records)."""

from pathlib import Path
from typing import Iterable

import yaml
from pydantic import BaseModel, ValidationError

from ..errors import BookforgeError
from ..project import Project
from .models import Act, Chapter, Constants, Ledger, Scene, TimelineEntry, Track, problems_from


class BibleError(BookforgeError):
    pass


def dump_yaml(data) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100, default_flow_style=False)


def to_plain(record: BaseModel) -> dict:
    return record.model_dump(by_alias=True, exclude_defaults=False)


def _load(path: Path):
    if not path.exists():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise BibleError(f"{path} is not valid YAML: {e}") from e


def _records(path: Path, key: str, cls) -> list:
    data = _load(path)
    if not data:
        return []
    if not isinstance(data, dict) or not isinstance(data.get(key), list):
        raise BibleError(f"{path}: expected a '{key}:' list at the top level")
    try:
        return [cls.model_validate(item) for item in data[key]]
    except ValidationError as e:
        raise BibleError(f"{path} is not valid: " + "; ".join(problems_from(e))) from e


def _write(path: Path, key: str, records: Iterable[BaseModel]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_yaml({key: [to_plain(r) for r in records]}), encoding="utf-8")


# ── constants (series-wide) ────────────────────────────────────────────────

def constants_path(project: Project) -> Path:
    return project.root / "bible" / "constants.yaml"


def load_constants(project: Project) -> Constants:
    data = _load(constants_path(project))
    if not data:
        return Constants()
    try:
        return Constants.model_validate(data)
    except ValidationError as e:
        raise BibleError(f"{constants_path(project)} is not valid: " + "; ".join(problems_from(e))) from e


def save_constants(project: Project, constants: Constants) -> None:
    path = constants_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_yaml({"entities": [to_plain(e) for e in constants.entities],
                               "rules": [to_plain(r) for r in constants.rules]}), encoding="utf-8")


# ── tracks and timeline (series-wide files, entries are per book) ──────────

def load_tracks(project: Project) -> list[Track]:
    return _records(project.root / "bible" / "tracks.yaml", "tracks", Track)


def save_tracks(project: Project, tracks: list[Track]) -> None:
    _write(project.root / "bible" / "tracks.yaml", "tracks", tracks)


def load_timeline(project: Project) -> list[TimelineEntry]:
    return _records(project.root / "bible" / "timeline.yaml", "scenes", TimelineEntry)


def save_timeline(project: Project, entries: list[TimelineEntry]) -> None:
    _write(project.root / "bible" / "timeline.yaml", "scenes", entries)


# ── the book's structure ───────────────────────────────────────────────────

def acts_path(project: Project) -> Path:
    return project.book_dir / "acts.yaml"


def chapters_path(project: Project) -> Path:
    return project.book_dir / "chapters.yaml"


def scenes_path(project: Project) -> Path:
    return project.book_dir / "scenes.yaml"


def load_acts(project: Project) -> list[Act]:
    return _records(acts_path(project), "acts", Act)


def load_chapters(project: Project) -> list[Chapter]:
    return _records(chapters_path(project), "chapters", Chapter)


def load_scenes(project: Project) -> list[Scene]:
    return _records(scenes_path(project), "scenes", Scene)


def save_acts(project: Project, acts: list[Act]) -> None:
    _write(acts_path(project), "acts", acts)


def save_chapters(project: Project, chapters: list[Chapter]) -> None:
    _write(chapters_path(project), "chapters", chapters)


def save_scenes(project: Project, scenes: list[Scene]) -> None:
    _write(scenes_path(project), "scenes", scenes)


def rel(project: Project, path: Path) -> str:
    return str(path.relative_to(project.root))


# ── merging ────────────────────────────────────────────────────────────────

def upsert_plan(base: list[Track], incoming: list[Track]) -> list[Track]:
    """Add incoming tracks, or add/replace plan entries (matched by `from`) on tracks that exist.

    Re-running a layer therefore gives the same result. A track keeps its entity: a
    conflicting entity is an error, not a silent change.
    """
    from .positions import parse_position  # local import: positions has no dependencies

    by_id = {t.id: t.model_copy(deep=True) for t in base}
    order = [t.id for t in base]
    for t in incoming:
        if t.id not in by_id:
            by_id[t.id] = t.model_copy(deep=True)
            order.append(t.id)
            continue
        existing = by_id[t.id]
        if existing.entity != t.entity:
            raise BibleError(f"track '{t.id}' belongs to '{existing.entity}', not '{t.entity}'")
        entries = {e.from_: e for e in existing.plan}
        for e in t.plan:
            entries[e.from_] = e
        existing.plan = sorted(entries.values(), key=lambda e: parse_position(e.from_).key)
    return [by_id[i] for i in order]


# ── the story-event ledger ───────────────────────────────────────────────────

def ledger_path(project: Project) -> Path:
    return project.book_dir / "ledger.yaml"


def load_ledger(project: Project) -> Ledger | None:
    data = _load(ledger_path(project))
    if not data:
        return None
    try:
        return Ledger.model_validate(data)
    except ValidationError as e:
        raise BibleError(f"{ledger_path(project)} is not valid: " + "; ".join(problems_from(e))) from e


def save_ledger(project: Project, ledger: Ledger) -> None:
    path = ledger_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_yaml(to_plain(ledger)), encoding="utf-8")
