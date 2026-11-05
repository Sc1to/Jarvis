"""Deleting books and series."""

import json
import shutil
import subprocess

import pytest
import yaml
from fastapi.testclient import TestClient
from typer.testing import CliRunner

import main
from bookforge import api, cli, deletion, vcs
from bookforge.bible import store
from bookforge.project import Project
from bookforge.state import new_state, save_state
from conftest import RuleLLM
from test_prose_qc import book, qc_rules  # noqa: F401  (book is a fixture)
from test_report_assemble_bench import full  # noqa: F401  (fixture)

client = TestClient(main.app, raise_server_exceptions=False)
B = "/api/series/series/books/b1"


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True).stdout


@pytest.fixture
def two_books(full):
    """The finished b1 plus a b2 that has its own entries in the shared bible files, workbench scores and threads."""
    root = full.root
    (root / "books" / "b2").mkdir()
    save_state(root / "books" / "b2" / "state.json", new_state("b2"))
    (root / "books" / "b2" / "notes.md").write_text("book two")
    tracks = yaml.safe_load((root / "bible" / "tracks.yaml").read_text())
    tracks["tracks"][0]["plan"].append({"from": "b2.ch01", "value": "book two state", "must_show": False})
    tracks["tracks"].append({"id": "b2-only", "entity": "anna", "kind": "other", "version": 1, "observed": [],
                             "plan": [{"from": "b2.ch01", "value": "only in book two", "must_show": False}]})
    (root / "bible" / "tracks.yaml").write_text(yaml.safe_dump(tracks))
    timeline = yaml.safe_load((root / "bible" / "timeline.yaml").read_text())
    timeline["scenes"].append({"id": "b2.ch01.s1", "day": 1, "time": "dawn"})
    (root / "bible" / "timeline.yaml").write_text(yaml.safe_dump(timeline))
    (root / "workbench").mkdir(exist_ok=True)
    (root / "workbench" / "calibration.yaml").write_text(yaml.safe_dump({"scores": {"b1.ch01.s1": {"voice": 4}, "b2.ch01.s1": {"voice": 3}}}))
    (root / "workbench" / "threads.yaml").write_text(yaml.safe_dump({"threads": [{"id": "t1", "setup": "b1.ch01.s1"}, {"id": "t2", "setup": "b2.ch01.s1"}]}))
    (root / "workbench" / "rules.yaml").write_text(yaml.safe_dump({"rules": [
        {"id": "r1", "type": "style_rule", "text": "x", "scope": "book", "target": "b1"},
        {"id": "r2", "type": "style_rule", "text": "x", "scope": "scene", "target": "b1.ch01.s1"},
        {"id": "r3", "type": "style_rule", "text": "x", "scope": "series"}]}))
    vcs.commit(root, "test: a second book")
    return root


# ── a book ──────────────────────────────────────────────────────────────────

def test_deleting_a_book_removes_its_folder_and_only_its_entries_in_the_shared_files(two_books):
    ids_before = [t["id"] for t in yaml.safe_load((two_books / "bible" / "tracks.yaml").read_text())["tracks"]]
    shared = ids_before[0]  # the track that also has a book-two entry
    r = deletion.delete_book(two_books, "b1")
    assert not (two_books / "books" / "b1").exists() and (two_books / "books" / "b2" / "notes.md").exists()
    tracks = yaml.safe_load((two_books / "bible" / "tracks.yaml").read_text())["tracks"]
    assert [t["id"] for t in tracks] == [shared, "b2-only"]  # tracks only book one used are gone; the shared one stays with book two's entry
    assert all(not e["from"].startswith("b1.") for t in tracks for e in t["plan"]) and any(e["from"] == "b2.ch01" for t in tracks for e in t["plan"])
    assert all(not o["at"].startswith("b1.") for t in tracks for o in t.get("observed", []))
    assert [s["id"] for s in yaml.safe_load((two_books / "bible" / "timeline.yaml").read_text())["scenes"]] == ["b2.ch01.s1"]
    assert r["timeline_removed"] == 8 and r["track_entries_removed"] > 0 and r["tracks_removed"] >= 1


def test_workbench_entries_of_the_book_go_and_book_rules_are_counted_not_deleted(two_books):
    r = deletion.delete_book(two_books, "b1")
    assert list(yaml.safe_load((two_books / "workbench" / "calibration.yaml").read_text())["scores"]) == ["b2.ch01.s1"]
    assert [t["id"] for t in yaml.safe_load((two_books / "workbench" / "threads.yaml").read_text())["threads"]] == ["t2"]
    assert len(yaml.safe_load((two_books / "workbench" / "rules.yaml").read_text())["rules"]) == 3  # left alone
    assert (r["calibration_removed"], r["threads_removed"], r["inactive_rules"]) == (1, 1, 2)


def test_a_deleted_book_is_a_git_commit_and_can_be_brought_back(two_books):
    before = git(two_books, "rev-parse", "HEAD").strip()
    deletion.delete_book(two_books, "b1")
    assert git(two_books, "log", "--format=%s", "-1").startswith("delete book b1")
    assert git(two_books, "status", "--porcelain").strip() == ""
    git(two_books, "checkout", before, "--", "books/b1")
    assert (two_books / "books" / "b1" / "state.json").exists()


