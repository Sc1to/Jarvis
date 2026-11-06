"""The shared layer loop (skeleton).

Walks the layers in order, runs the registered handler for each, marks the layer
accepted, commits the step, and stops at human checkpoints. The refine / research /
review / correct loop inside a handler is built in milestone 14.3 and later.
"""

import logging
from dataclasses import dataclass, field
from typing import Callable

from .. import vcs
from .. import activity, cancel, steering
from ..constants import CHECKPOINT_REVIEW_FILES, LAYER_ORDER
from ..errors import BookforgeError
from ..llm import LLMClient
from ..project import Project
from ..research.search import WebClient

log = logging.getLogger("platform_bookforge.runner")


@dataclass
class StepContext:
    project: Project
    layer: str
    llm: LLMClient | None
    web: WebClient | None = None  # None: research is skipped


@dataclass
class StepResult:
    files: list[str]  # paths the handler wrote, relative to the series root
    note: str = ""
    # accepted: the layer is done. partial: made progress and stopped (at `checkpoint`, if given), to be run again.
    # flagged: finished what it could, but some items need the author. Files are committed in every case.
    outcome: str = "accepted"
    checkpoint: str | None = None


Handler = Callable[[StepContext], StepResult]


@dataclass
class RunSummary:
    ran: list[str] = field(default_factory=list)
    notes: dict[str, str] = field(default_factory=dict)  # layer -> what the handler reported
    stopped: str = "complete"  # complete | until | checkpoint | cancelled | not_implemented | failed
    detail: str = ""

    @property
    def exit_code(self) -> int:
        return {"complete": 0, "until": 0, "checkpoint": 0, "cancelled": 0, "not_implemented": 2, "failed": 1}[self.stopped]


def review_files(project: Project, checkpoint: str) -> list[str]:
    """The files to review at a checkpoint that exist now, as paths relative to the series."""
    found: list[str] = []
    for pattern in CHECKPOINT_REVIEW_FILES.get(checkpoint, ()):
        pattern = pattern.format(book=project.book)
        found += sorted(str(p.relative_to(project.root)) for p in project.root.glob(pattern) if p.is_file())
    return found


def _commit_step(project: Project, layer: str, files: list[str], label: str) -> None:
    if project.config.git.commit_each_step:
        state_rel = str(project.state_path.relative_to(project.root))
        vcs.commit(project.root, f"{project.book}.{layer}: {label}", files + [state_rel])


def _blocking_checkpoint(project: Project, layer: str) -> str | None:
    """A checkpoint on an earlier layer, not shared by this one, that is not yet approved."""
    cfg = project.config.layers
    idx = LAYER_ORDER.index(layer)
    own = cfg[layer].checkpoint
    for earlier in LAYER_ORDER[:idx]:
        cp = cfg[earlier].checkpoint
        if cp and cp != own and project.state.checkpoints[cp].status != "approved":
            return cp
    return None


def _update_checkpoints(project: Project) -> None:
    for cp in ("direction", "structure"):
        layers = project.config.checkpoint_layers(cp)
        if layers and all(project.state.layers[name].status == "accepted" for name in layers):
            project.state.reach_checkpoint(cp)


def run(
    project: Project, llm: LLMClient | None, handlers: dict[str, Handler],
    until: str | None = None, web: WebClient | None = None,
) -> RunSummary:
    if until is not None and until not in LAYER_ORDER:
        raise BookforgeError(f"unknown layer '{until}' (expected one of: {', '.join(LAYER_ORDER)})")
    order = LAYER_ORDER if until is None else LAYER_ORDER[: LAYER_ORDER.index(until) + 1]
    summary = RunSummary(stopped="until" if until else "complete")

    for layer in order:
        if project.state.layers[layer].status == "accepted":
            continue

        blocker = _blocking_checkpoint(project, layer)
        if blocker:
            summary.stopped = "checkpoint"
            summary.detail = f"waiting for you to approve the '{blocker}' checkpoint before '{layer}'"
            return summary

        handler = handlers.get(layer)
        if handler is None:
            summary.stopped = "not_implemented"
            summary.detail = f"layer '{layer}' has no implementation yet"
            return summary

        try:
            cancel.check()
            activity.set(layer=layer, scene=None, step=None)
            result = handler(StepContext(project=project, layer=layer, llm=llm, web=web))
            files = [str(project.resolve(f).relative_to(project.root.resolve())) for f in result.files]
        except cancel.Cancelled:  # stopped by the author: not a failure; what is done stays, the rest runs again next time
            project.save_state()
            summary.stopped = "cancelled"
            summary.detail = f"stopped at your request during '{layer}'; what was finished is kept, run again to continue"
            return summary
        except Exception as e:  # a failed layer is flagged, never a crash mid-run
            log.exception("layer %s failed", layer)
            project.state.set_layer_status(layer, "flagged", note=str(e))
            project.save_state()
            summary.stopped = "failed"
            summary.detail = f"layer '{layer}' failed: {e}"
            return summary

        if result.note:
            summary.notes[layer] = result.note

        if result.outcome == "partial":
            project.state.set_layer_status(layer, "drafted", note=result.note or None)
            if result.checkpoint:
                project.state.reach_checkpoint(result.checkpoint)
            project.save_state()
            _commit_step(project, layer, files, "drafted")
            summary.stopped = "checkpoint"
            summary.detail = result.note
            if result.checkpoint:
                summary.detail = f"reached the '{result.checkpoint}' checkpoint; review, then run `approve {result.checkpoint}`"
                review = review_files(project, result.checkpoint)
                if review:
                    summary.detail += "\nReview (edit freely; your edits are kept): " + ", ".join(review)
            return summary
        if result.outcome == "flagged":
            project.state.set_layer_status(layer, "flagged", note=result.note or None)
            project.save_state()
            _commit_step(project, layer, files, "flagged")
            summary.stopped = "failed"
            summary.detail = f"layer '{layer}' needs you: {result.note}"
            return summary

        project.state.set_layer_status(layer, "accepted", note=result.note or None)
        steering.clear(project, layer)  # the author's note for a rewrite has done its work
        _update_checkpoints(project)
        project.save_state()
        summary.ran.append(layer)
        _commit_step(project, layer, files, "accepted")

        reached = [
            cp for cp in ("direction", "structure")
            if project.state.checkpoints[cp].status == "waiting"
            and project.config.layers[layer].checkpoint == cp
        ]
        if reached:
            summary.stopped = "checkpoint"
            review = review_files(project, reached[0])
            summary.detail = f"reached the '{reached[0]}' checkpoint; review, then run `approve {reached[0]}`"
            if review:
                summary.detail += "\nReview (edit freely; your edits are kept): " + ", ".join(review)
            return summary

    return summary
