import json
import subprocess

import pytest
from typer.testing import CliRunner

from bookforge import cli, scenefiles
from bookforge.bible import store
from bookforge.layers import HANDLERS
from bookforge.layers.prose import check_context
from bookforge.layers.runner import run
from bookforge.llm import LLMError
from bookforge.project import Project
from bookforge.state import load_state
from conftest import RuleLLM
from prose_fakes import prose
from structure_fakes import SMALL_CONFIG, ready, rules

PROSE_CONFIG = (SMALL_CONFIG.replace("research:", "  prose: {words: [100, 600], drafts: 2}\nresearch:")
                + "  judge_drafts: false\n  continuity_check: false\n  critic_check: false\n  extract_observed: false\n  max_revision_rounds: 0\n")
SCENES = [f"b1.ch0{c}.s{s}" for c in range(1, 5) for s in (1, 2)]
SUMMARY = "Anna meets Jonas on the quay and they quarrel about the ledger before they part for the night."
BANNED = "She felt a testament to her own stubbornness, a testament to everything."


def good(scene_id: str, draft: int) -> str:
    return prose((SCENES.index(scene_id) * 5 + draft * 7) % 30, 22)


def prose_rules(overrides=None):
    """Replies for every scene: two good drafts each, unless `overrides` gives a list of replies (strings or callables) for a scene."""
    overrides = {k: list(v) for k, v in (overrides or {}).items()}
    out = []
    for sid in SCENES:
        queue = overrides.get(sid)
        if queue is None:
            queue = [good(sid, 1), good(sid, 2)] * 3

        def reply(messages, queue=queue):
            item = queue.pop(0) if len(queue) > 1 else queue[0]
            return item(messages) if callable(item) else item

        out.append((f"Write scene {sid} as continuous", reply))
    out.append(("Summarise the scene below", SUMMARY))
    return out


@pytest.fixture
def book(project):
    """A small book with layers 1-6 done and the structure checkpoint approved: ready for prose."""
    p = ready(project)
    assert run(p, RuleLLM(rules()), HANDLERS).stopped == "checkpoint"
    p.state.approve_checkpoint("structure")
    p.save_state()
    (p.root / "config.yaml").write_text(PROSE_CONFIG)
    from bookforge import vcs
    vcs.commit(p.root, "test setup: structure approved, prose config")
    return Project.open(p.root)


def go(project, llm, until=None):
    return run(project, llm, HANDLERS, until=until)


def git(project, *args):
    return subprocess.run(["git", "-C", str(project.root), *args], capture_output=True, text=True).stdout


def review(project, sid):
    return json.loads(scenefiles.review_path(project, sid).read_text())


def scene_calls(llm, sid):
    return llm.calls_matching(f"Write scene {sid} as continuous")


# ── the voice checkpoint ────────────────────────────────────────────────────

def test_the_first_run_writes_chapter_one_and_stops_at_the_voice_checkpoint(book):
    llm = RuleLLM(prose_rules())
    summary = go(book, llm)
    assert summary.stopped == "checkpoint" and summary.exit_code == 0
    assert "reached the 'voice' checkpoint" in summary.detail and "approve voice" in summary.detail
    assert "books/b1/scenes/ch01/s1/final.md" in summary.detail and "books/b1/scenes/ch01/s2/final.md" in summary.detail
    assert "style/banned.txt" in summary.detail and "ch02" not in summary.detail
    assert len(llm.calls_matching("Write the scene described below")) == 4  # 2 scenes x 2 drafts
    assert len(llm.calls_matching("Summarise the scene below")) == 2
    state = load_state(book.state_path)
    assert state.checkpoints["voice"].status == "waiting" and state.layers["prose"].status == "drafted"
    assert [state.items[s].status for s in SCENES[:2]] == ["accepted", "accepted"] and SCENES[2] not in state.items


