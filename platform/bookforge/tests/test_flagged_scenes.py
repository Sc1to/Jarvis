"""A flagged scene is revised with what was found, the author can dismiss or instruct, and the false-flag causes are gone."""

import json

import pytest
from typer.testing import CliRunner

from bookforge import cli, ops, scenefiles
from bookforge.errors import BookforgeError
from bookforge.qc import scene_notes
from bookforge.qc.revise import Flag, issue_text
from bookforge.state import load_state
from conftest import RuleLLM
from prose_fakes import prose  # noqa: F401
from qc_fakes import CONTINUITY, REVISE, continuity, reviser
from test_prose import good
from test_prose_qc import COMMON, SID, book, go, kinds, qc_rules, review  # noqa: F401

FACT = "Anna Voss: grey eyes"
DRAFTS = lambda: [good(SID, 1) + " " + COMMON, good(SID, 2) + " " + COMMON]  # noqa: E731
FLAGS = (CONTINUITY, continuity({"grey eyes": ("yes", 0.9, COMMON)}))  # always says the scene contradicts her grey eyes


def flag_the_scene(book):
    """Run until the first scene is flagged: the check keeps saying yes and the reviser changes nothing."""
    llm = RuleLLM(qc_rules(overrides={SID: DRAFTS()}, continuity=FLAGS, revise=(REVISE, reviser({}))))
    go(book, llm)
    assert load_state(book.state_path).items[SID].status == "flagged"
    assert not scenefiles.final_path(book, SID).exists()
    return llm


# ── specific prompts ────────────────────────────────────────────────────────

def test_a_contradiction_is_put_to_the_writer_with_the_words_the_fact_and_what_to_do():
    flag = Flag("continuity", "contradiction", "the scene contradicts a fixed fact: X", quote="her green eyes", fact="Anna Voss: grey eyes")
    text = issue_text(flag)
    assert 'The passage says "her green eyes", which contradicts this fixed fact: Anna Voss: grey eyes.' in text
    assert "Rewrite the passage so it agrees with the fact" in text and "change only what is needed" in text


def test_the_authors_instruction_is_added_to_the_problem():
    flag = Flag("continuity", "contradiction", "m", quote="q", fact="f", instruction="she dyes them, say so")
    assert issue_text(flag).endswith("The author says: she dyes them, say so")


def test_other_findings_keep_their_own_message():
    assert issue_text(Flag("mechanical", "banned_phrase", "banned phrase: 'x'")) == "- banned phrase: 'x'"


# ── a flagged scene is revised from its saved text first ────────────────────

def test_a_flagged_scene_is_revised_with_the_findings_before_it_is_written_again(book):
    flag_the_scene(book)
    log = []
    answers = {"n": 0}

    def reply(messages):
        answers["n"] += 1
        return (FLAGS[1] if answers["n"] == 1 else continuity())(messages)

    llm = RuleLLM(qc_rules(continuity=(CONTINUITY, reply), revise=(REVISE, reviser({"grey eyes": "tired eyes"}, log))))
    go(book, llm)
    assert "draft" not in kinds(llm)  # no new drafts: the saved text was revised
    assert 'The passage says "' in log[0]["prompt"] and f"contradicts this fixed fact: {FACT}" in log[0]["prompt"]
    assert load_state(book.state_path).items[SID].status == "accepted"
    assert "tired eyes" in scenefiles.final_path(book, SID).read_text()
    r = review(book)
    assert r["revised_after_flag"] is True and r["unresolved"] == []


def test_when_the_revision_does_not_work_the_scene_is_written_again_and_the_writer_is_told_what_was_wrong(book):
    flag_the_scene(book)
    llm = RuleLLM(qc_rules(overrides={SID: DRAFTS()}, continuity=FLAGS, revise=(REVISE, reviser({}))))
    go(book, llm)
    assert "draft" in kinds(llm)
    prompt = next(c["messages"][-1]["content"] for c in llm.calls if "Write the scene described below" in c["messages"][-1]["content"])
    assert "Problems found in the previous attempt at this scene" in prompt
    assert f"It contradicted this fixed fact: {FACT}" in prompt and f'(It said: "{COMMON}")' in prompt


def test_the_revision_of_saved_text_can_be_switched_off(book):
    flag_the_scene(book)
    book.config.qc.revise_flagged = False
    llm = RuleLLM(qc_rules(overrides={SID: DRAFTS()}, continuity=(CONTINUITY, continuity()), revise=(REVISE, reviser({}))))
    go(book, llm)
    assert kinds(llm)[0] == "draft"  # straight to a new draft, as before
    assert load_state(book.state_path).items[SID].status == "accepted"


# ── the author dismisses or instructs ───────────────────────────────────────

