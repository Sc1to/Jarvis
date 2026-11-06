"""Staleness: what a change made out of date, and bringing it back up to date in escalating steps.

**Detection.** A scene's `deps.yaml` records what its prose was built from (fingerprints). Building the
briefing again gives the current fingerprints; a difference is a reason. For the planning layers a snapshot,
`books/<book>/plan-deps.yaml`, is taken when the structure checkpoint is approved: a chapter whose act has
changed since, and a scene whose chapter has changed, are out of date too. (A changed chapter changes the
`parent` fingerprint of its scenes' prose as well, so written scenes show up under both.)

**Fixing** (`stale --fix`), cheapest step first, scene by scene in book order:

1. *Re-check.* The mechanical checks, and (unless the only change is the style) the continuity questions, on
   the text as it is. Usually nothing is wrong: the fingerprints are refreshed and the scene stays accepted.
2. *Patch.* Only the passages that contradict the new version are rewritten, the same way the revision loop
   does it. The result is checked again. A new summary and extraction follow.
3. *Redraft.* When the scene's own plan changed, or a patch could not fix it: the scene is written again.

Text you wrote or adopted yourself is never patched or redrafted. If it no longer agrees, the scene is flagged
for you. A rejected change request is a reason of its own: the plan stands, so the passage is patched to agree.
"""

import json
import logging
from dataclasses import dataclass, field

import yaml

from . import changes, scenefiles
from .bible import store
from .bible.models import Scene
from .briefing import build_briefing
from .deps import Reason, diff, fingerprint, read_deps, write_deps
from .errors import BookforgeError, LayerError
from .layers.prose import _commit, _summarise, check_context, record_extraction, write_scene
from .layers.runner import StepContext
from .project import Project
from .qc.continuity import check_continuity
from .qc.mechanical import all_banned, check_scene
from .qc.revise import Flag, revise_text
from .qc.scene import _mechanical_flags
from .state import Item, now

log = logging.getLogger("platform_bookforge.stale")


# ── detection ─────────────────────────────────────────────────────────────────

@dataclass
class SceneStale:
    scene: str
    reasons: list[Reason] = field(default_factory=list)
    rejected: list[changes.ChangeRequest] = field(default_factory=list)

    @property
    def level(self) -> str:
        """The step to start with: redraft when the scene's own plan changed, else re-check (patch if a change was rejected)."""
        if any(r.key == "scene" for r in self.reasons):
            return "redraft"
        return "patch" if self.rejected else "recheck"

    @property
    def needs_continuity(self) -> bool:
        return bool(self.rejected) or any(r.key != "style" for r in self.reasons)

    def why(self) -> list[str]:
        return [r.text() for r in self.reasons] + [f"change request {c.id} rejected: the plan stands" for c in self.rejected]


@dataclass
class PlanStale:
    id: str
    kind: str  # chapter | scene
    reason: str


@dataclass
class StaleReport:
    scenes: list[SceneStale] = field(default_factory=list)
    plan: list[PlanStale] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)  # scenes that could not be checked

    @property
    def empty(self) -> bool:
        return not self.scenes and not self.plan


def scan_scene(project: Project, scene_id: str, rejected: dict[str, list] | None = None) -> SceneStale | None:
    """Why a written scene is out of date, or None if it is not. Raises BookforgeError if it cannot be checked."""
    item = project.state.items.get(scene_id)
    if item is None or item.status not in ("accepted", "stale"):
        return None
    old = read_deps(scenefiles.deps_path(project, scene_id))
    if old is None:
        return None
    reasons = diff(old, build_briefing(project, scene_id).deps)
    rej = (rejected if rejected is not None else changes.open_rejections(project)).get(scene_id, [])
    return SceneStale(scene_id, reasons, rej) if reasons or rej else None


def scan(project: Project) -> StaleReport:
    report = StaleReport()
    if not store.scenes_path(project).exists():
        return report
    scenes = store.load_scenes(project)
    rejected = changes.open_rejections(project)
    for s in scenes:
        try:
            found = scan_scene(project, s.id, rejected)
        except BookforgeError as e:
            report.problems.append(f"{s.id}: {e}")
            continue
        if found:
            report.scenes.append(found)
    report.plan = _scan_plan(project)
    return report


def sync_status(project: Project, report: StaleReport) -> None:
    """Make state.json agree with the scan: stale scenes marked, scenes that are fine again accepted."""
    stale = {s.scene: s for s in report.scenes}
    for sid, item in project.state.items.items():
        if sid in stale and item.status == "accepted":
            item.status, item.updated, item.note = "stale", now(), "; ".join(stale[sid].why())[:300]
        elif sid not in stale and item.status == "stale" and not any(p.startswith(sid + ":") for p in report.problems):
            item.status, item.updated, item.note = "accepted", now(), None
    project.save_state()


# ── the planning layers ───────────────────────────────────────────────────────

def plan_deps_path(project: Project):
    return project.book_dir / "plan-deps.yaml"


