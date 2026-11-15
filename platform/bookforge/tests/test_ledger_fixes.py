"""Ledger checks added after b2: sentence-level coverage, causal order, one ending and one decision, weights that discriminate."""

import copy

from bookforge.validators import HARD, ledger as L


def ev(i, text, excerpt=None, **kw):
    base = dict(id=i, text=text, excerpt=excerpt or text, once_only=True, after=[], kind="event", weight=2, pov="", ending=False, decision=False, pays_off="", source="synopsis")
    return {**base, **kw}


def codes(findings, severity=None):
    return {f.code for f in findings if severity is None or f.severity == severity}


SYN = ("Eli finds a drive in the cargo hold and reads what the corporation hid about the mines.\n\n"
       "The foreman seals the sector. They allow Eli to escape, but only on the condition that he signs a gag agreement.")


def test_a_dropped_sentence_inside_a_covered_paragraph_is_found_by_sentence_not_paragraph():
    events = [ev("e1", "Eli finds a drive", "Eli finds a drive"), ev("e2", "The foreman seals the sector", "The foreman seals the sector")]
    found = [f for f in L.check_ledger(events, SYN) if f.code == "sentence_not_covered"]
    assert any("They allow Eli to escape" in f.message for f in found) and any("reads what the corporation hid" in f.message for f in found)
    assert not any("seals the sector" in f.message and "They allow" not in f.message for f in found)  # the sentence an event quotes is covered


def test_a_condition_listed_after_what_it_conditions_is_caught_and_the_right_order_passes():
    escape = ev("e14", "Eli escapes the sector", "Eli escapes the sector")
    grant = ev("e15", "They allow Eli to escape on condition that he signs", "They allow Eli to escape, but only on the condition that he signs a gag agreement")
    bad = L.causal_order([escape, grant])
    assert bad and bad[0].code == "causal_order" and bad[0].items == ["e15", "e14"] and "listed after" in bad[0].message
    assert L.causal_order([grant, escape]) == []


def test_a_cause_listed_after_its_effect_is_caught():
    effect = ev("e3", "The sector is sealed", "The sector is sealed because the foreman found the broadcast")
    cause = ev("e4", "The foreman found the broadcast", "the foreman found the broadcast")
    assert any(f.code == "causal_order" for f in L.causal_order([effect, cause])) and L.causal_order([cause, effect]) == []


def test_exactly_one_ending_and_at_most_one_decision():
    events = [ev(f"e{i}", f"event number {i} happens") for i in range(1, 7)]
    events[3].update(ending=True)
    events[5].update(ending=True)
    c = codes(L.check_ledger(events), HARD)
    assert "several_endings" in c
    events[3]["ending"] = False
    events[1].update(decision=True)
    events[2].update(decision=True)
    assert "several_decisions" in codes(L.check_ledger(events), HARD) and "several_endings" not in codes(L.check_ledger(events), HARD)


def test_the_last_acts_turning_point_must_be_the_decision_or_the_ending_not_a_transition():
    events = [ev("e1", "a"), ev("e2", "b"), ev("e3", "Eli launches and leaves the sector"), ev("e4", "Eli chooses to broadcast", decision=True), ev("e5", "the corporation signs a deal", ending=True)]
    acts = [dict(id="b2.act1", events=["e1", "e2"], turning_point_event="e2", chapter_count=2), dict(id="b2.act2", events=["e3", "e4", "e5"], turning_point_event="e3", chapter_count=3)]
    assert "final_turning_point_is_transition" in codes(L.check_acts(acts, events), HARD)
    acts[1]["turning_point_event"] = "e4"
    assert "final_turning_point_is_transition" not in codes(L.check_acts(acts, events))


def test_weights_that_say_nothing_are_refused():
    flat = [ev(f"e{i}", f"event {i}", weight=2) for i in range(1, 9)]
    assert any(f.code == "weights_flat" and f.severity == HARD for f in L.weights_flat(flat))
    varied = copy.deepcopy(flat)
    for e in varied[:3]:
        e["weight"] = 1
    for e in varied[3:5]:
        e["weight"] = 3
    assert L.weights_flat(varied) == [] and L.weights_flat(flat[:4]) == []  # a short ledger is not judged


def act(i, events, n, reason, tp=None):
    return dict(id=f"b2.act{i}", events=events, chapter_count=n, sizing_reason=reason, turning_point_event=tp or events[-1], turning_point="x")


def test_an_acts_own_text_must_agree_with_its_numbers():
    events = [ev(f"e{i}", f"event {i}", weight=w) for i, w in enumerate([3, 2, 3, 1], 1)]  # weight 9
    wrong = act(1, ["e1", "e2", "e3", "e4"], 6, "weight 8 over 4 events, so about 8 chapters [computed: weight 9 over 4 events, about 4.5 chapters at 2 weight per chapter]")
    found = [f for f in L.sizing_consistency([wrong], events) if f.code == "sizing_reason_mismatch"]
    assert len(found) == 2 and any("weight 8" in f.message for f in found) and any("8 chapters" in f.message for f in found)
    ok = act(1, ["e1", "e2", "e3", "e4"], 5, "weight 9 over 4 events: about 5 chapters")
    assert L.sizing_consistency([ok], events) == []
    deliberate = act(1, ["e1", "e2", "e3", "e4"], 3, "override: two events are one scene in practice; about 8 chapters would pad")
    assert L.sizing_consistency([deliberate], events) == []


