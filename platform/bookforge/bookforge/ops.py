"""The multi-step operations shared by the command line and the HTTP service.

Each takes an open project and the clients it needs (so tests and the service can pass their own) and
returns plain data; printing and HTTP formatting stay with the caller.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import steering, assemble as assembly, bench as benchmarks, changes as change_requests, report as morning_report, stale as staleness, vcs
from .bible import store as bible_store
from .constants import LAYER_ORDER, REDO_NOTE
from .errors import BookforgeError
from .layers import HANDLERS
from .layers.runner import RunSummary, StepContext, run as run_layers
from .llm import LLMClient
from .project import Project
from .state import Checkpoint
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


# ── writing a planning layer again ────────────────────────────────────────────

REDOABLE = LAYER_ORDER[:-1]  # everything before the prose; written scenes are redone with `rewrite`


def _prose_exists(project: Project) -> bool:
    return any(project.book_dir.glob("scenes/*/*/final.md")) or any(project.book_dir.glob("scenes/*/*/revised.md"))


def redo_plan(project: Project, layer: str) -> list[str]:
    """The layers `redo` would reset along with this one: those after it that are not still pending."""
    if layer not in REDOABLE:
        raise BookforgeError(f"only planning layers can be redone ({', '.join(REDOABLE)}); written scenes are redone with `rewrite`")
    return [l for l in LAYER_ORDER[LAYER_ORDER.index(layer) + 1:] if l != "prose" and project.state.layers[l].status != "pending"]


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
    for cp in ("direction", "structure"):
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


def decide_change(project: Project, cr_id: str, approve: bool) -> change_requests.ChangeRequest:
    decided = change_requests.approve(project, cr_id) if approve else change_requests.reject(project, cr_id)
    if project.config.git.commit_each_step:
        vcs.commit(project.root, f"{project.book}: change request {decided.id} {decided.status}")
    return decided


# ── rewriting scenes ──────────────────────────────────────────────────────────

SCENE_FILES = ("final.md", "revised.md", "summary.md", "review.json", "extracted.yaml", "deps.yaml")


def rewrite_scenes(project: Project, targets: list[str], force: bool = False) -> dict:
    """Throw away the text of scenes (or a whole chapter) so the next `run` writes them again.

    Deleting files is not enough: an accepted scene is skipped whatever is on disk. This puts the scenes back to pending
    (and the prose layer back to unfinished), removes their drafts, text, summary, review and what was observed from
    them. Everything stays in Git history. Text you wrote yourself is not discarded unless `force`.
    """
    from . import scenefiles
    from .state import Item

    scenes = bible_store.load_scenes(project) if bible_store.scenes_path(project).exists() else []
    chosen: list[str] = []
    for t in targets:
        found = [s.id for s in scenes if s.id == t or s.chapter == t]
        if not found:
            raise BookforgeError(f"'{t}' is not a scene or chapter of this book (try b1.ch01.s1 or b1.ch01)")
        chosen += [i for i in found if i not in chosen]
    kept: list[str] = []
    reset: list[str] = []
    for sid in chosen:
        review = scenefiles.read(scenefiles.review_path(project, sid))
        try:
            own = bool(review) and json.loads(review).get("source") == "adopted"
        except ValueError:
            own = False
        if own and not force:
            kept.append(sid)
            continue
        d = scenefiles.scene_dir(project, sid)
        for f in list(d.glob("draft-*.md")) + [d / n for n in SCENE_FILES]:
            f.unlink(missing_ok=True)
        item = project.state.items.setdefault(sid, Item())
        item.status, item.note, item.updated = "pending", None, now_stamp()
        reset.append(sid)
    if reset:
        tracks = bible_store.load_tracks(project)
        for t in tracks:
            t.observed = [o for o in t.observed if o.get("at") not in reset]
        bible_store.save_tracks(project, tracks)
        if project.state.layers["prose"].status == "accepted":
            project.state.layers["prose"].status = "drafted"
        project.save_state()
        if project.config.git.commit_each_step:
            vcs.commit(project.root, f"{project.book}: {len(reset)} scene(s) reset for rewriting: {', '.join(reset[:6])}{'...' if len(reset) > 6 else ''}")
    return {"reset": reset, "kept": kept}
