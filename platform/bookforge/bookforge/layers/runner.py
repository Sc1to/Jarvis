"""The shared layer loop (skeleton).

Walks the layers in order, runs the registered handler for each, marks the layer
accepted, commits the step, and stops at human checkpoints. The refine / research /
review / correct loop inside a handler is built in milestone 14.3 and later.
"""

import logging
from dataclasses import dataclass, field
from typing import Callable

from .. import vcs
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


Handler = Callable[[StepContext], StepResult]


@dataclass
class RunSummary:
    ran: list[str] = field(default_factory=list)
    notes: dict[str, str] = field(default_factory=dict)  # layer -> what the handler reported
    stopped: str = "complete"  # complete | until | checkpoint | not_implemented | failed
    detail: str = ""

    @property
    def exit_code(self) -> int:
        return {"complete": 0, "until": 0, "checkpoint": 0, "not_implemented": 2, "failed": 1}[self.stopped]


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
            result = handler(StepContext(project=project, layer=layer, llm=llm, web=web))
            files = [str(project.resolve(f).relative_to(project.root.resolve())) for f in result.files]
        except Exception as e:  # a failed layer is flagged, never a crash mid-run
            log.exception("layer %s failed", layer)
            project.state.set_layer_status(layer, "flagged", note=str(e))
            project.save_state()
            summary.stopped = "failed"
            summary.detail = f"layer '{layer}' failed: {e}"
            return summary

        project.state.set_layer_status(layer, "accepted", note=result.note or None)
        _update_checkpoints(project)
        project.save_state()
        summary.ran.append(layer)
        if result.note:
            summary.notes[layer] = result.note

        if project.config.git.commit_each_step:
            state_rel = str(project.state_path.relative_to(project.root))
            vcs.commit(project.root, f"{project.book}.{layer}: accepted", files + [state_rel])

        reached = [
            cp for cp in ("direction", "structure")
            if project.state.checkpoints[cp].status == "waiting"
            and project.config.layers[layer].checkpoint == cp
        ]
        if reached:
            summary.stopped = "checkpoint"
            review = [f.format(book=project.book) for f in CHECKPOINT_REVIEW_FILES.get(reached[0], ())]
            review = [f for f in review if (project.root / f).exists()]
            summary.detail = f"reached the '{reached[0]}' checkpoint; review, then run `approve {reached[0]}`"
            if review:
                summary.detail += "\nReview (edit freely; your edits are kept): " + ", ".join(review)
            return summary

    return summary