def test_a_dismissed_finding_is_not_asked_about_again_for_that_scene(book):
    flag_the_scene(book)
    notes = ops.decide_finding(book, SID, FACT, "dismiss")
    assert notes["dismissed"] == [FACT]
    llm = RuleLLM(qc_rules(overrides={SID: DRAFTS()}, continuity=FLAGS, revise=(REVISE, reviser({}))))
    go(book, llm)
    asked = " ".join(c["messages"][-1]["content"] for c in llm.calls_matching("against facts the author has fixed"))
    assert FACT not in asked and "Anna Voss: " in asked  # the other facts are still checked
    assert load_state(book.state_path).items[SID].status == "accepted"


def test_an_instruction_reaches_the_revision_and_the_next_draft(book):
    flag_the_scene(book)
    ops.decide_finding(book, SID, FACT, "instruct", "She dyes them: say so in the first line")
    log = []
    llm = RuleLLM(qc_rules(overrides={SID: DRAFTS()}, continuity=FLAGS, revise=(REVISE, reviser({}, log))))
    go(book, llm)
    assert "The author says: She dyes them: say so in the first line" in log[0]["prompt"]
    draft_prompt = next(c["messages"][-1]["content"] for c in llm.calls if "Write the scene described below" in c["messages"][-1]["content"])
    assert "The author says: She dyes them: say so in the first line" in draft_prompt


def test_notes_can_be_taken_back_and_are_kept_per_scene(book):
    flag_the_scene(book)
    ops.decide_finding(book, SID, FACT, "dismiss")
    assert scene_notes.path(book, SID).exists()
    assert ops.decide_finding(book, SID, FACT, "clear") == {"dismissed": [], "instructions": {}}
    assert not scene_notes.path(book, SID).exists()
    assert scene_notes.read(book, "b1.ch02.s1") == {"dismissed": [], "instructions": {}}


def test_a_finding_the_scene_does_not_have_is_refused(book):
    flag_the_scene(book)
    with pytest.raises(BookforgeError, match="not one of this scene's findings"):
        ops.decide_finding(book, SID, "Something else entirely", "dismiss")
    with pytest.raises(BookforgeError, match="action must be"):
        ops.decide_finding(book, SID, FACT, "ignore")
    with pytest.raises(BookforgeError, match="not a scene"):
        ops.decide_finding(book, "b1.ch99.s1", FACT, "dismiss")
    with pytest.raises(BookforgeError, match="write what the writer should do"):
        ops.decide_finding(book, SID, FACT, "instruct", "  ")


def test_the_finding_command(book):
    flag_the_scene(book)
    runner = CliRunner()
    out = runner.invoke(cli.app, ["finding", str(book.root), SID, "--question", FACT, "--instruct", "she dyes them"])
    assert out.exit_code == 0 and "0 dismissed, 1 instruction(s)" in out.output
    out = runner.invoke(cli.app, ["finding", str(book.root), SID, "--question", FACT, "--dismiss"])
    assert out.exit_code == 0 and "1 dismissed, 0 instruction(s)" in out.output
    assert runner.invoke(cli.app, ["finding", str(book.root), SID, "--question", FACT]).exit_code == 1  # nothing to do
    assert runner.invoke(cli.app, ["finding", str(book.root), SID, "--question", FACT, "--dismiss", "--clear"]).exit_code == 1


# ── the false-flag causes ───────────────────────────────────────────────────

def test_an_approved_decision_only_warns(book):
    from bookforge.bible import store as bible_store
    from bookforge.qc.continuity import build_questions
    from bookforge.research.notes import stores_for
    n = stores_for(book)["book"].add_need(layer="synopsis", question="How do the locks work?", stance="invent",
                                          rule="Locks in a vacuum fail if forced.", status="proposed")
    ops.decide_need(book, n.id, approve=True)
    scenes = bible_store.load_scenes(book)
    questions, _ = build_questions(book, next(s for s in scenes if s.id == SID), scenes)
    [q] = [q for q in questions if "Author's decision" in q.text]
    assert q.severity == "warn"


# ── one cut-off reply does not stop the book ────────────────────────────────

def test_a_scene_whose_writer_reply_stays_cut_off_is_flagged_and_the_run_goes_on(book):
    from bookforge.llm import TruncatedReply
    from test_prose import good as _good  # noqa: F401
    calls = {"n": 0}

    def cut(messages):
        calls["n"] += 1
        raise TruncatedReply("writer model reply was cut off at 5000 tokens (finish_reason=length), even after raising the limit 2 time(s)")

    llm = RuleLLM([("Write the scene described below", cut)] + qc_rules())
    go(book, llm)
    items = load_state(book.state_path).items
    first = items[SID]
    assert first.status == "flagged" and "the writer's reply was cut off" in first.note
    assert calls["n"] >= 2  # every scene was tried: the run did not stop at the first