def test_the_acts_must_add_up_to_about_what_the_ledger_estimated():
    a1, a2 = act(1, ["e1"], 6, "x"), act(2, ["e2"], 6, "x")
    found = L.acts_vs_capacity([a1, a2], 21.5)
    assert found and found[0].code == "acts_differ_from_capacity" and found[0].severity == HARD and "12" in found[0].message and "21.5" in found[0].message
    assert L.acts_vs_capacity([a1, a2], 13) == [] and L.acts_vs_capacity([a1, a2], None) == []
    assert L.acts_vs_capacity([a1, dict(a2, sizing_reason="override: the second act is short on purpose")], 21.5) == []


def test_a_book_whose_chapters_are_one_synopsis_sentence_each_is_reported():
    events = [ev(f"e{i}", f"event {i}") for i in range(1, 7)] + [ev("e2.1", "a local setback", source="derived", parent="e2")]
    one_each = [dict(id=f"b2.ch{i:02d}", events_covered=[f"e{i}"]) for i in range(1, 7)]
    found = L.thin_chapters(one_each, events)
    assert found and found[0].code == "chapters_one_sentence_each" and found[0].severity == "soft" and "6 of 6" in found[0].message
    richer = [dict(id="b2.ch01", events_covered=["e1"]), dict(id="b2.ch02", events_covered=["e2", "e2.1"]), dict(id="b2.ch03", events_covered=["e3"], events_continued=["e2"]),
              dict(id="b2.ch04", events_covered=["e4", "e5"])]
    assert L.thin_chapters(richer, events) == [] and L.one_sentence_chapters(richer, events) == ["b2.ch01"]


SYN2 = ("Mara pries the hatch open and finds a data drive hidden in the asteroid’s crust.\n\n"
        "The corporation has turned the asteroid into a closed economic loop where workers are paid in scrip valid only at company stores.\n\n"
        "Halloway intercepts them at the launch bay, armed with a plasma cutter and backed by automated drones.")


def test_a_typographic_apostrophe_does_not_make_an_excerpt_a_misquotation():
    events = [ev("e1", "Mara finds a drive", "Mara pries the hatch open and finds a data drive hidden in the asteroid's crust")]  # a plain apostrophe for the synopsis's curly one
    assert "excerpt_not_in_synopsis" not in codes(L.check_ledger(events, SYN2))


def test_an_excerpt_that_is_not_a_quotation_is_pointed_at_the_sentence_it_came_from():
    events = [ev("e1", "Mara opens the hatch and finds the drive", "Mara opens the hatch ... finds a data drive in the crust"),
              ev("e2", "Halloway stops them at the launch bay", "Halloway stops them at the launch bay with drones")]
    assert "excerpt_not_in_synopsis" in codes(L.check_ledger(events, SYN2))
    notes = L.repair_excerpts(events, SYN2)
    assert len(notes) == 2 and events[0]["excerpt"].startswith("Mara pries the hatch open") and events[1]["excerpt"].startswith("Halloway intercepts them at the launch bay")
    assert "excerpt_not_in_synopsis" not in codes(L.check_ledger(events, SYN2))
    unrelated = [ev("e3", "x", "something that is nowhere in the synopsis at all")]
    assert L.repair_excerpts(unrelated, SYN2) == [] and unrelated[0]["excerpt"].startswith("something")  # nothing close enough: left for the check to report


def test_description_the_model_lists_as_needing_no_event_is_not_a_missing_event():
    events = [ev("e1", "Mara finds a drive", "Mara pries the hatch open and finds a data drive hidden in the asteroid's crust"),
              ev("e3", "Halloway intercepts them", "Halloway intercepts them at the launch bay, armed with a plasma cutter and backed by automated drones")]
    found = [f for f in L.check_ledger(events, SYN2) if f.code == "sentence_not_covered"]
    assert len(found) == 1 and "closed economic loop" in found[0].message and "no_event_needed" in found[0].message
    waived = [{"quote": "The corporation has turned the asteroid into a closed economic loop where workers are paid in scrip valid only at company stores", "reason": "scene-setting"}]
    assert not [f for f in L.check_ledger(events, SYN2, no_event_needed=waived) if f.code == "sentence_not_covered"]


def test_a_condition_that_fits_several_earlier_events_equally_is_a_guess_not_a_verdict():
    early1 = ev("e6", "Eli and Mara escape the sector through the vents")
    early2 = ev("e7", "Eli and Mara escape the sector through the cargo bay")
    grant = ev("e27", "They allow Eli to escape on condition that he signs", "They allow Eli to escape the sector, but only on the condition that he signs")
    found = L.causal_order([early1, early2, grant])
    assert len(found) == 1 and found[0].severity == "soft" and "2 earlier events fit" in found[0].message
    assert L.causal_order([early1, grant])[0].severity == "hard"  # one clear match is a verdict