def _plan_fingerprints(project: Project) -> dict:
    acts = {a.id: fingerprint(a.model_dump()) for a in store.load_acts(project)}
    chapters = {c.id: fingerprint(c.model_dump()) for c in store.load_chapters(project)}
    return {"acts": acts, "chapters": chapters}


def record_plan(project: Project, only: set[str] | None = None) -> None:
    """Take the snapshot the planning layers are compared with (all of it, or just the chapters/scenes named)."""
    try:
        cur = _plan_fingerprints(project)
        chapters, scenes = store.load_chapters(project), store.load_scenes(project)
    except BookforgeError as e:
        log.warning("no plan snapshot: %s", e)
        return
    old = _read_snapshot(project)
    snap = {"chapters": dict(old.get("chapters", {})), "scenes": dict(old.get("scenes", {}))} if only else {"chapters": {}, "scenes": {}}
    for c in chapters:
        if only is None or c.id in only:
            snap["chapters"][c.id] = {"self": cur["chapters"][c.id], "act": cur["acts"].get(c.act, "")}
    for s in scenes:
        if only is None or s.id in only:
            snap["scenes"][s.id] = {"chapter": cur["chapters"].get(s.chapter, "")}
    plan_deps_path(project).write_text(yaml.safe_dump(snap, sort_keys=True), encoding="utf-8")


