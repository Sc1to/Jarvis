"""Rewriting scenes: deleting files does not do it; `rewrite` does, also while the voice checkpoint waits."""

import json

import pytest
from typer.testing import CliRunner

from bookforge import cli, ops, scenefiles
from bookforge.bible import store
from bookforge.errors import BookforgeError
from bookforge.project import Project
from bookforge.state import load_state
from conftest import RuleLLM
from prose_fakes import prose
from qc_fakes import EXTRACT, extractor
from test_prose_qc import SID, book, calls, go, qc_rules  # noqa: F401  (book is a fixture)
from test_report_assemble_bench import full  # noqa: F401  (fixture)

S2 = "b1.ch01.s2"


def writes(llm, sid):
    return [c for c in llm.calls if f"Write scene {sid} " in c["messages"][-1]["content"]]


def test_deleting_the_files_of_an_accepted_scene_does_not_make_it_get_rewritten(book):
    go(book, RuleLLM(qc_rules()))
    for f in scenefiles.scene_dir(book, SID).glob("*"):
        f.unlink()
    llm = RuleLLM(qc_rules())
    go(Project.open(book.root), llm)
    assert not writes(llm, SID)  # the status still says accepted: this is why `rewrite` exists


def test_rewrite_resets_the_scene_and_the_next_run_writes_it_again_even_while_the_voice_checkpoint_waits(book):
    go(book, RuleLLM(qc_rules()))
    p = Project.open(book.root)
    assert p.state.checkpoints["voice"].status == "waiting"
    old = scenefiles.final_path(p, SID).read_text()
    result = ops.rewrite_scenes(p, [SID])
    assert result == {"reset": [SID], "kept": [], "voice_reset": False}
    d = scenefiles.scene_dir(p, SID)
    assert not list(d.glob("draft-*.md")) and not (d / "final.md").exists() and not (d / "review.json").exists() and not (d / "deps.yaml").exists()
    assert Project.open(book.root).state.items[SID].status == "pending" and Project.open(book.root).state.items[S2].status == "accepted"
    llm = RuleLLM(qc_rules(overrides={SID: [prose(11, 22), prose(12, 22)]}))
    summary = go(Project.open(book.root), llm)
    assert len(writes(llm, SID)) == 2 and not writes(llm, S2)  # only the reset scene
    assert summary.stopped == "checkpoint"
    assert scenefiles.final_path(book, SID).read_text() != old and Project.open(book.root).state.items[SID].status == "accepted"


def test_a_whole_chapter_can_be_reset_and_what_was_observed_from_it_is_dropped(book):
    go(book, RuleLLM(qc_rules()))
    p = Project.open(book.root)
    assert any(o["at"] in (SID, S2) for t in store.load_tracks(p) for o in t.observed)
    result = ops.rewrite_scenes(p, ["b1.ch01"])
    assert result["reset"] == [SID, S2]
    assert not any(o["at"] in (SID, S2) for t in store.load_tracks(Project.open(book.root)) for o in t.observed)


def test_after_the_whole_book_is_done_a_rewrite_makes_the_prose_layer_unfinished_again(full):
    assert full.state.layers["prose"].status == "accepted"
    ops.rewrite_scenes(full, ["b1.ch03.s1"])
    p = Project.open(full.root)
    assert p.state.layers["prose"].status == "drafted" and p.state.items["b1.ch03.s1"].status == "pending"
    llm = RuleLLM(qc_rules())
    go(p, llm)
    assert len(writes(llm, "b1.ch03.s1")) == 2
    assert Project.open(full.root).state.layers["prose"].status == "accepted"


def test_text_you_wrote_is_not_discarded_without_force(book):
    d = scenefiles.scene_dir(book, SID)
    d.mkdir(parents=True)
    (d / "final.md").write_text(prose(3, 22))
    go(book, RuleLLM(qc_rules()))
    p = Project.open(book.root)
    assert json.loads(scenefiles.review_path(p, SID).read_text())["source"] == "adopted"
    kept = ops.rewrite_scenes(p, [SID, S2])
    assert kept == {"reset": [S2], "kept": [SID], "voice_reset": False} and scenefiles.final_path(p, SID).exists()
    assert ops.rewrite_scenes(Project.open(book.root), [SID], force=True)["reset"] == [SID]
    assert not scenefiles.final_path(book, SID).exists()