def test_deleting_the_last_book_leaves_an_empty_series(book):
    deletion.delete_book(book.root, "b1")
    assert not (book.root / "books" / "b1").exists() and (book.root / "premise.md").exists()


def test_unknown_and_invalid_books_are_refused(book):
    for b in ("b9", "../x", "B1"):
        with pytest.raises(deletion.DeleteError):
            deletion.delete_book(book.root, b)


# ── a series and the trash ──────────────────────────────────────────────────

def test_a_series_goes_to_the_trash_and_can_be_restored(book):
    data = book.root.parent
    dest = deletion.trash_series(data, "series")
    assert not (data / "series").exists() and (dest / "premise.md").exists() and dest.parent.name == ".trash"
    [item] = deletion.list_trash(data)
    assert item["series"] == "series" and item["books"] == ["b1"] and item["deleted"]
    assert deletion.restore(data, item["name"]) == "series" and (data / "series" / "books" / "b1" / "state.json").exists()
    assert deletion.list_trash(data) == []


def test_restore_refuses_to_overwrite_and_reports_a_missing_item(book):
    data = book.root.parent
    dest = deletion.trash_series(data, "series")
    (data / "series").mkdir()
    with pytest.raises(deletion.DeleteError) as e:
        deletion.restore(data, dest.name)
    assert "exists now" in str(e.value)
    with pytest.raises(deletion.DeleteError):
        deletion.restore(data, "nothing-20200101-000000")


def test_emptying_the_trash_removes_it_for_good(book):
    data = book.root.parent
    deletion.trash_series(data, "series")
    assert deletion.empty_trash(data) == 1 and deletion.list_trash(data) == [] and deletion.empty_trash(data) == 0


def test_an_unknown_series_cannot_be_trashed(tmp_path):
    with pytest.raises(deletion.DeleteError):
        deletion.trash_series(tmp_path, "nope")


# ── the API ─────────────────────────────────────────────────────────────────

@pytest.fixture
def served(book, monkeypatch):
    monkeypatch.setattr(main, "DATA_DIR", str(book.root.parent))
    return book


def test_delete_a_book_over_the_api(served):
    r = client.delete(B)
    assert r.status_code == 200 and r.json()["data"]["book"] == "b1"
    assert client.get(f"{B}/status").status_code == 404
    assert client.get("/api/series").json()["data"][0]["books"] == []


def test_delete_a_series_over_the_api_then_restore_it(served):
    r = client.delete("/api/series/series")
    assert r.status_code == 200
    trash = r.json()["data"]["trash"]
    assert client.get("/api/series").json()["data"] == []
    assert [t["name"] for t in client.get("/api/trash").json()["data"]] == [trash]
    assert client.post(f"/api/trash/{trash}/restore").json()["data"] == {"series": "series"}
    assert [s["name"] for s in client.get("/api/series").json()["data"]] == ["series"]
    client.delete("/api/series/series")
    assert client.post("/api/trash/empty").json()["data"] == {"removed": 1} and client.get("/api/trash").json()["data"] == []


def test_nothing_is_deleted_while_a_job_runs(served, monkeypatch):
    import threading
    gate, started = threading.Event(), threading.Event()

    class Slow(RuleLLM):
        def complete(self, role, messages, **options):
            started.set()
            gate.wait(30)
            return super().complete(role, messages, **options)

    monkeypatch.setattr(api, "make_llm", lambda project: Slow(qc_rules()))
    monkeypatch.setattr(api, "make_web", lambda project: None)
    job = client.post(f"{B}/run", json={"until": "prose"}).json()["data"]
    assert started.wait(30)
    try:
        assert client.delete(B).status_code == 409 and client.delete("/api/series/series").status_code == 409
    finally:
        gate.set()
    api.jobs.wait(job["id"], 60)
    assert (served.root / "books" / "b1").exists()


def test_unknown_things_and_odd_names_are_404(served):
    assert client.delete("/api/series/nope").status_code == 404
    assert client.delete("/api/series/series/books/b9").status_code == 404
    assert client.post("/api/trash/..%2fseries/restore").status_code == 404
    assert client.post("/api/trash/.hidden/restore").status_code == 404


# ── the command line ────────────────────────────────────────────────────────

def test_the_delete_and_trash_commands(two_books):
    runner = CliRunner()
    assert runner.invoke(cli.app, ["delete", str(two_books), "--book", "b1"], input="n\n").exit_code == 1 and (two_books / "books" / "b1").exists()
    out = runner.invoke(cli.app, ["delete", str(two_books), "--book", "b1", "--yes"])
    assert out.exit_code == 0 and "deleted book b1" in out.output and "2 rule(s) were scoped to it" in out.output
    out = runner.invoke(cli.app, ["delete", str(two_books), "--yes"])
    assert out.exit_code == 0 and "moved to" in out.output and "--restore" in out.output
    listing = runner.invoke(cli.app, ["trash", str(two_books.parent)])
    assert "(series series, books: b2" in listing.output
    name = listing.output.split()[0]
    assert "restored as series" in runner.invoke(cli.app, ["trash", str(two_books.parent), "--restore", name]).output
    runner.invoke(cli.app, ["delete", str(two_books), "--yes"])
    assert "removed 1 item" in runner.invoke(cli.app, ["trash", str(two_books.parent), "--empty"]).output
    assert "the trash is empty" in runner.invoke(cli.app, ["trash", str(two_books.parent)]).output