def test_each_scene_leaves_its_files_and_a_commit(book):
    go(book, RuleLLM(prose_rules()))
    d = scenefiles.scene_dir(book, "b1.ch01.s1")
    assert sorted(p.name for p in d.iterdir()) == ["deps.yaml", "draft-1.md", "draft-2.md", "final.md", "review.json", "summary.md"]
    assert (d / "summary.md").read_text().strip() == SUMMARY
    log = git(book, "log", "--format=%s").split("\n")
    assert log[:3] == ["b1.prose: drafted", "b1.ch01.s2: drafted, checked, accepted", "b1.ch01.s1: drafted, checked, accepted"]
    assert git(book, "status", "--porcelain").strip() == ""
    r = review(book, "b1.ch01.s1")
    assert r["source"] == "written" and r["chosen"] in ("draft-1", "draft-2") and r["summary_source"] == "model"
    assert set(r["mechanical"]) == {"draft-1", "draft-2"} and r["briefing_tokens"] > 0


def test_running_again_while_the_checkpoint_waits_does_nothing(book):
    go(book, RuleLLM(prose_rules()))
    llm = RuleLLM([])
    again = go(Project.open(book.root), llm)
    assert again.stopped == "checkpoint" and llm.calls == [] and "approve voice" in again.detail


def test_after_approval_the_rest_of_the_book_is_written_and_the_layer_accepted(book):
    go(book, RuleLLM(prose_rules()))
    p = Project.open(book.root)
    p.state.approve_checkpoint("voice")
    p.save_state()
    llm = RuleLLM(prose_rules())
    summary = go(Project.open(book.root), llm)
    assert summary.stopped == "complete" and summary.ran == ["prose"] and "8/8 scenes accepted" in summary.notes["prose"]
    assert len(llm.calls_matching("Write the scene described below")) == 12  # 6 scenes x 2 drafts: chapter 1 is not redone
    assert load_state(book.state_path).layers["prose"].status == "accepted"
    assert all(scenefiles.final_path(book, s).exists() for s in SCENES)


# ── choosing and flagging ───────────────────────────────────────────────────

def test_the_draft_with_fewer_problems_becomes_final(book):
    sid = "b1.ch01.s1"
    llm = RuleLLM(prose_rules({sid: [good(sid, 1) + " " + BANNED, good(sid, 2)]}))
    go(book, llm, until="prose")
    r = review(book, sid)
    assert r["chosen"] == "draft-2" and r["mechanical"]["draft-1"]["score"] >= 100 > r["mechanical"]["draft-2"]["score"]
    assert scenefiles.final_path(book, sid).read_text().strip() == good(sid, 2).strip()
    assert scenefiles.draft_path(book, sid, 1).exists()  # the rejected draft is kept


def test_the_first_draft_wins_a_tie(book):
    sid = "b1.ch01.s1"
    same = good(sid, 1)
    go(book, RuleLLM(prose_rules({sid: [same, same]})), until="prose")
    r = review(book, sid)
    assert r["mechanical"]["draft-1"]["score"] == r["mechanical"]["draft-2"]["score"] and r["chosen"] == "draft-1"


def test_a_scene_whose_best_draft_still_blocks_is_flagged_and_the_run_goes_on(book):
    sid = "b1.ch01.s1"
    bad = [good(sid, 1) + " " + BANNED] * 2
    llm = RuleLLM(prose_rules({sid: bad}))
    summary = go(book, llm)
    assert summary.stopped == "checkpoint"  # chapter 1 is done as far as it goes; the author reads it
    state = load_state(book.state_path)
    assert state.items[sid].status == "flagged" and "banned phrase: 'a testament to'" in state.items[sid].note
    assert state.items["b1.ch01.s2"].status == "accepted"
    assert not scenefiles.final_path(book, sid).exists() and scenefiles.draft_path(book, sid, 1).exists()
    r = review(book, sid)
    assert r["blocking"] and "summary_source" not in r
    assert git(book, "log", "--format=%s").split("\n")[:3] == ["b1.prose: drafted", "b1.ch01.s2: drafted, checked, accepted", f"{sid}: drafted, flagged"]
    assert len(llm.calls_matching("Summarise the scene below")) == 1  # no summary for the flagged scene


