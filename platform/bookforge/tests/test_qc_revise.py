import pytest

from bookforge.bible import store
from bookforge.errors import LayerError
from bookforge.layers.runner import StepContext
from bookforge.llm import LLMError
from bookforge.qc.extract import Extraction, extract_observed, record_observed
from bookforge.qc.revise import Flag, locate, paragraphs, revise_text
from conftest import RuleLLM
from prose_fakes import prose
from qc_fakes import EXTRACT, REVISE, extractor, reviser
from test_qc_checks import book, ctx_for, scene_of  # noqa: F401  (fixtures and helpers)

TEXT = "First paragraph, calm and plain, ends here.\n\nSecond paragraph has a testament to her will in it.\n\nThird paragraph closes the scene quietly."


# ── locating ────────────────────────────────────────────────────────────────

def test_paragraph_spans():
    spans = paragraphs(TEXT)
    assert [TEXT[s:e].split()[0] for s, e in spans] == ["First", "Second", "Third"]
    assert paragraphs("") == [] and paragraphs("one\n \ntwo") == [(0, 3), (6, 9)]


def test_a_flag_is_located_by_span_or_by_quote():
    spans = paragraphs(TEXT)
    start = TEXT.index("a testament")
    assert locate(TEXT, spans, Flag("mechanical", "banned_phrase", "m", start=start, end=start + 11)) == 1
    assert locate(TEXT, spans, Flag("critic", "c", "m", quote="closes the scene quietly")) == 2
    assert locate(TEXT, spans, Flag("critic", "c", "m", quote="Second   paragraph\nhas a")) == 1  # whitespace differences are fine
    assert locate(TEXT, spans, Flag("critic", "c", "m", quote="not in the text")) is None
    assert locate(TEXT, spans, Flag("continuity", "c", "m")) is None
    assert locate(TEXT, spans, Flag("mechanical", "cut_off", "m", start=len(TEXT) + 50)) == 2  # clamped to the end


# ── revising ────────────────────────────────────────────────────────────────

def banned_flag():
    start = TEXT.index("a testament")
    return Flag("mechanical", "banned_phrase", "banned phrase: 'a testament to'", start=start, end=start + 14)


def test_only_the_flagged_paragraph_is_replaced(book):
    log = []
    llm = RuleLLM([(REVISE, reviser({"a testament to her will": "proof of her will"}, log))])
    rev = revise_text(ctx_for(book, llm), TEXT, [banned_flag()], ["a testament to"], "t")
    assert rev.text == TEXT.replace("a testament to her will", "proof of her will")
    assert rev.unfixed == [] and len(llm.calls) == 1 and llm.calls[0]["role"] == "writer"
    prompt = log[0]["prompt"]
    assert "banned phrase: 'a testament to'" in prompt and "First paragraph, calm and plain" in prompt and "Third paragraph closes" in prompt
    assert rev.applied[0]["paragraph"] == 1 and rev.applied[0]["mode"] == "rewrite" and rev.applied[0]["flags"] == ["banned_phrase"]


def test_several_flags_in_one_paragraph_cost_one_call(book):
    llm = RuleLLM([(REVISE, reviser({"a testament to": "proof of", "in it": "inside"}))])
    two = [banned_flag(), Flag("critic", "critic:pacing", "too slow (criterion pacing: x)", quote="has a testament to her will")]
    rev = revise_text(ctx_for(book, llm), TEXT, two, ["a testament to"], "t")
    assert len(llm.calls) == 1 and "- banned phrase" in llm.calls[0]["messages"][1]["content"] and "- too slow" in llm.calls[0]["messages"][1]["content"]
    assert "proof of her will inside" in rev.text


def test_flags_in_different_paragraphs_are_fixed_separately_and_in_place(book):
    llm = RuleLLM([(REVISE, reviser({"calm and plain": "quiet", "closes the scene quietly": "ends the scene"}))])
    flags = [Flag("critic", "c", "m", quote="calm and plain"), Flag("critic", "c", "m", quote="closes the scene quietly")]
    rev = revise_text(ctx_for(book, llm), TEXT, flags, [], "t")
    assert len(llm.calls) == 2
    assert rev.text == TEXT.replace("calm and plain", "quiet").replace("closes the scene quietly", "ends the scene")
    assert [a["paragraph"] for a in rev.applied] == [0, 2]


def test_a_flag_that_cannot_be_located_is_returned_unfixed(book):
    llm = RuleLLM([(REVISE, reviser({}))])
    nowhere = Flag("continuity", "contradiction", "clash", quote="words that are not there")
    rev = revise_text(ctx_for(book, llm), TEXT, [nowhere], [], "t")
    assert rev.text == TEXT and rev.unfixed == [nowhere] and llm.calls == [] and rev.applied == []


def test_chatter_is_deleted_not_rewritten(book):
    text = "Sure! Here is the scene:\n\n" + TEXT
    llm = RuleLLM([])
    flag = Flag("mechanical", "chatter", "starts with a remark", start=0, end=24)
    rev = revise_text(ctx_for(book, llm), text, [flag], [], "t")
    assert rev.text == TEXT and llm.calls == [] and rev.applied[0]["mode"] == "delete"


def test_a_long_chatter_paragraph_is_rewritten_rather_than_deleted(book):
    long_para = "Sure! " + "This is a very long remark that is really part of the story. " * 8
    text = long_para + "\n\n" + TEXT
    llm = RuleLLM([(REVISE, reviser({"Sure! ": ""}))])
    rev = revise_text(ctx_for(book, llm), text, [Flag("mechanical", "chatter", "m", start=0, end=6)], [], "t")
    assert len(llm.calls) == 1 and not rev.text.startswith("Sure")


