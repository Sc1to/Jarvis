import subprocess

import pytest

from bookforge.errors import BookforgeError
from bookforge.layers.runner import StepContext, StepResult, run
from bookforge.llm import FakeLLMClient
from bookforge.project import Project
from bookforge.state import load_state

from conftest import all_handlers, file_handler


def commits(project):
    out = subprocess.run(["git", "-C", str(project.root), "log", "--format=%s"], capture_output=True, text=True).stdout
    return [m for m in out.split("\n") if m]


def test_empty_registry_stops_at_first_layer_and_changes_nothing(project):
    before = project.state.model_copy(deep=True)
    summary = run(project, None, {})
    assert summary.stopped == "not_implemented" and summary.exit_code == 2
    assert summary.ran == []
    assert "series_north_star" in summary.detail
    assert load_state(project.state_path).layers == before.layers
    assert len(commits(project)) == 1


def test_runs_layers_1_to_3_then_stops_at_direction_checkpoint(project):
    summary = run(project, None, all_handlers())
    assert summary.ran == ["series_north_star", "book_north_star", "synopsis"]
    assert summary.stopped == "checkpoint" and summary.exit_code == 0
    assert "direction" in summary.detail
    state = load_state(project.state_path)
    assert state.checkpoints["direction"].status == "waiting"
    assert all(state.layers[n].status == "accepted" and state.layers[n].version == 1 for n in summary.ran)
    assert state.layers["acts"].status == "pending"


def test_one_commit_per_accepted_step_including_its_files_and_state(project):
    run(project, None, all_handlers())
    assert commits(project) == [
        "b1.synopsis: accepted",
        "b1.book_north_star: accepted",
        "b1.series_north_star: accepted",
        "series: initialized with book b1",
    ]
    tracked = subprocess.run(["git", "-C", str(project.root), "ls-files"], capture_output=True, text=True).stdout.split()
    assert {"north-star.md", "books/b1/north-star.md", "books/b1/synopsis.md"} <= set(tracked)
    status = subprocess.run(["git", "-C", str(project.root), "status", "--porcelain"], capture_output=True, text=True).stdout
    assert status.strip() == ""


def test_next_run_is_blocked_until_checkpoint_is_approved(project):
    run(project, None, all_handlers())
    again = run(project, None, all_handlers())
    assert again.stopped == "checkpoint" and again.ran == []
    assert "'direction'" in again.detail and "'acts'" in again.detail

    project.state.approve_checkpoint("direction")
    project.save_state()
    after = run(project, None, all_handlers())
    assert after.ran == ["acts", "chapters", "scenes"]
    assert after.stopped == "checkpoint" and "structure" in after.detail


def test_structure_checkpoint_covers_acts_chapters_and_scenes(project):
    run(project, None, all_handlers())
    project.state.approve_checkpoint("direction")
    summary = run(project, None, all_handlers(), until="chapters")
    assert summary.stopped == "until"
    assert project.state.checkpoints["structure"].status == "pending"  # scenes not accepted yet
    run(project, None, all_handlers())
    assert project.state.checkpoints["structure"].status == "waiting"


def test_prose_waits_for_structure_approval_and_then_completes(project):
    run(project, None, all_handlers())
    project.state.approve_checkpoint("direction")
    run(project, None, all_handlers())
    blocked = run(project, None, all_handlers())
    assert blocked.stopped == "checkpoint" and blocked.ran == []
    project.state.approve_checkpoint("structure")
    done = run(project, None, all_handlers())
    assert done.ran == ["prose"] and done.stopped == "complete"


def test_until_stops_after_the_named_layer(project):
    summary = run(project, None, all_handlers(), until="series_north_star")
    assert summary.stopped == "until"
    assert summary.ran == ["series_north_star"]
    assert project.state.checkpoints["direction"].status == "pending"


def test_until_already_accepted_runs_nothing(project):
    run(project, None, all_handlers(), until="series_north_star")
    summary = run(project, None, all_handlers(), until="series_north_star")
    assert summary.ran == [] and summary.stopped == "until"


def test_unknown_until_is_an_error(project):
    with pytest.raises(BookforgeError, match="unknown layer"):
        run(project, None, all_handlers(), until="epilogue")


def test_failing_handler_flags_the_layer_and_a_rerun_recovers(project):
    def boom(ctx: StepContext) -> StepResult:
        raise RuntimeError("model offline")

    handlers = {**all_handlers(), "book_north_star": boom}
    summary = run(project, None, handlers)
    assert summary.stopped == "failed" and summary.exit_code == 1
    assert summary.ran == ["series_north_star"]
    assert "model offline" in summary.detail
    state = load_state(project.state_path)
    assert state.layers["book_north_star"].status == "flagged"
    assert state.layers["book_north_star"].note == "model offline"
    assert "b1.book_north_star: accepted" not in commits(project)

    recovered = run(project, None, all_handlers())
    assert recovered.ran == ["book_north_star", "synopsis"]


def test_handler_cannot_report_files_outside_the_series(project):
    def sneaky(ctx: StepContext) -> StepResult:
        return StepResult(files=["../outside.md"])

    summary = run(project, None, {"series_north_star": sneaky}, until="series_north_star")
    assert summary.stopped == "failed"
    assert load_state(project.state_path).layers["series_north_star"].status == "flagged"


def test_commit_each_step_can_be_turned_off(project):
    (project.root / "config.yaml").write_text("git:\n  commit_each_step: false\n", encoding="utf-8")
    reopened = Project.open(project.root)
    run(reopened, None, all_handlers())
    assert commits(reopened) == ["series: initialized with book b1"]


def test_handlers_receive_the_llm_and_context(project):
    llm = FakeLLMClient({"critic": ["# North star\nA ledger of deaths.\n"]})
    seen = {}

    def handler(ctx: StepContext) -> StepResult:
        seen["layer"], seen["book"] = ctx.layer, ctx.project.book
        text = ctx.llm.complete("critic", [{"role": "user", "content": ctx.project.resolve("premise.md").read_text()}])
        ctx.project.resolve("north-star.md").write_text(text)
        return StepResult(files=["north-star.md"])

    run(project, llm, {"series_north_star": handler}, until="series_north_star")
    assert seen == {"layer": "series_north_star", "book": "b1"}
    assert "ledger that predicts deaths" in llm.calls[0]["messages"][0]["content"]
    assert (project.root / "north-star.md").read_text().startswith("# North star")