def test_flagged_scenes_make_the_layer_need_you_and_are_rewritten_on_the_next_run(book):
    sid = "b1.ch03.s1"
    go(book, RuleLLM(prose_rules()))
    p = Project.open(book.root)
    p.state.approve_checkpoint("voice")
    p.save_state()
    bad = RuleLLM(prose_rules({sid: [good(sid, 1) + " " + BANNED] * 2}))
    summary = go(Project.open(book.root), bad)
    assert summary.stopped == "failed" and summary.exit_code == 1 and sid in summary.detail and "needs you" in summary.detail
    assert load_state(book.state_path).layers["prose"].status == "flagged"
    assert load_state(book.state_path).items["b1.ch04.s2"].status == "accepted"  # the other scenes were not held up

    fixed = RuleLLM(prose_rules())
    again = go(Project.open(book.root), fixed)
    assert again.stopped == "complete" and again.ran == ["prose"]
    assert len(fixed.calls_matching("Write the scene described below")) == 2  # only the flagged scene, both drafts, again
    assert load_state(book.state_path).items[sid].status == "accepted"


@pytest.mark.parametrize("breaker,code", [
    (lambda t: "Sure! Here is the scene:\n\n" + t, "chatter"),
    (lambda t: t[: t.rindex(".")] + " and then she", "cut_off"),
    (lambda t: "# Scene 1\n\n" + t, "formatting"),
    (lambda t: t.split(".")[0] + ".", "length"),
])
def test_other_blocking_problems_also_flag_the_scene(book, breaker, code):
    sid = "b1.ch01.s1"
    llm = RuleLLM(prose_rules({sid: [breaker(good(sid, 1)), breaker(good(sid, 2))]}))
    go(book, llm, until="prose")
    assert load_state(book.state_path).items[sid].status == "flagged"
    assert code in json.dumps(review(book, sid)["mechanical"])


# ── resuming ────────────────────────────────────────────────────────────────

def test_a_crash_between_drafts_keeps_the_first_draft_and_a_rerun_does_not_redo_it(book):
    sid = "b1.ch01.s1"

    def offline(_):
        raise LLMError("colibri went away")

    broken = RuleLLM(prose_rules({sid: [good(sid, 1), offline]}))
    summary = go(book, broken, until="prose")
    assert summary.stopped == "failed" and "colibri went away" in summary.detail
    assert scenefiles.draft_path(book, sid, 1).exists() and not scenefiles.draft_path(book, sid, 2).exists()
    assert load_state(book.state_path).layers["prose"].status == "flagged"

    again = RuleLLM(prose_rules())
    assert go(Project.open(book.root), again, until="prose").stopped == "checkpoint"
    assert len(scene_calls(again, sid)) == 1  # only draft 2: draft 1 was reused


def test_progress_is_committed_scene_by_scene_even_when_a_later_scene_fails(book):
    def offline(_):
        raise LLMError("offline")

    llm = RuleLLM(prose_rules({"b1.ch01.s2": [offline]}))
    go(book, llm, until="prose")
    assert scenefiles.final_path(book, "b1.ch01.s1").exists()
    assert "b1.ch01.s1: drafted, checked, accepted" in git(book, "log", "--format=%s")


def test_a_hand_written_final_is_checked_and_adopted_without_drafts(book):
    sid = "b1.ch01.s1"
    d = scenefiles.scene_dir(book, sid)
    d.mkdir(parents=True)
    mine = prose(3, 22)
    (d / "final.md").write_text(mine)
    llm = RuleLLM(prose_rules())
    go(book, llm, until="prose")
    assert scene_calls(llm, sid) == []
    assert scenefiles.final_path(book, sid).read_text() == mine
    assert review(book, sid)["source"] == "adopted"
    assert f"{sid}: adopted, checked, accepted" in git(book, "log", "--format=%s")
    assert load_state(book.state_path).items[sid].status == "accepted"


