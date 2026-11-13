"""The multi-step operations shared by the command line and the HTTP service.

Each takes an open project and the clients it needs (so tests and the service can pass their own) and
returns plain data; printing and HTTP formatting stay with the caller.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import milestones, steering, assemble as assembly, bench as benchmarks, changes as change_requests, report as morning_report, stale as staleness, vcs
from .bible import store as bible_store
from .constants import LAYER_CHECKPOINTS, LAYER_ORDER, REDO_NOTE
from .errors import BookforgeError
from .layers import HANDLERS
from .layers.runner import RunSummary, StepContext, run as run_layers
from .llm import LLMClient
from .project import Project
from .state import Checkpoint, Item
from .research.search import WebClient

log = logging.getLogger("platform_bookforge.ops")


def now_stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


# ── run ───────────────────────────────────────────────────────────────────────

@dataclass
class PipelineOutcome:
    summary: RunSummary
    assembled: assembly.Assembly | None = None
    report_path: str | None = None
    report_error: str | None = None
    milestones_error: str | None = None  # why no milestones were made (never stops a run)


def resume_point(project: Project) -> dict | None:
    """Where the next Run continues, for the status line: the first layer that is not accepted and, in the prose layer, the scene it
    starts with (an interrupted scene first, then scenes still to do, flagged ones last; see layers.prose.order_for_run)."""
    from .layers.prose import order_for_run
    for layer in LAYER_ORDER:
        if project.state.layers[layer].status == "accepted":
            continue
        if layer != "prose" or not bible_store.scenes_path(project).exists():
            return {"layer": layer, "scene": None, "reason": "next", "accepted": 0, "flagged": 0, "todo": 0, "total": 0}
        scenes = bible_store.load_scenes(project)
        chapters = bible_store.load_chapters(project)
        status = {s.id: (project.state.items.get(s.id).status if project.state.items.get(s.id) else "pending") for s in scenes}
        first = chapters[0].id if chapters else ""
        order = [s for s in order_for_run(project, scenes, project.state.checkpoints["voice"].status == "approved", first)
                 if status[s.id] not in ("accepted", "stale")]
        nxt = order[0] if order else None
        reason = {"drafted": "interrupted", "flagged": "flagged"}.get(status[nxt.id], "next") if nxt else "next"
        n = lambda *k: sum(1 for v in status.values() if v in k)  # noqa: E731
        return {"layer": layer, "scene": nxt.id if nxt else None, "reason": reason, "accepted": n("accepted"), "flagged": n("flagged"),
                "todo": n("pending", "drafted", "checked"), "total": len(scenes)}
    return None


def resume_text(point: dict | None) -> str:
    if not point:
        return "Nothing left to run."
    if point["scene"] is None:
        return f"The next Run continues with the {point['layer']} layer."
    why = {"interrupted": " (interrupted: its drafts are kept)", "flagged": " (flagged: only flagged scenes are left)"}.get(point["reason"], "")
    return (f"The next Run continues at {point['scene']}{why}: {point['accepted']} of {point['total']} scenes accepted, "
            f"{point['flagged']} flagged, {point['todo']} to do.")


def run_pipeline(project: Project, llm: LLMClient | None, web: WebClient | None, until: str | None = None,
                 handlers: dict | None = None) -> PipelineOutcome:
    """Run the layers; if every one is accepted assemble the book; always write the morning report."""
    started = now_stamp()
    summary = run_layers(project, llm=llm, handlers=HANDLERS if handlers is None else handlers, until=until, web=web)
    out = PipelineOutcome(summary)
    if summary.stopped == "complete":
        try:
            out.assembled = assembly.assemble(project)
        except BookforgeError as e:
            summary.detail = f"not assembled: {e}"
    if llm is not None:
        out.milestones_error = milestones.refresh_quietly(StepContext(project=project, layer="prose", llm=llm))
    try:
        out.report_path = morning_report.write_report(project, since=started)
        if project.config.git.commit_each_step:
            vcs.commit(project.root, f"{project.book}: morning report", [out.report_path])
    except (BookforgeError, OSError) as e:
        out.report_error = str(e)
    return out


# ── stale ─────────────────────────────────────────────────────────────────────

@dataclass
class StalePass:
    report: staleness.StaleReport
    fixes: list[staleness.FixResult] = field(default_factory=list)


def stale_pass(project: Project, llm: LLMClient | None = None, fix: bool = False, accept: list[str] | None = None,
               only: set[str] | None = None) -> StalePass:
    """Accept what the author says is fine, optionally fix, then rescan, sync state.json and commit it."""
    scene_ids = {s.id for s in bible_store.load_scenes(project)} if bible_store.scenes_path(project).exists() else set()
    for target in accept or []:
        if target in scene_ids:
            staleness.accept_as_is(project, target)
            staleness.record_plan(project, {target})  # also clears "its chapter changed" for this scene
        elif target in {c.id for c in bible_store.load_chapters(project)}:
            staleness.record_plan(project, {target})
        else:
            raise BookforgeError(f"'{target}' is not a scene or chapter of this book")
    fixes = staleness.fix_all(StepContext(project=project, layer="prose", llm=llm), only) if fix else []
    report = staleness.scan(project)
    staleness.sync_status(project, report)
    if project.config.git.commit_each_step:
        keep = [project.state_path, staleness.plan_deps_path(project)]
        vcs.commit(project.root, f"{project.book}: stale scan", [str(f.relative_to(project.root)) for f in keep if f.exists()])
    return StalePass(report, fixes)


# ── bench ─────────────────────────────────────────────────────────────────────

@dataclass
class BenchOutcome:
    run: benchmarks.BenchRun
    comparison: dict | None
    accepted: bool
    accept_refused: bool = False  # --accept was asked for but the run loses


def bench_pass(project: Project, llm: LLMClient | None, only: list[str] | None = None, accept: bool = False,
               force: bool = False, judge: bool = True) -> BenchOutcome:
    ctx = StepContext(project=project, layer="prose", llm=llm)
    baseline = benchmarks.accepted_run(project)
    run = benchmarks.run_bench(ctx, only)
    comparison = benchmarks.compare(ctx, run, baseline, judge=judge) if baseline else None
    accepted = accept and (comparison is None or comparison["ships"] or force)
    if accepted:
        benchmarks.accept(project, run)
    benchmarks.commit(project, run, accepted)
    return BenchOutcome(run, comparison, accepted, accept_refused=accept and not accepted)


# ── checkpoints and change requests ───────────────────────────────────────────

def approve_checkpoint(project: Project, checkpoint: str) -> None:
    """Approve a waiting checkpoint. The approved version includes any edits made while reviewing."""
    project.state.approve_checkpoint(checkpoint)
    project.save_state()
    if checkpoint == "structure":
        staleness.record_plan(project)  # from now on, a changed act or chapter makes what was planned from it stale
    message = f"{project.book}: {checkpoint} approved"
    if project.config.git.commit_each_step or project.config.git.tag_checkpoints:
        vcs.commit(project.root, message)
    if project.config.git.tag_checkpoints:
        vcs.tag(project.root, f"{project.book}-{checkpoint}-approved", message)


def list_needs(project: Project) -> list:
    """Every need of the series and the open book: (scope, Need) pairs, series first."""
    from .research.notes import stores_for
    return [(scope, n) for scope, store in stores_for(project).items() for n in store.needs()]


def decide_need(project: Project, need_id: str, approve: bool | None = None, stance: str | None = None, rule: str | None = None,
                applies_to: list[str] | None = None):
    """Approve or reject a proposed rule, assumption or deviation, and/or change its stance or its text.

    Changing the stance or the text without saying approve or reject puts the need back to 'proposed': an edit is not an
    approval. A stance that needs a lookup has no facts until the lookup is run (it is not run from here).
    """
    from .research.notes import MAX_RULE_CHARS_STORED, STANCES, stores_for
    store = next((s for s in stores_for(project).values() if any(n.id == need_id for n in s.needs())), None)
    if store is None:
        raise BookforgeError(f"no need '{need_id}' (see `needs`)")
    need = next(n for n in store.needs() if n.id == need_id)
    if stance is not None:
        stance = stance.strip().casefold()
        if stance not in STANCES:
            raise BookforgeError(f"stance must be one of: {', '.join(STANCES)}")
        need.stance = stance
    if rule is not None:
        need.rule = " ".join(rule.split())[:MAX_RULE_CHARS_STORED]
    if applies_to is not None:  # [] = the whole book
        from .research.notes import canonical_places
        try:
            need.applies_to = canonical_places(applies_to)
        except ValueError as e:
            raise BookforgeError(str(e)) from None
    if need.stance == "invent" and not need.rule:
        raise BookforgeError("an invented thing needs the rule you decide on (--rule \"...\")")
    if approve is True:
        need.status, need.decided_by = "approved", "author"
    elif approve is False:
        need.status, need.decided_by = "rejected", "author"
    elif stance is not None or rule is not None:
        need.status, need.decided_by = "proposed", ""  # (changing only where it applies does not reopen a decision)
    store.save_need(need)
    store.write_needs_md()
    if project.config.git.commit_each_step:
        vcs.commit(project.root, f"{project.book}: need {need.id} {need.status} ({need.stance})")
    return need


# ── what the author says about a scene's findings ────────────────────────────

FINDING_ACTIONS = ("dismiss", "instruct", "clear")


def decide_finding(project: Project, scene_id: str, question: str, action: str, text: str = "") -> dict:
    """Dismiss a finding of the continuity check as a false alarm, give the writer an instruction about it, or take either back.

    Applied the next time the scene is run: a dismissed finding is not asked about again for this scene, and an instruction is
    added to the problem when that finding is revised. Returns the author's notes for the scene.
    """
    from . import scenefiles
    from .qc import scene_notes
    if action not in FINDING_ACTIONS:
        raise BookforgeError(f"action must be one of: {', '.join(FINDING_ACTIONS)}")
    scenes = bible_store.load_scenes(project) if bible_store.scenes_path(project).exists() else []
    if not any(s.id == scene_id for s in scenes):
        raise BookforgeError(f"'{scene_id}' is not a scene of this book")
    raw = scenefiles.read(scenefiles.review_path(project, scene_id))
    try:
        review = json.loads(raw) if raw else {}
    except ValueError:
        review = {}
    cont = review.get("continuity") or {}
    known = {f.get("question") for f in cont.get("flags") or []} | {u.get("question") for u in cont.get("unsure") or []}
    notes = scene_notes.read(project, scene_id)
    known |= set(notes["dismissed"]) | set(notes["instructions"])
    if question not in known:
        raise BookforgeError("that is not one of this scene's findings (see its review)")
    if action == "dismiss":
        scene_notes.dismiss(project, scene_id, question)
    elif action == "instruct":
        if not text.strip():
            raise BookforgeError("write what the writer should do about it")
        scene_notes.instruct(project, scene_id, question, text)
    else:
        scene_notes.clear(project, scene_id, question)
    if project.config.git.commit_each_step:
        vcs.commit(project.root, f"{scene_id}: you {'cleared a note on' if action == 'clear' else action + 'ed'} a finding", [scenefiles.scene_dir(project, scene_id)])
    return scene_notes.read(project, scene_id)


def _flagged_review(project: Project, scene_id: str) -> dict:
    from . import scenefiles
    scenes = bible_store.load_scenes(project) if bible_store.scenes_path(project).exists() else []
    if not any(s.id == scene_id for s in scenes):
        raise BookforgeError(f"'{scene_id}' is not a scene of this book")
    raw = scenefiles.read(scenefiles.review_path(project, scene_id))
    try:
        return json.loads(raw) if raw else {}
    except ValueError:
        return {}


def flag_reasons(project: Project, scene_id: str) -> list[dict]:
    """Every reason a flagged scene is flagged, each as {key, kind (mechanical|continuity|critic), message, accepted, note}.

    Each one can be accepted on its own; the scene goes on once every reason is fixed or accepted. A scene whose writer reply was
    cut off has no text and so no reasons to accept."""
    from .qc import scene_notes
    review = _flagged_review(project, scene_id)
    accepted = scene_notes.read(project, scene_id)["accepted"]
    out = []
    for item in review.get("reason_items") or []:
        a = accepted.get(item["key"])
        out.append({**item, "accepted": a is not None, "note": a["note"] if a else ""})
    return out


def accept_reason(project: Project, scene_id: str, key: str, note: str = "", llm: LLMClient | None = None) -> dict:
    """Accept one reason a scene is flagged: the text is kept as it is and this reason no longer blocks it.

    Once every reason is accepted the scene is settled at once (accepted, summary, extraction; `llm` writes those, else the plan
    stands in for the summary). While some reason is still open the others are revised or checked on the next run. Returns the
    reason, with `scene_status`.
    """
    from . import scenefiles
    from .qc import scene_notes
    if project.state.items.get(scene_id, Item()).status != "flagged":
        raise BookforgeError(f"{scene_id} is not flagged")
    reasons = flag_reasons(project, scene_id)
    found = next((r for r in reasons if r["key"] == key), None)
    if found is None:
        if not reasons:
            raise BookforgeError("this scene has no text to accept (see its note); run it again, or write the scene yourself")
        raise BookforgeError("that is not one of this scene's reasons (see its review)")
    scene_notes.accept(project, scene_id, key, found["message"], note)
    if project.config.git.commit_each_step:
        vcs.commit(project.root, f"{scene_id}: you accepted a reason it was flagged: {found['message']}"[:200], [scenefiles.scene_dir(project, scene_id)])
    if all(r["accepted"] or r["key"] == key for r in reasons):
        from .layers.prose import finish_accepted
        scenes = bible_store.load_scenes(project)
        scene = next(s for s in scenes if s.id == scene_id)
        finish_accepted(StepContext(project=project, layer="prose", llm=llm), scene, scenes)
    return {**found, "accepted": True, "note": " ".join(note.split()), "scene_status": project.state.items[scene_id].status}


def undo_accept_reason(project: Project, scene_id: str, key: str) -> None:
    from .qc import scene_notes
    _flagged_review(project, scene_id)
    scene_notes.unaccept(project, scene_id, key)


# ── writing a planning layer again ────────────────────────────────────────────

REDOABLE = LAYER_ORDER[:-1]  # everything before the prose; written scenes are redone with `rewrite`


def _prose_exists(project: Project) -> bool:
    return any(project.book_dir.glob("scenes/*/*/final.md")) or any(project.book_dir.glob("scenes/*/*/revised.md"))


def redo_plan(project: Project, layer: str) -> list[str]:
    """The layers `redo` would reset along with this one: those after it that are not still pending."""
    if layer not in REDOABLE:
        raise BookforgeError(f"only planning layers can be redone ({', '.join(REDOABLE)}); written scenes are redone with `rewrite`")
    def unused(name: str) -> bool:  # a ledger a book was planned without is not something to reset
        item = project.state.layers[name]
        return name == "ledger" and item.status == "accepted" and (item.note or "").startswith("not used")
    return [l for l in LAYER_ORDER[LAYER_ORDER.index(layer) + 1:] if l != "prose" and project.state.layers[l].status != "pending" and not unused(l)]


def redo_layer(project: Project, layer: str, note: str = "", cascade: bool = False) -> dict:
    """Have a planning layer written again, optionally steered by a note, and everything built on it.

    The layers after it that already ran were built on the old version; they are reset too, but only if `cascade` says
    so. Nothing is deleted: what is on disk now is committed first (so hand edits survive in Git history) and is
    overwritten when the layer runs again; a layer that is one document shows its previous version to the model with
    your note. Refused once scenes have been written (use `rewrite`), because re-planning would orphan them.
    The checkpoints these layers belong to go back to pending, so you review the new version. The research those layers made
    (questions, facts, undecided needs, notes) is moved to `research/archive/` so they research from scratch; decisions you
    made yourself stay (see `archive_layers`).
    """
    from .layers.structure import _clean_work
    downstream = redo_plan(project, layer)
    if _prose_exists(project) or project.state.layers["prose"].status != "pending":
        raise BookforgeError("scenes have already been written; redoing the plan would orphan them. Rewrite or delete those scenes first (`rewrite`)")
    if downstream and not cascade:
        raise BookforgeError(f"redoing '{layer}' also resets {', '.join(downstream)}, which were built on it. Confirm that (--cascade) or redo a later layer instead")
    reset = [layer] + downstream
    if project.config.git.commit_each_step:
        vcs.commit(project.root, f"{project.book}: before redoing {layer} (everything as it was)")
    for l in reset:
        project.state.set_layer_status(l, "pending", REDO_NOTE)
        _clean_work(project, l)
    project.state.items = {}
    for cp in LAYER_CHECKPOINTS:
        if any(project.config.layers[l].checkpoint == cp for l in reset):
            project.state.checkpoints[cp] = Checkpoint()
    for l in reset:
        steering.clear(project, l)
    if note.strip():
        steering.write(project, layer, note)
    from .research.notes import archive_layers
    archived = archive_layers(project, reset, datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"))
    project.save_state()
    if project.config.git.commit_each_step:
        vcs.commit(project.root, f"{project.book}: redo {layer}" + (" with a note" if note.strip() else ""))
    return {"layer": layer, "reset": reset, "note": bool(note.strip()), "archived": archived}


def decide_change(project: Project, cr_id: str, approve: bool | None, dismiss: bool = False) -> change_requests.ChangeRequest:
    """Approve (the plan follows the prose), reject (the prose follows the plan) or dismiss (neither changes)."""
    if dismiss:
        decided = change_requests.dismiss(project, cr_id)
    else:
        decided = change_requests.approve(project, cr_id) if approve else change_requests.reject(project, cr_id)
    if project.config.git.commit_each_step:
        vcs.commit(project.root, f"{project.book}: change request {decided.id} {decided.status}")
    return decided


# ── rewriting scenes ──────────────────────────────────────────────────────────

SCENE_FILES = ("final.md", "revised.md", "summary.md", "review.json", "extracted.yaml", "deps.yaml")


def rewrite_plan(project: Project, targets: list[str], force: bool = False) -> dict:
    """What `rewrite_scenes` would do, without doing it: {"reset": [ids], "kept": [ids you wrote yourself], "by_status": {...}}.

    A target is a scene id, a chapter id, or `all` (or the book's id, like `b1`) for every scene of the book.
    """
    from . import scenefiles
    from .state import Item

    scenes = bible_store.load_scenes(project) if bible_store.scenes_path(project).exists() else []
    chosen: list[str] = []
    for t in targets:
        if t.strip().casefold() in ("all", project.book):
            found = [s.id for s in scenes]
        else:
            found = [s.id for s in scenes if s.id == t or s.chapter == t]
        if not found:
            raise BookforgeError(f"'{t}' is not a scene or chapter of this book (try b1.ch01.s1, b1.ch01 or all)")
        chosen += [i for i in found if i not in chosen]
    kept: list[str] = []
    reset: list[str] = []
    for sid in chosen:
        review = scenefiles.read(scenefiles.review_path(project, sid))
        try:
            own = bool(review) and json.loads(review).get("source") == "adopted"
        except ValueError:
            own = False
        (kept if own and not force else reset).append(sid)
    by_status: dict[str, int] = {}
    for sid in reset:
        status = project.state.items.get(sid, Item()).status
        by_status[status] = by_status.get(status, 0) + 1
    return {"reset": reset, "kept": kept, "by_status": by_status}


def rewrite_scenes(project: Project, targets: list[str], force: bool = False, reset_voice: bool = False) -> dict:
    """Throw away the text of scenes (a chapter, or `all`) so the next `run` writes them again.

    Deleting files is not enough: an accepted scene is skipped whatever is on disk. This puts the scenes back to pending
    (and the prose layer back to unfinished), removes their drafts, text, summary, review and what was observed from
    them. Everything stays in Git history. Text you wrote yourself is not discarded unless `force`. With `reset_voice`, and
    when the first chapter is among the scenes, the voice checkpoint goes back to pending: the next run writes chapter 1 only
    and waits for you to read it and approve the voice again.
    """
    from . import scenefiles
    from .state import Checkpoint, Item

    plan = rewrite_plan(project, targets, force)
    reset, kept = plan["reset"], plan["kept"]
    for sid in reset:
        d = scenefiles.scene_dir(project, sid)
        for f in list(d.glob("draft-*.md")) + [d / n for n in SCENE_FILES]:
            f.unlink(missing_ok=True)
        item = project.state.items.setdefault(sid, Item())
        item.status, item.note, item.updated = "pending", None, now_stamp()
    voice_reset = False
    if reset:
        tracks = bible_store.load_tracks(project)
        for t in tracks:
            t.observed = [o for o in t.observed if o.get("at") not in reset]
        bible_store.save_tracks(project, tracks)
        if project.state.layers["prose"].status == "accepted":
            project.state.layers["prose"].status = "drafted"
        chapters = bible_store.load_chapters(project) if bible_store.chapters_path(project).exists() else []
        first = chapters[0].id if chapters else None
        first_scenes = {s.id for s in bible_store.load_scenes(project) if s.chapter == first}
        if reset_voice and first_scenes & set(reset):
            project.state.checkpoints["voice"] = Checkpoint()
            voice_reset = True
        project.save_state()
        if project.config.git.commit_each_step:
            vcs.commit(project.root, f"{project.book}: {len(reset)} scene(s) reset for rewriting: {', '.join(reset[:6])}{'...' if len(reset) > 6 else ''}")
    return {"reset": reset, "kept": kept, "voice_reset": voice_reset}