def _read_snapshot(project: Project) -> dict:
    try:
        data = yaml.safe_load(plan_deps_path(project).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _scan_plan(project: Project) -> list[PlanStale]:
    snap = _read_snapshot(project)
    if not snap:
        return []
    try:
        cur = _plan_fingerprints(project)
        chapters, scenes = store.load_chapters(project), store.load_scenes(project)
    except BookforgeError:
        return []
    out = []
    for c in chapters:
        rec = (snap.get("chapters") or {}).get(c.id)
        if rec and rec.get("act") != cur["acts"].get(c.act, ""):
            out.append(PlanStale(c.id, "chapter", f"its act {c.act} changed since the structure was approved"))
    for s in scenes:
        rec = (snap.get("scenes") or {}).get(s.id)
        if rec and rec.get("chapter") != cur["chapters"].get(s.chapter, ""):
            out.append(PlanStale(s.id, "scene", f"its chapter {s.chapter} changed since the structure was approved"))
    return out


# ── fixing ────────────────────────────────────────────────────────────────────

@dataclass
class FixResult:
    scene: str
    action: str  # rechecked | patched | redrafted | needs-author | skipped
    note: str = ""


def _read_review(project: Project, sid: str) -> dict:
    raw = scenefiles.read(scenefiles.review_path(project, sid))
    try:
        return json.loads(raw) if raw else {}
    except ValueError:
        return {}


def _write_review(project: Project, sid: str, review: dict) -> None:
    scenefiles.review_path(project, sid).write_text(json.dumps(review, indent=2, ensure_ascii=False), encoding="utf-8")


def _refresh(project: Project, sid: str) -> None:
    """Record what the scene is now built from."""
    write_deps(scenefiles.deps_path(project, sid), build_briefing(project, sid).deps)


def _mark(project: Project, sid: str, status: str, note: str | None, bump: bool = False) -> None:
    item = project.state.items.setdefault(sid, Item())
    item.status, item.updated, item.note = status, now(), note  # type: ignore[assignment]
    if bump:
        item.version += 1
    project.save_state()


def accept_as_is(project: Project, sid: str) -> None:
    """The author says the scene is fine as it is: refresh what it is built from and mark it accepted."""
    _refresh(project, sid)
    for cr in changes.open_rejections(project).get(sid, []):
        cr.fixed = True
        changes.save(project, cr)
    _mark(project, sid, "accepted", "accepted as is by the author")
    _commit(project, sid, "stale, accepted as is", [scenefiles.deps_path(project, sid), changes.change_dir(project)])


def _problems(ctx: StepContext, scene: Scene, scenes: list[Scene], text: str, st: SceneStale | None, mech) -> tuple[list[Flag], list[str], str | None]:
    """(passage flags, problems no passage can fix, why the continuity check could not run)."""
    cfg = ctx.project.config.qc
    flags, unfixable = _mechanical_flags(check_scene(text, mech))
    error = None
    if (st is None or st.needs_continuity) and cfg.continuity_check:
        cont = check_continuity(ctx, scene, scenes, text, what="scene")
        error = cont.error
        for f in cont.flags:
            if f.fixable:
                flags.append(Flag("continuity", f.kind, f.message(), quote=f.evidence, fact=f.question))
            else:
                unfixable.append(f.message())
    for cr in (st.rejected if st else []):
        flags.append(Flag("continuity", "plan", cr.message(), quote=cr.evidence))
    return flags, unfixable, error


def _redraft(ctx: StepContext, scene: Scene, scenes: list[Scene], why: str) -> FixResult:
    project, sid = ctx.project, scene.id
    d = scenefiles.scene_dir(project, sid)
    for old in list(d.glob("draft-*.md")) + [scenefiles.final_path(project, sid), scenefiles.revised_path(project, sid),
                                              scenefiles.summary_path(project, sid), scenefiles.extracted_path(project, sid)]:
        old.unlink(missing_ok=True)
    cfg = project.config.layers["prose"]
    _mark(project, sid, "pending", None)
    accepted, _ = write_scene(ctx, scene, scenes, max(1, cfg.drafts or 2), tuple(cfg.words or (1500, 3000)))
    for cr in changes.open_rejections(project).get(sid, []):
        cr.fixed = True
        changes.save(project, cr)
    if accepted:
        return FixResult(sid, "redrafted", why)
    return FixResult(sid, "needs-author", f"redrafted, but it still needs you: {project.state.items[sid].note or ''}")


def fix_scene(ctx: StepContext, scene: Scene, scenes: list[Scene], st: SceneStale) -> FixResult:
    project, sid = ctx.project, scene.id
    why = "; ".join(st.why())[:200]
    text = scenefiles.read(scenefiles.final_path(project, sid))
    if text is None:
        return FixResult(sid, "skipped", "it has no final.md")
    review = _read_review(project, sid)
    own_text = review.get("source") == "adopted"
    mech = check_context(project, scene, scenes)

    def needs_author(reason: str) -> FixResult:
        _mark(project, sid, "flagged", f"no longer agrees ({why}); {reason}"[:300])
        _commit(project, sid, "stale, needs the author", [])
        return FixResult(sid, "needs-author", f"{reason} ({why})")

    if st.level == "redraft":
        if own_text:
            return needs_author("the scene's plan changed and the text is your own: rewrite it, or delete final.md to have it redrafted")
        return _redraft(ctx, scene, scenes, f"the scene's plan changed ({why})")

    # 1. re-check
    flags, unfixable, error = _problems(ctx, scene, scenes, text, st, mech)
    if not flags and not unfixable:
        if error:
            return FixResult(sid, "skipped", f"could not re-check (the scene stays stale): {error}")
        _refresh(project, sid)
        for cr in st.rejected:
            cr.fixed = True
            changes.save(project, cr)
        _mark(project, sid, "accepted", f"re-checked after a change: still agrees ({why})"[:300])
        _commit(project, sid, "stale, re-checked: still agrees", [scenefiles.deps_path(project, sid), changes.change_dir(project)])
        return FixResult(sid, "rechecked", "still agrees")

    if own_text:
        return needs_author("the text is your own, so it is not patched")
    # 2. patch
    if not unfixable:
        try:
            revision = revise_text(ctx, text, flags, all_banned(mech), f"{sid} stale patch")
        except LayerError as e:
            return _redraft(ctx, scene, scenes, f"a patch was not possible ({e})")
        if revision.applied and not revision.unfixed:
            after, left, err = _problems(ctx, scene, scenes, revision.text, SceneStale(sid, st.reasons), mech)
            if not after and not left and not err:
                return _finish_patch(ctx, scene, scenes, revision.text, review, [a for a in revision.applied], why, st)
    # 3. redraft
    return _redraft(ctx, scene, scenes, f"the patch did not resolve it ({why})")


def _finish_patch(ctx, scene: Scene, scenes: list[Scene], text: str, review: dict, applied: list[dict], why: str, st: SceneStale) -> FixResult:
    project, sid = ctx.project, scene.id
    final = scenefiles.final_path(project, sid)
    final.write_text(text.rstrip() + "\n", encoding="utf-8")
    summary, source = _summarise(ctx, scene, text)
    scenefiles.summary_path(project, sid).write_text(summary.rstrip() + "\n", encoding="utf-8")
    paths = [final, scenefiles.summary_path(project, sid), scenefiles.deps_path(project, sid), scenefiles.review_path(project, sid)]
    review["summary_source"] = source
    record_extraction(ctx, scene, scenes, text, review, paths)
    review.setdefault("stale_fixes", []).append({"at": now(), "action": "patched", "why": why, "passages": applied})
    _write_review(project, sid, review)
    _refresh(project, sid)
    for cr in st.rejected:
        cr.fixed = True
        changes.save(project, cr)
    paths.append(changes.change_dir(project))
    _mark(project, sid, "accepted", f"patched after a change ({why})"[:300], bump=True)
    _commit(project, sid, "stale, patched", paths)
    return FixResult(sid, "patched", f"{len(applied)} passage(s) rewritten")


def fix_all(ctx: StepContext, only: set[str] | None = None) -> list[FixResult]:
    """Fix every stale scene in book order. Each scene is looked at when its turn comes, so a patch that
    changes the end of one scene is seen by the next."""
    project = ctx.project
    scenes = store.load_scenes(project)
    results = []
    for s in scenes:
        if only is not None and s.id not in only:
            continue
        try:
            st = scan_scene(project, s.id)
        except BookforgeError as e:
            results.append(FixResult(s.id, "skipped", str(e)))
            continue
        if st is None:
            if project.state.items.get(s.id, Item()).status == "stale":
                _mark(project, s.id, "accepted", None)
            continue
        results.append(fix_scene(ctx, s, scenes, st))
    return results