def test_a_hand_written_final_that_fails_the_checks_is_flagged_and_left_alone(book):
    sid = "b1.ch01.s1"
    d = scenefiles.scene_dir(book, sid)
    d.mkdir(parents=True)
    mine = prose(3, 22) + " " + BANNED
    (d / "final.md").write_text(mine)
    llm = RuleLLM(prose_rules())
    go(book, llm, until="prose")
    assert scene_calls(llm, sid) == [] and (d / "final.md").read_text() == mine
    assert load_state(book.state_path).items[sid].status == "flagged"


# ── what the model is given ─────────────────────────────────────────────────

def test_the_model_gets_the_briefing_and_the_word_range(book):
    llm = RuleLLM(prose_rules())
    go(book, llm, until="prose")
    first = scene_calls(llm, "b1.ch01.s1")[0]
    system, user = first["messages"][0]["content"], first["messages"][1]["content"]
    assert "Return only the scene text" in system and "English" in system
    assert "Write scene b1.ch01.s1 as continuous prose of about 100 to 600 words" in user
    assert "Point of view: third-limited. Tense: past." in user
    assert "1. Something happens.\n2. Anna decides." in user and "## Series north star" in user
    assert first["role"] == "writer" and first["options"] == {"max_tokens": int(600 * 1.6) + 300, "draft": 0, "grow": False}
    assert scene_calls(llm, "b1.ch01.s1")[1]["options"]["draft"] == 1


def test_later_scenes_see_the_earlier_ones_text_and_summaries(book):
    llm = RuleLLM(prose_rules())
    go(book, llm, until="prose")
    second = scene_calls(llm, "b1.ch01.s2")[0]["messages"][1]["content"]
    final_one = scenefiles.final_path(book, "b1.ch01.s1").read_text().split()
    assert "The end of the previous scene (b1.ch01.s1), verbatim" in second and " ".join(final_one[-8:]) in second
    assert f"Earlier in this chapter (b1.ch01):\n  - b1.ch01.s1: {SUMMARY}" in second


def test_deps_are_written_for_every_drafted_scene(book):
    go(book, RuleLLM(prose_rules()), until="prose")
    text = scenefiles.deps_path(book, "b1.ch01.s2").read_text()
    assert text.startswith("scene: b1.ch01.s2@") and "previous:" in text and "b1.ch01.s1@" in text


def test_the_summary_falls_back_to_the_plan_when_the_model_fails(book):
    def offline(_):
        raise LLMError("offline")

    rules_ = [r for r in prose_rules() if "Summarise" not in r[0]] + [("Summarise the scene below", offline)]
    go(book, RuleLLM(rules_), until="prose")
    assert scenefiles.summary_path(book, "b1.ch01.s1").read_text().strip() == "Scene 1.1 changes things."
    assert review(book, "b1.ch01.s1")["summary_source"] == "plan"


def test_a_summary_of_the_wrong_length_is_corrected(book):
    (book.root / "config.yaml").write_text(PROSE_CONFIG.replace("max_revision_rounds: 0", "max_revision_rounds: 1"))
    book = Project.open(book.root)

    def reply(messages):
        return "Too short." if len(messages) == 2 else SUMMARY

    rules_ = [r for r in prose_rules() if "Summarise" not in r[0]] + [("Summarise the scene below", reply)]
    go(book, RuleLLM(rules_), until="prose")
    assert scenefiles.summary_path(book, "b1.ch01.s1").read_text().strip() == SUMMARY


def test_one_draft_per_scene_when_configured(book):
    (book.root / "config.yaml").write_text(PROSE_CONFIG.replace("drafts: 2", "drafts: 1"))
    llm = RuleLLM(prose_rules())
    go(Project.open(book.root), llm, until="prose")
    assert len(llm.calls_matching("Write the scene described below")) == 2
    assert not scenefiles.draft_path(book, "b1.ch01.s1", 2).exists()


def test_the_layer_needs_scenes_and_a_model(tmp_path, book):
    from bookforge.errors import LayerError
    from bookforge.layers.prose import prose as prose_layer
    from bookforge.layers.runner import StepContext
    with pytest.raises(LayerError, match="scenes.yaml is missing"):
        prose_layer(StepContext(ready(Project.create(tmp_path / "other", "A premise.")), "prose", RuleLLM([])))
    with pytest.raises(LayerError, match="no model client"):
        prose_layer(StepContext(book, "prose", None))


