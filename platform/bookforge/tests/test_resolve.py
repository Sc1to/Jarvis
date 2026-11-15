"""Proposals for uncovered synopsis sentences, on b2's real synopsis and the real Inbox sentences."""

from pathlib import Path

from bookforge import resolve

SYN = (Path(__file__).parent / "fixtures" / "b2" / "synopsis.md").read_text(encoding="utf-8")

S_UPON = "Upon landing, Eli is immediately confronted by the harsh reality of the frontier."
S_DESTROY = "Halloway attempts to destroy the drive containing the evidence, but Mara, despite her fading mind, intervenes."
S_COGNITIVE = "Her cognitive decline has made her unpredictable, allowing her to outmaneuver Halloway's precise movements."
S_SAVE = "Eli realizes that he cannot save her; the medical supplies are insufficient, and the corporation will not provide aid to a worker who has become a liability."


def ev(i, text, excerpt=""):
    return dict(id=i, text=text, excerpt=excerpt or text, once_only=True, source="synopsis")


EVENTS = [ev("e12", "Mara is injured and her radiation sickness worsens", "Mara is injured in the struggle, her condition worsening as she succumbs to the radiation sickness that has plagued her for years."),
          ev("e13", "Eli cannot save Mara: the medical supplies are insufficient and the corporation will not give aid to a liability")]


def test_a_sentence_an_event_already_tells_in_other_words_widens_that_event():
    p = resolve.propose_coverage(None, SYN, S_SAVE[:60], EVENTS)
    assert p.outcome == "widen" and p.target == "e13" and p.label == "tool housekeeping" and "Widen the excerpt of e13" in p.answer and not p.applied and p.mode == "shadow"


def test_a_sentence_that_elaborates_the_event_before_it_is_attached_to_that_event():
    events = [ev("e9", "Mara intervenes when Halloway tries to destroy the drive", S_DESTROY)]
    p = resolve.propose_coverage(None, SYN, S_COGNITIVE[:60], events)
    assert p.outcome == "attach" and p.target == "e9" and "Attach this sentence to e9" in p.answer
    assert resolve.propose_coverage(None, SYN, S_COGNITIVE[:60], [ev("e1", "Eli arrives at the asteroid")]) is None  # nothing owns the sentence before it, and no model: no proposal


def test_the_model_step_sorts_description_from_change_and_must_name_the_words():
    def ask(**slots):
        if "harsh reality" in slots["sentence"]:
            return {"outcome": "commentary", "change": "", "words": "", "reason": "it describes the setting on arrival and nothing changes"}
        return {"outcome": "change", "change": "Halloway tries to destroy the evidence drive and Mara stops him", "words": "Halloway attempts to destroy the drive", "reason": "an action with a result"}
    waive = resolve.propose_coverage(None, SYN, S_UPON[:60], [ev("e1", "Eli arrives")], ask)
    assert waive.outcome == "waive" and "No event needed" in waive.answer and "no_event_needed" in waive.answer and waive.label == "tool housekeeping"
    new = resolve.propose_coverage(None, SYN, S_DESTROY[:60], [ev("e1", "Eli arrives")], ask)
    assert new.outcome == "new_event" and new.label == "proposal" and new.answer.startswith("Add an event: Halloway tries to destroy")  # never a housekeeping outcome


def test_an_answer_that_names_no_change_in_the_words_of_the_sentence_is_not_a_proposal():
    bad_words = {"outcome": "change", "change": "x", "words": "words that are not in the sentence", "reason": "r"}
    no_change = {"outcome": "change", "change": "", "words": "", "reason": "r"}
    inconsistent = {"outcome": "commentary", "change": "something happens", "words": "", "reason": "r"}
    for data in (bad_words, no_change, inconsistent, {"outcome": "maybe"}, {}):
        assert resolve.check_model_answer(data, S_DESTROY) is None
    assert resolve.check_model_answer({"outcome": "change", "change": "x", "words": "Halloway attempts to destroy the drive", "reason": ""}, S_DESTROY) == ("change", "x", "")


def test_every_sentence_of_the_real_inbox_can_be_located_from_its_shortened_quotation():
    for s in (S_UPON, S_DESTROY, S_COGNITIVE, S_SAVE, "The *Kestrel* is ready for launch, but the cost is high.",
              "The corporation buried the ship and the evidence to protect its structural stability, prioritizing the asset over the lives of the workers."):
        i = resolve.locate(SYN, s[:140])
        assert i is not None and resolve._flat(SYN)[i][1].startswith(s[:40].replace("*", "*"))
