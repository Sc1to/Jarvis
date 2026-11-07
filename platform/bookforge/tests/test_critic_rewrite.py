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


# ── accepting the reasons a scene is flagged ─────────────────────────────────

def critic_flagged(book):
    llm = RuleLLM(qc_rules(critic=(CRITIC, critic([{"beats_covered": 1}] * 9)), revise=(REVISE, reviser({}))))
    go(book, llm)
    assert load_state(book.state_path).items[SID].status == "flagged"
    return llm


def test_each_reason_a_scene_is_flagged_for_is_listed_on_its_own(book):
    from bookforge import ops
    critic_flagged(book)
    reasons = ops.flag_reasons(book, SID)
    assert [(r["key"], r["kind"], r["accepted"]) for r in reasons] == [("critic:beats_covered", "critic", False)]
    assert reasons[0]["message"] == "the critic scored beats_covered 1 (minimum 3)"


def test_a_reason_can_be_accepted_and_the_scene_is_kept_as_written_not_written_again(book):
    from bookforge import ops, scenefiles
    critic_flagged(book)
    kept = scenefiles.best_text(book, SID)
    ops.accept_reason(book, SID, "critic:beats_covered", "the debt is existing, not hereditary: fine")
    llm = RuleLLM(qc_rules(critic=(CRITIC, critic([{"beats_covered": 1}] * 9)), revise=(REVISE, reviser({}))))
    go(book, llm)
    assert load_state(book.state_path).items[SID].status == "accepted"
    assert not writes(llm)  # the scene was not written again
    assert scenefiles.read(scenefiles.final_path(book, SID)).strip() == kept.strip()
    r = review(book)
    assert r["accepted_reasons"]["critic:beats_covered"]["note"].startswith("the debt is existing") and r["reason_items"] == []


def test_accepting_one_reason_leaves_the_others_standing(book):
    from bookforge import ops
    from bookforge.qc import scene_notes
    llm = RuleLLM(qc_rules(critic=(CRITIC, critic([{"beats_covered": 1, "dialogue": 1}] * 9)), revise=(REVISE, reviser({}))))
    go(book, llm)
    keys = [r["key"] for r in ops.flag_reasons(book, SID)]
    assert keys == ["critic:dialogue", "critic:beats_covered"] or sorted(keys) == ["critic:beats_covered", "critic:dialogue"]
    ops.accept_reason(book, SID, "critic:beats_covered")
    go(book, RuleLLM(qc_rules(critic=(CRITIC, critic([{"beats_covered": 1, "dialogue": 1}] * 9)), revise=(REVISE, reviser({})))))
    assert load_state(book.state_path).items[SID].status == "flagged"
    assert [r["key"] for r in ops.flag_reasons(book, SID)] == ["critic:dialogue"]
    assert list(scene_notes.read(book, SID)["accepted"]) == ["critic:beats_covered"]


def test_accepting_is_refused_for_a_scene_that_is_not_flagged_or_for_a_reason_it_does_not_have(book):
    import pytest
    from bookforge import ops
    from bookforge.errors import BookforgeError
    with pytest.raises(BookforgeError, match="not flagged"):
        ops.accept_reason(book, SID, "critic:beats_covered")
    critic_flagged(book)
    with pytest.raises(BookforgeError, match="not one of this scene's reasons"):
        ops.accept_reason(book, SID, "critic:pacing")


def test_an_acceptance_can_be_taken_back(book):
    from bookforge import ops
    from bookforge.qc import scene_notes
    critic_flagged(book)
    ops.accept_reason(book, SID, "critic:beats_covered")
    assert scene_notes.read(book, SID)["accepted"]
    ops.undo_accept_reason(book, SID, "critic:beats_covered")
    assert scene_notes.read(book, SID)["accepted"] == {}


def test_a_continuity_finding_can_be_accepted_like_any_other_reason(book):
    from bookforge import ops, scenefiles
    from test_flagged_scenes import FACT, flag_the_scene
    flag_the_scene(book)
    kept = scenefiles.best_text(book, SID)
    [reason] = ops.flag_reasons(book, SID)
    assert reason["kind"] == "continuity" and reason["key"] == f"continuity:{FACT}"
    ops.accept_reason(book, SID, reason["key"], "she wears contacts")
    from test_flagged_scenes import DRAFTS, FLAGS
    from qc_fakes import REVISE, reviser
    go(book, RuleLLM(qc_rules(overrides={SID: DRAFTS()}, continuity=FLAGS, revise=(REVISE, reviser({})))))
    assert load_state(book.state_path).items[SID].status == "accepted"
    assert scenefiles.read(scenefiles.final_path(book, SID)).strip() == kept.strip()


def test_a_mechanical_problem_can_be_accepted_and_is_then_neither_revised_nor_blocking(book):
    from bookforge import ops, scenefiles
    from test_prose import BANNED, good
    bad = good(SID, 1) + " " + BANNED
    rules = lambda: qc_rules(overrides={SID: [bad, bad]}, revise=(REVISE, reviser({"unrelated": "x"})))  # noqa: E731  never fixes it
    go(book, RuleLLM(rules()))
    [reason] = [r for r in ops.flag_reasons(book, SID)]
    assert reason["kind"] == "mechanical" and "banned phrase" in reason["message"]
    ops.accept_reason(book, SID, reason["key"], "the phrase is a quotation")
    log = []
    go(book, RuleLLM(qc_rules(overrides={SID: [bad, bad]}, revise=(REVISE, reviser({" the ": " THE "}, log)))))
    assert load_state(book.state_path).items[SID].status == "accepted" and not log  # nothing was revised for the accepted reason
    assert BANNED in scenefiles.read(scenefiles.final_path(book, SID))


def test_the_critics_beat_verdicts_are_kept_only_when_well_formed():
    from bookforge.qc.critic import clean_beats
    raw = [{"beat": 2, "verdict": "Out of order", "note": "comes first"}, {"beat": 9, "verdict": "shown"}, {"beat": 1, "verdict": "maybe"},
           {"beat": True, "verdict": "shown"}, "junk", {"beat": 1, "verdict": "missing", "note": " no  debt "}]
    assert clean_beats(raw, 3) == [{"beat": 1, "verdict": "missing", "note": "no debt"}, {"beat": 2, "verdict": "out_of_order", "note": "comes first"}]
    assert clean_beats(None, 3) == []
