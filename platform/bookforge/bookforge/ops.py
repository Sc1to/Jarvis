"""The multi-step operations shared by the command line and the HTTP service.

Each takes an open project and the clients it needs (so tests and the service can pass their own) and
returns plain data; printing and HTTP formatting stay with the caller.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import assemble as assembly, bench as benchmarks, changes as change_requests, report as morning_report, stale as staleness, vcs
from .bible import store as bible_store
from .errors import BookforgeError
from .layers import HANDLERS
from .layers.runner import RunSummary, StepContext, run as run_layers
from .llm import LLMClient
from .project import Project
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


def decide_change(project: Project, cr_id: str, approve: bool) -> change_requests.ChangeRequest:
    decided = change_requests.approve(project, cr_id) if approve else change_requests.reject(project, cr_id)
    if project.config.git.commit_each_step:
        vcs.commit(project.root, f"{project.book}: change request {decided.id} {decided.status}")
    return decided