def test_unknown_targets_are_refused(book):
    with pytest.raises(BookforgeError) as e:
        ops.rewrite_scenes(book, ["b1.ch09.s9"])
    assert "not a scene or chapter" in str(e.value)


def test_the_rewrite_command(book):
    go(book, RuleLLM(qc_rules()))
    runner = CliRunner()
    out = runner.invoke(cli.app, ["rewrite", str(book.root), SID])
    assert out.exit_code == 0 and f"reset 1 scene(s): {SID}" in out.output and "Next: python -m bookforge run" in out.output
    assert runner.invoke(cli.app, ["rewrite", str(book.root), "nope"]).exit_code == 1
    assert "scene(s) reset for rewriting" in __import__("subprocess").run(["git", "-C", str(book.root), "log", "--format=%s", "-1"], capture_output=True, text=True).stdout


def test_the_rewrite_endpoint(full, monkeypatch):
    import main
    from fastapi.testclient import TestClient
    monkeypatch.setattr(main, "DATA_DIR", str(full.root.parent))
    r = TestClient(main.app).post("/api/series/series/books/b1/rewrite", json={"targets": ["b1.ch04"]})
    assert r.status_code == 200 and r.json()["data"]["reset"] == ["b1.ch04.s1", "b1.ch04.s2"]


# ── all scenes, a preview, and asking for the voice checkpoint again ─────────

def test_all_is_every_scene_of_the_book(book):
    go(book, RuleLLM(qc_rules()))
    all_ids = [s.id for s in store.load_scenes(book)]
    plan = ops.rewrite_plan(book, ["all"])
    assert plan["reset"] == all_ids and plan["kept"] == [] and sum(plan["by_status"].values()) == len(all_ids)
    assert ops.rewrite_plan(book, ["b1"])["reset"] == all_ids  # the book's own id means the same
    assert ops.rewrite_plan(book, ["b1.ch01"])["reset"] == [i for i in all_ids if i.startswith("b1.ch01.")]


def test_the_preview_changes_nothing_and_counts_scenes_by_status(book):
    go(book, RuleLLM(qc_rules()))
    before = load_state(book.state_path).items[SID].status
    plan = ops.rewrite_plan(book, ["b1.ch01"])
    assert plan["by_status"] == {before: len(plan["reset"])} and scenefiles.final_path(book, SID).exists()
    assert load_state(book.state_path).items[SID].status == before


def test_a_preview_names_the_scenes_with_your_own_text_unless_you_force(book):
    go(book, RuleLLM(qc_rules()))
    review = json.loads(scenefiles.review_path(book, SID).read_text())
    review["source"] = "adopted"
    scenefiles.review_path(book, SID).write_text(json.dumps(review))
    assert ops.rewrite_plan(book, ["b1.ch01"])["kept"] == [SID]
    assert ops.rewrite_plan(book, ["b1.ch01"], force=True)["kept"] == []


def test_unknown_targets_are_refused_and_say_what_works(book):
    with pytest.raises(BookforgeError, match="b1.ch01.s1, b1.ch01 or all"):
        ops.rewrite_plan(book, ["b9.ch99"])


def test_rewriting_chapter_one_can_ask_for_the_voice_checkpoint_again(book):
    go(book, RuleLLM(qc_rules()))
    p = Project.open(book.root)
    p.state.reach_checkpoint("voice")
    p.state.approve_checkpoint("voice")
    p.save_state()
    kept_approved = ops.rewrite_scenes(Project.open(book.root), ["b1.ch01"])
    assert kept_approved["voice_reset"] is False and load_state(book.state_path).checkpoints["voice"].status == "approved"
    p = Project.open(book.root)
    result = ops.rewrite_scenes(p, ["b1.ch01"], reset_voice=True)
    assert result["voice_reset"] is True and load_state(book.state_path).checkpoints["voice"].status == "pending"
    llm = RuleLLM(qc_rules())
    summary = go(Project.open(book.root), llm, until="prose")
    assert "voice" in summary.detail  # the run writes chapter 1 and waits for the voice checkpoint again


def test_the_voice_is_not_asked_for_again_when_chapter_one_is_not_rewritten(book):
    go(book, RuleLLM(qc_rules()))
    p = Project.open(book.root)
    p.state.reach_checkpoint("voice")
    p.state.approve_checkpoint("voice")
    p.save_state()
    result = ops.rewrite_scenes(Project.open(book.root), ["b1.ch02"], reset_voice=True)
    assert result["voice_reset"] is False and load_state(book.state_path).checkpoints["voice"].status == "approved"
