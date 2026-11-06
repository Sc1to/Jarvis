"""The critic: whole-scene scores (beats_covered, pacing) write the scene again once, with the critic's notes in the briefing."""

from bookforge.layers.prose import _problems_text
from bookforge.bible import store
from bookforge.state import load_state
from conftest import RuleLLM
from qc_fakes import CRITIC, REVISE, critic, reviser
from test_prose_qc import SID, book, first_scene, go, qc_rules, review  # noqa: F401

NOTES = "Problems found in the previous attempt at this scene"


def writes(llm, sid=SID):
    return [c for c in llm.calls if f"Write scene {sid} " in c["messages"][-1]["content"]]


def scene(book, sid=SID):
    return next(s for s in store.load_scenes(book) if s.id == sid)


def test_a_missing_beat_writes_the_scene_again_once_with_the_critics_notes(book):
    revise_log = []
    llm = RuleLLM(qc_rules(critic=(CRITIC, critic([{"beats_covered": 1}, {}], issue="the second beat never happens")),
                           revise=(REVISE, reviser({}, revise_log))))
    go(book, llm)
    assert len(writes(llm)) == 4  # two drafts, then two more with the notes
    first_pass_prompt = writes(llm)[0]["messages"][-1]["content"]
    again = writes(llm)[2]["messages"][-1]["content"]
    assert NOTES not in first_pass_prompt and NOTES in again
    assert "The critic scored beats_covered 1 (minimum 3): whether every planned beat happens, in order" in again
    assert '"' in again and "the second beat never happens" in again  # the quoted weak lines with what is wrong with them
    assert "Make every one of these beats happen on the page, in order: 1." in again
    r = review(book)
    assert r["rewrote_with_critic_notes"] is True and r["first_attempt_critic"]["scores"]["beats_covered"] == 1
    assert load_state(book.state_path).items[SID].status == "accepted"


def test_a_scene_is_not_patched_line_by_line_when_the_critic_says_the_whole_scene_is_the_problem(book):
    log = []
    llm = RuleLLM(qc_rules(critic=(CRITIC, critic([{"pacing": 2}, {}])), revise=(REVISE, reviser({" the ": " THE "}, log))))
    go(book, llm)
    assert len(writes(llm)) == 4 and log == []  # nothing was patched for the critic's lines: the scene was written again


def test_if_the_rewrite_is_also_marked_down_its_lines_are_patched_and_nothing_loops(book):
    log = []
    llm = RuleLLM(qc_rules(critic=(CRITIC, critic([{"beats_covered": 1}, {"beats_covered": 1}])), revise=(REVISE, reviser({" the ": " THE "}, log))))
    go(book, llm)
    assert len(writes(llm)) == 4  # one rewrite only, never a third round of drafts
    assert log  # the second attempt falls back to patching the critic's lines
    assert load_state(book.state_path).items[SID].status == "flagged"
    assert review(book)["rewrote_with_critic_notes"] is True


def test_a_low_score_about_a_line_level_criterion_is_still_patched_in_place(book):
    llm = RuleLLM(qc_rules(critic=(CRITIC, critic([{"show_dont_tell": 2}, {}])), revise=(REVISE, reviser({" the ": " THE "}))))
    go(book, llm)
    assert len(writes(llm)) == 2 and "rewrote_with_critic_notes" not in review(book)


def test_the_rewrite_can_be_switched_off(book):
    book.config.qc.critic_rewrite = False
    log = []
    llm = RuleLLM(qc_rules(critic=(CRITIC, critic([{"beats_covered": 1}, {}])), revise=(REVISE, reviser({" the ": " THE "}, log))))
    go(book, llm)
    assert len(writes(llm)) == 2 and log  # the old behaviour: patch the critic's lines


def test_a_scene_flagged_for_its_pacing_is_written_again_on_the_next_run_with_the_notes(book):
    flagged = RuleLLM(qc_rules(critic=(CRITIC, critic([{"pacing": 1}] * 4 + [{}])), revise=(REVISE, reviser({}))))
    go(book, flagged)
    assert load_state(book.state_path).items[SID].status == "flagged"
    log = []
    llm = RuleLLM(qc_rules(critic=(CRITIC, critic([{"pacing": 1}, {}])), revise=(REVISE, reviser({" the ": " THE "}, log))))
    go(book, llm)
    assert log == []  # the saved text was not patched line by line
    assert len(writes(llm)) == 2 and NOTES in writes(llm)[0]["messages"][-1]["content"]  # one rewrite, carrying the notes
    assert load_state(book.state_path).items[SID].status == "accepted"


def test_the_critic_block_is_in_the_notes_only_when_a_score_is_below_the_minimum(book):
    weak = {"criterion": "pacing", "quote": "She crossed the quay without hurrying at all", "issue": "nothing happens here"}
    low = {"critic": {"scores": {"pacing": 2, "voice": 4}, "weakest": [weak]}, "blocking": ["the critic scored pacing 2 (minimum 3)"]}
    text = _problems_text(book, scene(book), low)
    assert "The critic scored pacing 2 (minimum 3)" in text and '[pacing] "She crossed the quay without hurrying at all": nothing happens here' in text
    assert text.count("the critic scored") == 0  # the one-line reason is replaced by the detail
    fine = {"critic": {"scores": {"pacing": 3, "voice": 4}, "weakest": [weak]}}
    assert _problems_text(book, scene(book), fine) == ""
