"""Story milestones the AI works out by itself: "body found" at ch 2, "riddle solved" at ch 19.

One model call reads the chapter plan and, for chapters whose scenes are all written, the scene summaries (what really
happens on the page), and answers with a short list of turning points, each pinned to one chapter. The list is kept in
`workbench/milestones.yaml` with a fingerprint of what it was made from, so a run only asks again when the plan or the
written text changed. Each milestone says whether it comes from the plan or from written text. Notes for the author:
nothing here is checked against the prose and nothing goes stale.
"""

import hashlib
import json
from datetime import datetime, timezone

import yaml

from . import scenefiles
from .bible import store
from .errors import BookforgeError
from .project import Project
from .qc.support import ask_json
from .state import Item

MIN_COUNT, MAX_COUNT = 4, 12
SUMMARY_CHARS = 500  # per scene summary, so a long chapter does not drown the others


def path(project: Project):
    return project.root / "workbench" / "milestones.yaml"


def _inputs(project: Project) -> list[dict]:
    """One entry per chapter: its plan, and the scene summaries when every scene of it is written."""
    chapters = store.load_chapters(project) if store.chapters_path(project).exists() else []
    scenes = store.load_scenes(project) if store.scenes_path(project).exists() else []
    out = []
    for c in chapters:
        mine = [s for s in scenes if s.chapter == c.id]
        done = bool(mine) and all(project.state.items.get(s.id, Item()).status in ("accepted", "stale") for s in mine)
        summaries = []
        if done:
            for s in mine:
                text = (scenefiles.read(scenefiles.summary_path(project, s.id)) or "").strip()
                if text:
                    summaries.append(text[:SUMMARY_CHARS])
        written = bool(summaries)
        out.append({"id": c.id, "title": c.title, "plan": c.summary, "written": written, "summaries": summaries})
    return out


def _fingerprint(chapters: list[dict]) -> str:
    return hashlib.sha256(json.dumps(chapters, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def load(project: Project) -> dict:
    try:
        data = yaml.safe_load(path(project).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _chapters_text(chapters: list[dict]) -> str:
    blocks = []
    for c in chapters:
        head = f"{c['id']} {c['title']} [{'written' if c['written'] else 'planned'}]"
        body = "\n".join(f"- {s}" for s in c["summaries"]) if c["written"] else c["plan"]
        blocks.append(f"{head}\n{body}")
    return "\n\n".join(blocks)


def _previous_text(project: Project) -> str:
    items = load(project).get("items") or []
    return "\n".join(f"- {i['chapter']}: {i['label']}" for i in items) or "(nothing yet)"


def refresh(ctx, force: bool = False) -> dict:
    """Ask for the milestones again unless the plan and written text are the same as last time. Returns the saved record.

    Raises BookforgeError when the model cannot give a usable list; the old list is then left as it was."""
    project = ctx.project
    chapters = _inputs(project)
    if not chapters:
        raise BookforgeError("there are no chapters yet: plan the chapters first")
    fp = _fingerprint(chapters)
    old = load(project)
    if not force and old.get("fingerprint") == fp and old.get("items"):
        return old
    ids = {c["id"] for c in chapters}
    written = {c["id"] for c in chapters if c["written"]}
    low, high = min(MIN_COUNT, len(chapters)), MAX_COUNT

    def check(data: dict) -> list[str]:
        items = data.get("milestones")
        if not isinstance(items, list):
            return ['"milestones" must be a list']
        problems = []
        labels = set()
        for i, m in enumerate(items):
            if not isinstance(m, dict) or m.get("chapter") not in ids:
                problems.append(f"milestones[{i}] needs a 'chapter' that is one of the chapter ids above")
            elif not str(m.get("label", "")).strip() or len(str(m["label"]).strip()) > 80:
                problems.append(f"milestones[{i}] needs a short 'label'")
            elif str(m["label"]).strip().lower() in labels:
                problems.append(f"milestones[{i}] repeats a label")
            else:
                labels.add(str(m["label"]).strip().lower())
        if not problems and not low <= len(items) <= high:
            problems.append(f"give between {low} and {high} milestones")
        return problems

    data = ask_json(ctx, "story milestones", "critic", "milestones", check, max_tokens=900,
                    book_north_star=(scenefiles.read(project.book_dir / "north-star.md") or "").strip()[:2500] or "(none yet)",
                    chapters=_chapters_text(chapters), previous=_previous_text(project), min_count=str(low), max_count=str(high))
    order = {c["id"]: i for i, c in enumerate(chapters)}
    items = sorted(({"chapter": m["chapter"], "label": str(m["label"]).strip(), "basis": "written" if m["chapter"] in written else "plan"}
                    for m in data["milestones"]), key=lambda m: order[m["chapter"]])
    record = {"fingerprint": fp, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "items": items}
    p = path(project)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(record, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return record


def refresh_quietly(ctx) -> str | None:
    """For the end of a run: never raises and never blocks it. Returns why nothing was made, or None."""
    try:
        refresh(ctx)
    except BookforgeError as e:
        return str(e)
    except Exception as e:  # a model that is down or a fake that cannot answer must not fail the run
        return str(e)
    return None
