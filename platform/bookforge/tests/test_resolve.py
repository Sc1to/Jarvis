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


def test_in_assist_mode_the_ledger_parse_attaches_elaborating_and_already_told_sentences_but_not_what_you_took_back(project_with_ledger):
    from bookforge import answers
    from bookforge.layers.ledger import parse_ledger
    import copy
    p = project_with_ledger
    p.config.ledger.min_chapters = 1
    syn = ("Mara pries the hatch open and finds a data drive in the crust.\n\n"
           "Halloway attempts to destroy the drive, but Mara intervenes. Her cognitive decline has made her unpredictable, allowing her to outmaneuver Halloway's precise movements.\n\n"
           "Mara sails free with her debt cleared and the harbor behind her.")
    text = ("events:\n"
            "  - {id: e1, text: Mara finds a data drive, excerpt: 'Mara pries the hatch open and finds a data drive in the crust.', once_only: true, after: [], kind: event, weight: 2, source: synopsis}\n"
            "  - {id: e2, text: Mara stops Halloway destroying the drive, excerpt: 'Halloway attempts to destroy the drive, but Mara intervenes.', once_only: true, after: [e1], kind: event, weight: 2, source: synopsis}\n"
            "  - {id: e3, text: Mara sails free, excerpt: 'Mara sails free with her debt cleared and the harbor behind her.', once_only: true, after: [e2], kind: event, weight: 2, ending: true, source: synopsis}\n")

    def uncovered(project):
        led, problems, findings = parse_ledger(text, syn, project)
        return [f for f in findings if f.code == "sentence_not_covered"], led
    shadow, _ = uncovered(p)
    assert len(shadow) == 1 and "cognitive decline" in shadow[0].message  # shadow mode: the tool changes nothing
    answers.set_mode(p, "assist")
    assisted, led = uncovered(p)
    assert assisted == [] and led is not None
    assert led.events[1].also == ["Her cognitive decline has made her unpredictable, allowing her to outmaneuver Halloway's precise movements."]
    answers.take_back(p, "Her cognitive decline has made her unpredictable, allowing her to outmaneuver Halloway's precise movements.")  # undo
    again, _ = uncovered(p)
    assert len(again) == 1  # the tool leaves what you took back alone


def test_a_suggestion_you_accepted_attaches_the_sentence_even_in_shadow_mode(project_with_ledger):
    from bookforge import answers
    from bookforge.layers.ledger import parse_ledger
    p = project_with_ledger
    p.config.ledger.min_chapters = 1
    sentence = "Her cognitive decline has made her unpredictable, allowing her to outmaneuver Halloway's precise movements."
    syn = "Halloway attempts to destroy the drive, but Mara intervenes. " + sentence + "\n\nMara sails free with her debt cleared and the harbor behind her."
    text = ("events:\n"
            "  - {id: e2, text: Mara stops Halloway destroying the drive, excerpt: 'Halloway attempts to destroy the drive, but Mara intervenes.', once_only: true, after: [], kind: event, weight: 2, source: synopsis}\n"
            "  - {id: e3, text: Mara sails free, excerpt: 'Mara sails free with her debt cleared and the harbor behind her.', once_only: true, after: [e2], kind: event, weight: 2, ending: true, source: synopsis}\n")
    assert answers.load(p)["mode"] == "shadow"
    led, _, findings = parse_ledger(text, syn, p)
    assert any(f.code == "sentence_not_covered" for f in findings)  # shadow: nothing is attached on its own
    answers.accept_sentence(p, sentence)
    led, problems, findings = parse_ledger(text, syn, p)
    assert not any(f.code == "sentence_not_covered" for f in findings) and led.events[0].also == [sentence]