def test_a_revision_that_keeps_the_banned_phrase_is_sent_back(book):
    answers = iter(["Second paragraph has a testament to her will in it.", "Second paragraph has proof of her will in it."])
    llm = RuleLLM([(REVISE, lambda m: next(answers))])
    rev = revise_text(ctx_for(book, llm), TEXT, [banned_flag()], ["a testament to"], "t")
    assert "proof of her will" in rev.text and len(llm.calls) == 2
    assert "still contains a banned phrase" in llm.calls[1]["messages"][-1]["content"]


@pytest.mark.parametrize("reply,needle", [
    ("Tiny.", "close to the original"),
    ("word " * 60, "close to the original"),
    ("# Heading\n\nSecond paragraph rewritten with enough words in it to pass.", "plain prose"),
])
def test_revisions_that_change_size_or_add_formatting_are_rejected(book, reply, needle):
    llm = RuleLLM([(REVISE, reply)])
    with pytest.raises(LayerError, match="still has problems"):
        revise_text(ctx_for(book, llm), TEXT, [banned_flag()], [], "t")
    assert needle in llm.calls[1]["messages"][-1]["content"]


def test_a_failing_model_raises_so_the_scene_can_be_retried(book):
    def offline(_):
        raise LLMError("offline")

    with pytest.raises(LLMError):
        revise_text(ctx_for(book, RuleLLM([(REVISE, offline)])), TEXT, [banned_flag()], [], "t")


def test_the_first_and_last_paragraphs_have_context_placeholders(book):
    log = []
    llm = RuleLLM([(REVISE, reviser({}, log))])
    revise_text(ctx_for(book, llm), TEXT, [Flag("critic", "c", "m", quote="First paragraph, calm")], [], "t")
    assert "(start of the scene)" in log[0]["prompt"]
    log.clear()
    revise_text(ctx_for(book, RuleLLM([(REVISE, reviser({}, log))])), TEXT, [Flag("critic", "c", "m", quote="Third paragraph closes")], [], "t")
    assert "(end of the scene)" in log[0]["prompt"]


# ── extraction of observed states ───────────────────────────────────────────

SCENE_TEXT = prose(0, 16)


def test_every_planned_state_is_observed_with_real_evidence(book):
    scenes = store.load_scenes(book)
    ex = extract_observed(ctx_for(book, RuleLLM([(EXTRACT, extractor())])), scene_of(book, "b1.ch04.s1"), scenes, SCENE_TEXT)
    assert ex.error is None and {o["track"] for o in ex.observations} == {"anna-wound", "jonas-knows"} and ex.gaps == []
    wound = next(o for o in ex.observations if o["track"] == "anna-wound")
    assert wound["planned"] == "healed; scar remains" and wound["matches_plan"] is True and wound["evidence"] in " ".join(SCENE_TEXT.split())


def test_a_difference_from_the_plan_is_a_gap(book):
    ex = extract_observed(ctx_for(book, RuleLLM([(EXTRACT, extractor(gap="anna-wound"))])), scene_of(book, "b1.ch04.s1"),
                          store.load_scenes(book), SCENE_TEXT)
    assert [g["track"] for g in ex.gaps] == ["anna-wound"] and ex.gaps[0]["observed"] == "something else"


def test_evidence_that_is_not_in_the_scene_is_dropped_and_so_is_the_verdict(book):
    import json

    def reply(messages):
        return json.dumps({"observations": [{"track": t, "observed": "x", "matches_plan": False, "evidence": "invented evidence words here"}
                                            for t in ("anna-wound", "jonas-knows")]})

    ex = extract_observed(ctx_for(book, RuleLLM([(EXTRACT, reply)])), scene_of(book, "b1.ch04.s1"), store.load_scenes(book), SCENE_TEXT)
    assert all(o["evidence"] == "" and o["matches_plan"] is None for o in ex.observations) and ex.gaps == []


def test_a_scene_with_no_tracked_states_needs_no_call(book):
    store.save_tracks(book, [])
    llm = RuleLLM([])
    ex = extract_observed(ctx_for(book, llm), scene_of(book, "b1.ch02.s1"), store.load_scenes(book), SCENE_TEXT)
    assert ex.observations == [] and ex.gaps == [] and llm.calls == []


def test_extraction_problems_do_not_raise(book):
    def offline(_):
        raise LLMError("offline")

    ex = extract_observed(ctx_for(book, RuleLLM([(EXTRACT, offline)])), scene_of(book, "b1.ch04.s1"), store.load_scenes(book), SCENE_TEXT)
    assert "offline" in ex.error and ex.observations == []


def test_observations_are_recorded_in_the_tracks_and_replaced_not_duplicated(book):
    ex = Extraction(observations=[{"track": "anna-wound", "planned": "p", "observed": "first", "matches_plan": True, "evidence": "e"}])
    record_observed(book, "b1.ch04.s1", ex)
    ex2 = Extraction(observations=[{"track": "anna-wound", "planned": "p", "observed": "second", "matches_plan": None, "evidence": ""}])
    record_observed(book, "b1.ch04.s1", ex2)
    record_observed(book, "b1.ch04.s2", ex)
    wound = next(t for t in store.load_tracks(book) if t.id == "anna-wound")
    assert [(o["at"], o["value"]) for o in wound.observed] == [("b1.ch04.s1", "second"), ("b1.ch04.s2", "first")]
    record_observed(book, "b1.ch04.s3", Extraction())  # nothing to record: no change
    assert len(next(t for t in store.load_tracks(book) if t.id == "anna-wound").observed) == 2