# ── the mechanical context ──────────────────────────────────────────────────

def test_the_check_context_uses_accepted_scenes_and_the_previous_tail(book):
    go(book, RuleLLM(prose_rules()), until="prose")
    scenes = store.load_scenes(book)
    ctx = check_context(book, scenes[2], scenes)  # b1.ch02.s1
    assert len(ctx.earlier_texts) == 2 and ctx.names == {"anna": "Anna Voss", "jonas": "Jonas Reil"}
    assert ctx.previous_tail.split()[-3:] == scenefiles.final_path(book, "b1.ch01.s2").read_text().split()[-3:]
    assert ctx.scene_words == (100, 600) and ctx.banned and ctx.pov_id == "anna"
    first = check_context(book, scenes[0], scenes)
    assert first.earlier_texts == [] and first.previous_tail is None


# ── through the CLI ─────────────────────────────────────────────────────────

def test_cli_flow_voice_checkpoint_then_the_rest(book, monkeypatch):
    llm = RuleLLM(prose_rules())
    monkeypatch.setattr(cli, "build_client", lambda p: llm)
    monkeypatch.setattr(cli, "build_web_client", lambda p: None)
    runner = CliRunner()
    first = runner.invoke(cli.app, ["run", str(book.root)])
    assert first.exit_code == 0 and "approve voice" in first.output and "scenes/ch01/s1/final.md" in first.output, first.output
    status = runner.invoke(cli.app, ["status", str(book.root)])
    assert "Prose: 8 scenes: 2 accepted, 6 pending" in status.output and "voice              waiting" in status.output

    assert runner.invoke(cli.app, ["approve", str(book.root), "voice"]).exit_code == 0
    assert "b1-voice-approved" in git(book, "tag", "--list")
    last = runner.invoke(cli.app, ["run", str(book.root)])
    assert last.exit_code == 0 and "accepted: prose (8/8 scenes accepted)" in last.output and "all layers accepted" in last.output
    assert "Prose: 8 scenes: 8 accepted" in runner.invoke(cli.app, ["status", str(book.root)]).output


def test_cli_briefing_and_check(book):
    go(book, RuleLLM(prose_rules()), until="prose")
    runner = CliRunner()
    b = runner.invoke(cli.app, ["briefing", str(book.root), "b1.ch01.s2"])
    assert b.exit_code == 0 and "b1.ch01.s2: about" in b.output and "Series north star" in b.output and "## " not in b.output
    full = runner.invoke(cli.app, ["briefing", str(book.root), "b1.ch01.s2", "--full"])
    assert "## This scene" in full.output and "1. Something happens." in full.output
    cut = runner.invoke(cli.app, ["briefing", str(book.root), "b1.ch01.s2", "--tokens", "100000"])
    assert "of 100000 tokens" in cut.output
    tiny = runner.invoke(cli.app, ["briefing", str(book.root), "b1.ch01.s2", "--tokens", "50"])
    assert tiny.exit_code == 1 and "over the budget of 50" in tiny.output

    ok = runner.invoke(cli.app, ["check", str(book.root), "b1.ch01.s1"])
    assert ok.exit_code == 0 and "b1.ch01.s1:" in ok.output and "dialogue" in ok.output
    bad_file = book.root / "bad.md"
    bad_file.write_text(prose(0, 22) + " " + BANNED)
    bad = runner.invoke(cli.app, ["check", str(book.root), "b1.ch01.s1", "--file", str(bad_file)])
    assert bad.exit_code == 1 and "[block] banned_phrase: banned phrase: 'a testament to'" in bad.output
    assert runner.invoke(cli.app, ["check", str(book.root), "b1.ch09.s1"]).exit_code == 1
    assert "has no text yet" in runner.invoke(cli.app, ["check", str(book.root), "b1.ch03.s1"]).output
