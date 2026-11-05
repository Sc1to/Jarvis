"""Arc views: the tension curve (with editing that shows its consequence first) and the thread map.

Tension is the 1-10 field of each chapter in `chapters.yaml`. Changing it changes the chapter's fingerprint, so the
scenes written from it go stale; `set_tension` first reports how many scenes that touches and only writes when told to.
Threads (`workbench/threads.yaml`) link a setup scene to its payoff scene; a setup without a payoff is marked.
Character arc lanes (an inner state as a line across chapters) are not built: the bible holds no numeric inner state.
"""

import yaml

from . import scenefiles, vcs
from .bible import store
from .bible.positions import parse_position
from .errors import BookforgeError
from .project import Project
from .state import Item

FLAT_RUN = 4  # chapters in a row within one point of each other count as a flat stretch


class ArcError(BookforgeError):
    pass


def tension(project: Project) -> dict:
    chapters = store.load_chapters(project) if store.chapters_path(project).exists() else []
    scenes = store.load_scenes(project) if store.scenes_path(project).exists() else []
    acts = {a.id: a.title for a in (store.load_acts(project) if store.acts_path(project).exists() else [])}
    rows = []
    for c in chapters:
        mine = [s for s in scenes if s.chapter == c.id]
        written = sum(1 for s in mine if project.state.items.get(s.id, Item()).status in ("accepted", "stale"))
        rows.append({"id": c.id, "title": c.title, "act": acts.get(c.act, c.act), "tension": c.tension, "scenes": len(mine), "written": written})
    notes: list[str] = []
    values = [r["tension"] for r in rows]
    if rows:
        peak = max(values)
        if peak <= 7:
            notes.append(f"no climax: the highest planned tension is {peak}")
        else:
            first_peak = values.index(peak)
            if first_peak < 2 * len(values) // 3:
                notes.append(f"the peak ({rows[first_peak]['id']}, {peak}) comes before the last third of the book")
        i = 0
        while i < len(values):
            j = i
            while j + 1 < len(values) and max(values[i:j + 2]) - min(values[i:j + 2]) <= 1:
                j += 1
            if j - i + 1 >= FLAT_RUN:
                notes.append(f"flat stretch: {rows[i]['id']} to {rows[j]['id']} stay within one point of each other")
            i = j + 1
    return {"chapters": rows, "notes": notes}


def set_tension(project: Project, chapter_id: str, value: int, apply: bool = False) -> dict:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 10:
        raise ArcError("tension must be a whole number from 1 to 10")
    chapters = store.load_chapters(project)
    chapter = next((c for c in chapters if c.id == chapter_id), None)
    if chapter is None:
        raise ArcError(f"no chapter '{chapter_id}'")
    scenes = [s for s in store.load_scenes(project) if s.chapter == chapter_id]
    written = [s.id for s in scenes if project.state.items.get(s.id, Item()).status in ("accepted", "stale")]
    result = {"chapter": chapter_id, "from": chapter.tension, "to": value, "scenes": [s.id for s in scenes], "written": written,
              "consequence": f"affects {len(scenes)} scene(s), {len(written)} of them written (they go stale and are re-checked)" if value != chapter.tension else "no change",
              "applied": False}
    if apply and value != chapter.tension:
        chapter.tension = value
        store.save_chapters(project, chapters)
        if project.config.git.commit_each_step:
            vcs.commit(project.root, f"{project.book}: {chapter_id} tension {result['from']} -> {value} (workbench)", [str(store.chapters_path(project).relative_to(project.root))])
        result["applied"] = True
    return result


# ── threads ──────────────────────────────────────────────────────────────────

def _threads_path(project: Project):
    return project.root / "workbench" / "threads.yaml"


def load_threads(project: Project) -> list[dict]:
    try:
        data = yaml.safe_load(_threads_path(project).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return []
    return [t for t in data.get("threads", []) if isinstance(t, dict) and t.get("id")]


def _save_threads(project: Project, threads: list[dict]) -> None:
    p = _threads_path(project)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump({"threads": threads}, sort_keys=False, allow_unicode=True), encoding="utf-8")


def thread_map(project: Project) -> dict:
    scenes = [s.id for s in store.load_scenes(project)] if store.scenes_path(project).exists() else []
    index = {sid: i for i, sid in enumerate(scenes)}
    out = []
    for t in load_threads(project):
        setup, payoff = t.get("setup", ""), t.get("payoff", "") or ""
        problem = None
        if setup not in index:
            problem = "the setup scene does not exist"
        elif not payoff:
            problem = "no payoff yet"
        elif payoff not in index:
            problem = "the payoff scene does not exist"
        elif index[payoff] <= index[setup]:
            problem = "the payoff comes before (or in) the setup scene"
        out.append({"id": t["id"], "note": t.get("note", ""), "setup": setup, "payoff": payoff, "problem": problem,
                    "setup_at": index.get(setup), "payoff_at": index.get(payoff) if payoff else None})
    return {"scenes": scenes, "threads": out, "unpaid": sum(1 for t in out if t["problem"] == "no payoff yet")}


def upsert_thread(project: Project, thread_id: str, note: str, setup: str, payoff: str = "") -> None:
    import re
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,40}", thread_id or ""):
        raise ArcError("a thread id is lowercase letters, digits and '-'")
    ids = {s.id for s in store.load_scenes(project)}
    for label, value in (("setup", setup), ("payoff", payoff)):
        if value:
            try:
                parse_position(value)
            except ValueError as e:
                raise ArcError(f"{label}: {e}") from e
            if value not in ids:
                raise ArcError(f"{label}: no scene '{value}'")
    if not setup:
        raise ArcError("a thread needs a setup scene")
    threads = [t for t in load_threads(project) if t["id"] != thread_id] + [{"id": thread_id, "note": note, "setup": setup, "payoff": payoff}]
    _save_threads(project, sorted(threads, key=lambda t: t["id"]))


def delete_thread(project: Project, thread_id: str) -> None:
    threads = load_threads(project)
    if not any(t["id"] == thread_id for t in threads):
        raise ArcError(f"no thread '{thread_id}'")
    _save_threads(project, [t for t in threads if t["id"] != thread_id])
