import json

import pytest
from typer.testing import CliRunner

from bookforge.cli import app
from bookforge.layers import HANDLERS
from bookforge.project import Project
from bookforge.state import load_state

from conftest import all_handlers

runner = CliRunner()


@pytest.fixture
def premise(tmp_path):
    p = tmp_path / "premise.md"
    p.write_text("A clerk finds a ledger that predicts deaths.\n")
    return p


@pytest.fixture
def with_handlers(monkeypatch):
    for name, h in all_handlers().items():
        monkeypatch.setitem(HANDLERS, name, h)


def test_no_arguments_shows_help():
    result = runner.invoke(app, [])
    assert "new" in result.output and "approve" in result.output and "doctor" in result.output


def test_new_creates_a_series(tmp_path, premise):
    target = tmp_path / "s"
    result = runner.invoke(app, ["new", str(target), "--premise", str(premise)])
    assert result.exit_code == 0, result.output
    assert (target / "books/b1/state.json").exists()
    assert "Created series" in result.output


def test_new_reports_problems_with_exit_code_1(tmp_path, premise):
    missing = runner.invoke(app, ["new", str(tmp_path / "s"), "--premise", str(tmp_path / "nope.md")])
    assert missing.exit_code == 1 and "premise file not found" in missing.output
    runner.invoke(app, ["new", str(tmp_path / "s"), "--premise", str(premise)])
    twice = runner.invoke(app, ["new", str(tmp_path / "s"), "--premise", str(premise)])
    assert twice.exit_code == 1 and "not empty" in twice.output
    bad_book = runner.invoke(app, ["new", str(tmp_path / "t"), "--premise", str(premise), "--book", "B 1"])
    assert bad_book.exit_code == 1 and "invalid book id" in bad_book.output


def test_status_table_and_json(project):
    table = runner.invoke(app, ["status", str(project.root)])
    assert table.exit_code == 0
    assert "series_north_star" in table.output and "direction" in table.output
    as_json = runner.invoke(app, ["status", str(project.root), "--json"])
    assert json.loads(as_json.output)["book"] == "b1"


def test_status_on_a_folder_that_is_not_a_series(tmp_path):
    result = runner.invoke(app, ["status", str(tmp_path)])
    assert result.exit_code == 1 and "no book 'b1'" in result.output


def test_run_with_nothing_implemented_exits_2(project):
    result = runner.invoke(app, ["run", str(project.root)])
    assert result.exit_code == 2
    assert "nothing ran" in result.output and "no implementation yet" in result.output


def test_run_rejects_unknown_until_layer(project):
    result = runner.invoke(app, ["run", str(project.root), "--until", "epilogue"])
    assert result.exit_code == 1 and "unknown layer" in result.output


def test_run_stops_at_direction_checkpoint(project, with_handlers):
    result = runner.invoke(app, ["run", str(project.root)])
    assert result.exit_code == 0, result.output
    assert "accepted: synopsis" in result.output and "approve direction" in result.output


def test_approve_before_checkpoint_is_reached_fails(project):
    result = runner.invoke(app, ["approve", str(project.root), "direction"])
    assert result.exit_code == 1 and "not waiting" in result.output
    unknown = runner.invoke(app, ["approve", str(project.root), "midpoint"])
    assert unknown.exit_code == 1 and "unknown checkpoint" in unknown.output


def test_approve_records_commit_and_tag_then_run_continues(project, with_handlers):
    runner.invoke(app, ["run", str(project.root)])
    result = runner.invoke(app, ["approve", str(project.root), "direction"])
    assert result.exit_code == 0, result.output
    assert load_state(project.state_path).checkpoints["direction"].status == "approved"

    import subprocess
    tags = subprocess.run(["git", "-C", str(project.root), "tag", "--list"], capture_output=True, text=True).stdout.split()
    assert tags == ["b1-direction-approved"]
    head = subprocess.run(["git", "-C", str(project.root), "log", "-1", "--format=%s"], capture_output=True, text=True).stdout.strip()
    assert head == "b1: direction approved"

    again = runner.invoke(app, ["approve", str(project.root), "direction"])
    assert again.exit_code == 1  # cannot approve twice

    nxt = runner.invoke(app, ["run", str(project.root)])
    assert "accepted: acts" in nxt.output and "approve structure" in nxt.output


def test_doctor_passes_with_warnings_on_a_fresh_series(project):
    result = runner.invoke(app, ["doctor", str(project.root), "--offline"])
    assert result.exit_code == 0, result.output
    assert "[PASS] git" in result.output and "[PASS] series_state" in result.output
    assert "[WARN] network" in result.output and "--offline" in result.output


def test_doctor_fails_on_corrupt_state_and_bad_config(project):
    project.state_path.write_text("{broken")
    result = runner.invoke(app, ["doctor", str(project.root), "--offline"])
    assert result.exit_code == 1 and "[FAIL] series_state" in result.output

    (project.root / "config.yaml").write_text("nope: 1\n")
    result = runner.invoke(app, ["doctor", str(project.root), "--offline"])
    assert result.exit_code == 1 and "[FAIL] config" in result.output


def test_doctor_warns_about_uncommitted_changes(project):
    (project.root / "style/guide.md").write_text("changed\n")
    result = runner.invoke(app, ["doctor", str(project.root), "--offline"])
    assert result.exit_code == 0 and "[WARN] series_git" in result.output


def test_doctor_without_a_series(tmp_path):
    result = runner.invoke(app, ["doctor", "--offline"])
    assert result.exit_code == 0 and "series_state" not in result.output
