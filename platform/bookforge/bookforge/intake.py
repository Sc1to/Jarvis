"""Intake: a plan edit that brings in a new development is registered in the story-event ledger, so the ledger-based protections cover it.

A hand-written beat that adds something that happens ("the sheriff calls in the loan") is accepted as plain text, but the ledger does not know it:
the once-only, order, need-to-know and retell/overreach checks cannot protect what they cannot see. This finds such beats after a scenes edit is saved
and offers to register each as a minor complication of the chapter's own event (a derived event: weight 1, placed right after its parent, no renumbering,
no cascade). Heavy developments are not handled here: they change the plan's shape and go through Redo of the ledger.

Detection is lexical (no model): an ADDED beat whose content words share nothing meaningful with any event of its chapter. You decide; nothing is
registered without the button.
"""
import yaml

from . import vcs
from .bible import store
from .bible.models import StoryEvent
from .bible.validate import merge_derived
from .errors import BookforgeError
from .project import Project
from .validators.ledger import MAX_DERIVED_PER_PARENT
from .validators.text import content_stems, dice

MIN_BEAT_WORDS = 8
SAME_AS_AN_EVENT = 0.18  # dice overlap of content stems with an event of the chapter above which the beat is just that event told in detail


class IntakeError(BookforgeError):
    pass


def _beats_by_scene(text: str) -> dict[str, list[str]]:
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError:
        return {}
    return {str(s.get("id")): [str(b) for b in s.get("beats") or []] for s in data.get("scenes", []) if isinstance(s, dict)}


def new_event_candidates(project: Project, old_text: str, new_text: str) -> list[dict]:
    """Beats ADDED by a scenes edit that no event of their chapter accounts for: [{scene, chapter, beat, parents, parent, text}]."""
    ledger = store.active_ledger(project)
    if ledger is None or not store.chapters_path(project).exists():
        return []
    chapters = {c.id: c for c in store.load_chapters(project)}
    scenes = {s.id: s for s in store.load_scenes(project)} if store.scenes_path(project).exists() else {}
    old = _beats_by_scene(old_text)
    by_id = {e.id: e for e in ledger.events}
    out: list[dict] = []
    for sid, beats in _beats_by_scene(new_text).items():
        sc = scenes.get(sid)
        ch = chapters.get(sc.chapter) if sc else None
        if ch is None:
            continue
        mine = [x for x in list(ch.events_covered) + list(ch.events_continued) if x in by_id]
        own = [by_id[x] for x in mine] + [e for e in ledger.events if e.parent in mine]
        parents = [x for x in ch.events_covered if x in by_id and not by_id[x].parent]
        if not parents:
            continue
        for beat in beats:
            if beat in (old.get(sid) or []) or len(beat.split()) < MIN_BEAT_WORDS:
                continue
            stems = set(content_stems(beat))
            best = max((dice(stems, set(content_stems(e.text + " " + e.excerpt))) for e in own), default=0.0)
            if best < SAME_AS_AN_EVENT:
                out.append({"scene": sid, "chapter": ch.id, "beat": beat, "parents": parents, "parent": parents[-1], "text": beat.rstrip(".")[:200]})
    return out


def _next_id(events: list, parent: str) -> str:
    taken = {e.id for e in events}
    n = 1
    while f"{parent}.{n}" in taken:
        n += 1
    return f"{parent}.{n}"


def register_events(project: Project, items: list[dict]) -> list[str]:
    """Add each item ({scene, parent, text}) to the ledger as a minor complication of `parent`, tell the chapter and the scene about it. All or nothing.

    The new event is derived (weight 1, kind event, after its parent), which is the established way to add a small development inside a chapter without renumbering
    anything; the ledger, chapter and scene checks then run on the result and the change is rolled back if they find anything new. Returns the new ids."""
    from .documents import _ledger_problems
    from .layers import structure
    ledger = store.active_ledger(project)
    if ledger is None:
        raise IntakeError("this book has no story-event ledger")
    paths = [store.ledger_path(project), store.chapters_path(project), store.scenes_path(project)]
    before = structure.validate_chapters_file(project) + structure.validate_scenes_file(project)
    ledger_before = _ledger_problems(project, store.ledger_path(project).read_text(encoding="utf-8"))
    chapters = store.load_chapters(project)
    scenes = store.load_scenes(project)
    events = list(ledger.events)
    added: list[str] = []
    for it in items:
        parent = str(it["parent"])
        by_id = {e.id: e for e in events}
        if parent not in by_id or by_id[parent].parent:
            raise IntakeError(f"'{parent}' is not an event of the story that a complication can belong to")
        if sum(1 for e in events if e.parent == parent) >= MAX_DERIVED_PER_PARENT:
            raise IntakeError(f"{parent} already has {MAX_DERIVED_PER_PARENT} minor complications; this development is bigger than a complication: redo the ledger instead")
        text = " ".join(str(it["text"]).split())
        if not text:
            raise IntakeError("the event needs a sentence saying what happens")
        ev = StoryEvent(id=_next_id(events, parent), text=text, once_only=True, after=[parent], kind="event", weight=1, source="derived", parent=parent)
        events = merge_derived(events, [ev])
        sc = next((s for s in scenes if s.id == it["scene"]), None)
        ch = next((c for c in chapters if c.id == (sc.chapter if sc else it.get("chapter"))), None)
        if sc is None or ch is None:
            raise IntakeError(f"no scene '{it['scene']}'")
        for target in (ch.events_covered, sc.events):
            target.insert(target.index(parent) + 1 if parent in target else len(target), ev.id)
        added.append(ev.id)
    with store.transaction(paths):
        store.save_ledger(project, ledger.model_copy(update={"events": events}))
        store.save_chapters(project, chapters)
        store.save_scenes(project, scenes)
        new = [p for p in structure.validate_chapters_file(project) + structure.validate_scenes_file(project) if p not in before]
        new += [p for p in _ledger_problems(project, store.ledger_path(project).read_text(encoding="utf-8")) if p not in ledger_before]
        if new:
            raise IntakeError("registering these would leave the plan inconsistent: " + "; ".join(new[:4]))
    if project.config.git.commit_each_step:
        vcs.commit(project.root, f"{project.book}: you registered {len(added)} development(s) as story events ({', '.join(added)})", paths)
    return added
