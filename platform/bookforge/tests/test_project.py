import json
import subprocess

import pytest

from bookforge.errors import BookforgeError
from bookforge.project import Project


def test_create_lays_out_the_series(project):
    root = project.root
    for rel in ("premise.md", "ledger.yaml", "style/guide.md", "style/banned.txt", "bible/constants.yaml",
                "bible/tracks.yaml", "bible/timeline.yaml", "books/b1/state.json", ".gitignore"):
        assert (root / rel).is_file(), rel
    assert "ledger" in (root / "premise.md").read_text()
    assert json.loads((root / "books/b1/state.json").read_text())["book"] == "b1"


def test_create_makes_one_clean_commit(project_with_ledger):
    project = project_with_ledger
    log = subprocess.run(["git", "-C", str(project.root), "log", "--format=%s"], capture_output=True, text=True).stdout.split("\n")
    assert [m for m in log if m] == ["series: initialized with book b1"]
    status = subprocess.run(["git", "-C", str(project.root), "status", "--porcelain"], capture_output=True, text=True).stdout
    assert status.strip() == ""


def test_logs_are_not_tracked(project_with_ledger):
    project = project_with_ledger
    logs = project.book_dir / "logs"
    logs.mkdir()
    (logs / "calls.jsonl").write_text("{}\n")
    status = subprocess.run(["git", "-C", str(project.root), "status", "--porcelain"], capture_output=True, text=True).stdout
    assert status.strip() == ""


def test_create_refuses_non_empty_folder_and_empty_premise(tmp_path):
    target = tmp_path / "taken"
    target.mkdir()
    (target / "x").write_text("x")
    with pytest.raises(BookforgeError, match="not empty"):
        Project.create(target, "premise")
    with pytest.raises(BookforgeError, match="premise is empty"):
        Project.create(tmp_path / "new", "   \n")


def test_create_accepts_existing_empty_folder(tmp_path):
    (tmp_path / "empty").mkdir()
    assert Project.create(tmp_path / "empty", "premise").book == "b1"


@pytest.mark.parametrize("bad", ["B1", "1b", "../x", "b 1", "", "a" * 40])
def test_book_id_is_validated(tmp_path, bad):
    with pytest.raises(BookforgeError, match="invalid book id"):
        Project.create(tmp_path / "s", "premise", book=bad)


def test_open_round_trip_and_missing_book(project):
    reopened = Project.open(project.root)
    assert reopened.state == project.state
    with pytest.raises(BookforgeError, match="no book 'b2'"):
        Project.open(project.root, "b2")


def test_resolve_refuses_paths_outside_the_series(project):
    assert project.resolve("books/b1/synopsis.md").parent.name == "b1"
    for bad in ("../outside.md", "/etc/passwd", "books/../../outside"):
        with pytest.raises(BookforgeError, match="escapes"):
            project.resolve(bad)


def test_series_config_file_is_honoured(project):
    (project.root / "config.yaml").write_text("git:\n  commit_each_step: false\n", encoding="utf-8")
    assert Project.open(project.root).config.git.commit_each_step is False
