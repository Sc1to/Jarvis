"""Mechanical slips in a plan are corrected before the checks, so they are not asked about; what needs judgement is left alone."""

import copy

from conftest import RuleLLM
from ledger_structure_fakes import acts, chapters, dump, install_ledger, rules
from structure_fakes import ready

from bookforge.bible import repair, store
from bookforge.layers import HANDLERS
from bookforge.layers.runner import run


def ev(i, text="x", **kw):
    return {**dict(id=i, text=text, once_only=True, after=[], kind="event", weight=2, source="synopsis"), **kw}


LEDGER = [ev("e1", "Eli arrives"), ev("e2", "Eli finds Mara", after=["e1"]), ev("e3", "Mara warns Eli about the corporation", after=["e2"]), ev("e4", "Halloway hunts them", after=["e3"]),
          ev("e5", "Eli decides to broadcast", after=["e4"]), ev("e6", "Mara is injured in the struggle", after=["e5"]), ev("e7", "Eli realizes he cannot save Mara", after=["e6"]), ev("e8", "Eli launches the ship", after=["e7"])]


def test_events_listed_before_one_they_must_follow_are_moved_after_it_and_cycles_are_left_alone():
    raw = [ev("e1"), ev("e3", after=["e2"]), ev("e2", after=["e1"]), ev("e4", after=["e3"])]
    notes = repair.repair_event_order(raw)
    assert [e["id"] for e in raw] == ["e1", "e2", "e3", "e4"] and "e3" in notes[0]
    fine = [ev("e1"), ev("e2", after=["e1"])]
    assert repair.repair_event_order(fine) == [] and [e["id"] for e in fine] == ["e1", "e2"]
    loop = [ev("e1", after=["e2"]), ev("e2", after=["e1"])]
    assert repair.repair_event_order(loop) == [] and [e["id"] for e in loop] == ["e1", "e2"]
    flash = [ev("e1"), ev("e2", after=["e3"], kind="flashback"), ev("e3")]
    assert repair.repair_event_order(flash) == []  # told out of story order on purpose


def test_acts_get_their_events_in_order_each_once_and_an_orphan_goes_where_its_neighbours_are():
    raw = [dict(id="b2.act1", summary="Eli arrives and meets Mara", events=["e2", "e1", "e3"]), dict(id="b2.act2", summary="The hunt and the broadcast", events=["e5", "e4", "e3"]),
           dict(id="b2.act3", summary="Escape", events=["e7"])]
    notes = repair.repair_acts(raw, LEDGER)
    assert [a["events"] for a in raw] == [["e1", "e2", "e3"], ["e4", "e5", "e6"], ["e7", "e8"]]  # e3 kept in the first act; e6, between two acts and matching neither, goes to the earlier; e8 (the ending) to the last
    assert any("e3 was in two acts" in n for n in notes) and any("e6 was in no act" in n for n in notes) and any("e8 was in no act" in n for n in notes)
    assert repair.repair_acts([dict(id="a", events=["e1"])], []) == []


def chapter(i, events, title="t", summary="s", end="e"):
    return dict(id=f"b2.ch{i:02d}", act="b2.act2", title=title, purpose="p", summary=summary, end_state=end, events_covered=events, events_continued=[])


def test_chapters_in_the_wrong_order_are_swapped_back_and_the_tracks_follow():
    raw = [chapter(4, ["e4"]), chapter(6, ["e6"], title="Mara is hurt"), chapter(5, ["e5"], title="The broadcast")]  # ch05 and ch06 swapped (written ids differ too)
    tracks = [dict(id="mara-health", plan=[dict(**{"from": "b2.ch06", "value": "injured"})])]  # the injury is told in the chapter that is now b2.ch06
    notes = repair.repair_chapters(raw, tracks, LEDGER, ["e4", "e5", "e6"], "b2", 4)
    assert [c["events_covered"] for c in raw] == [["e4"], ["e5"], ["e6"]] and [c["id"] for c in raw] == ["b2.ch04", "b2.ch05", "b2.ch06"]
    assert raw[2]["title"] == "Mara is hurt" and tracks[0]["plan"][0]["from"] == "b2.ch06" and any("chapters put in story order" in n for n in notes)


def test_a_chapters_events_are_put_in_order_and_an_unlisted_act_event_joins_the_chapter_next_to_it():
    raw = [chapter(4, ["e5", "e4"]), chapter(5, ["e6"], summary="Mara is hurt and her condition worsens; Eli cannot save her", title="The cost"), chapter(6, ["e8"])]
    notes = repair.repair_chapters(raw, None, LEDGER, ["e4", "e5", "e6", "e7", "e8"], "b2", 4)
    assert raw[0]["events_covered"] == ["e4", "e5"] and any("put in the order they happen" in n for n in notes)
    assert raw[1]["events_covered"] == ["e6", "e7"] and any("e7 was in no chapter; it is told in b2.ch05" in n for n in notes)  # e7 matches ch05's words: Mara and "cannot save"


def test_what_needs_judgement_is_left_alone():
    interleaved = [chapter(4, ["e4", "e6"]), chapter(5, ["e5", "e7"])]  # the events of the two chapters interleave: swapping would split one
    repair.repair_chapters(interleaved, None, LEDGER, ["e4", "e5", "e6", "e7"], "b2", 4)
    assert [c["events_covered"] for c in interleaved] == [["e4", "e6"], ["e5", "e7"]]
    continued = [chapter(5, ["e5"]), chapter(4, ["e4"])]
    continued[0]["events_continued"] = ["e4"]
    repair.repair_chapters(continued, None, LEDGER, ["e4", "e5"], "b2", 4)
    assert [c["events_covered"] for c in continued] == [["e5"], ["e4"]]  # a continued event ties the order: the checks decide
    nothing = [chapter(4, ["e4"])]
    assert repair.repair_chapters(nothing, None, LEDGER, ["e4"], "b2", 4) == []


def project_ready(project):
    p = ready(project)
    install_ledger(p)
    return p


def test_a_chapter_plan_with_swapped_chapters_is_accepted_in_one_round_and_the_layer_says_what_it_corrected(project):
    p = project_ready(project)
    swapped = copy.deepcopy(chapters(1))
    swapped["chapters"] = [swapped["chapters"][1], swapped["chapters"][0]]  # the two chapters of act 1 in the wrong order
    llm = RuleLLM([("Plan the chapters this act's events need, b1.ch01 onward", dump(swapped))] + rules())
    summary = run(p, llm, HANDLERS, until="chapters")
    assert summary.ran == ["acts", "chapters"], summary.detail
    assert len([c for c in llm.calls if "Plan the chapters this act's events need, b1.ch01 onward" in c["messages"][-1]["content"]]) == 1  # no correction round
    assert [c.events_covered for c in store.load_chapters(p)][:2] == [["e1"], ["e2"]] and "mechanical slip" in summary.notes["chapters"]


def test_an_acts_plan_that_leaves_the_last_event_out_is_corrected_without_a_round(project):
    p = project_ready(project)
    plan = copy.deepcopy(acts())
    plan["acts"][1]["events"] = ["e3"]  # e4, the ending, listed in no act
    llm = RuleLLM([("Divide the book into ACTS by assigning", dump(plan))] + rules())
    summary = run(p, llm, HANDLERS, until="acts")
    assert summary.ran == ["acts"], summary.detail
    assert [a.events for a in store.load_acts(p)] == [["e1", "e2"], ["e3", "e4"]]
    assert len([c for c in llm.calls if "Divide the book into ACTS" in c["messages"][-1]["content"]]) == 1


def test_a_dependency_on_an_event_that_does_not_exist_is_dropped():
    raw = [ev("e1"), ev("e2", after=["e1", "e9"])]
    notes = repair.repair_unknown_after(raw)
    assert raw[1]["after"] == ["e1"] and "e9" in notes[0]


def scene(i, purpose, events, beats=("a beat", "another beat")):
    return dict(id=f"b2.ch07.s{i}", purpose=purpose, beats=list(beats), events=events, end_state="e")


def test_scenes_get_their_ids_back_their_events_once_and_only_the_chapters_own():
    raw = [scene(1, "Eli reaches the vault", ["e3", "e99"]), scene(3, "Mara warns Eli about the corporation", ["e3"]), scene(4, "Eli decides to broadcast", [])]  # ids 1,3,4; e3 twice; e99 foreign; e5 nowhere
    tracks = [dict(id="t", plan=[{"from": "b2.ch07.s4", "value": "v"}])]
    notes = repair.repair_scenes(raw, tracks, ["e3", "e5"], ["e3", "e5"], LEDGER, "b2", 7)
    assert [s["id"] for s in raw] == ["b2.ch07.s1", "b2.ch07.s2", "b2.ch07.s3"] and tracks[0]["plan"][0]["from"] == "b2.ch07.s3"
    assert [s["events"] for s in raw] == [[], ["e3"], ["e5"]]  # e3 kept where "warns Eli about the corporation" fits; e5 where "decides to broadcast" fits
    assert any("e99" in n and "taken out" in n for n in notes) and any("e3 was shown in 2 scenes" in n for n in notes) and any("e5 was shown in no scene" in n for n in notes)


def test_a_scene_plan_that_shows_a_chapter_event_in_no_scene_is_accepted_in_one_round(project):
    p = project_ready(project)
    run(p, RuleLLM(rules()), HANDLERS, until="chapters")
    from ledger_structure_fakes import scenes as scene_reply
    gap = copy.deepcopy(scene_reply(1))
    gap["scenes"][0]["events"] = []  # chapter 1 covers e1, no scene lists it
    llm = RuleLLM([("Scene ids are consecutive: b1.ch01.s1", dump(gap))] + rules())
    summary = run(p, llm, HANDLERS, until="scenes")
    assert summary.ran == ["scenes"], summary.detail
    assert len([c for c in llm.calls if "Scene ids are consecutive: b1.ch01.s1" in c["messages"][-1]["content"]]) == 1
    assert "e1" in [e for s in store.load_scenes(p) if s.chapter == "b1.ch01" for e in s.events]


def test_an_event_of_another_act_is_taken_out_of_a_chapter_that_retells_it_and_a_chapter_left_empty_is_not_touched():
    raw = [chapter(13, ["e4", "e3"], title="Aftermath"), chapter(14, ["e5"])]  # act 2 (e4, e5) lists e3, which act 1 told
    notes = repair.repair_chapters(raw, None, LEDGER, ["e4", "e5"], "b2", 13)
    assert [c["events_covered"] for c in raw] == [["e4"], ["e5"]] and any("e3, which belongs to another act" in n for n in notes)
    only = [chapter(13, ["e3"]), chapter(14, ["e4"])]
    repair.repair_chapters(only, None, LEDGER, ["e4"], "b2", 13)
    assert only[0]["events_covered"] == ["e3"]  # nothing of its own would be left: the checks decide
    derived = [ev("e4.1", "a complication of e4", parent="e4", source="derived")]
    mine = [chapter(13, ["e4", "e4.1"])]
    repair.repair_chapters(mine, None, LEDGER + derived, ["e4", "e4.1"], "b2", 13)
    assert mine[0]["events_covered"] == ["e4", "e4.1"]  # a complication of the act's own event is the act's


def test_an_event_told_as_new_in_two_chapters_of_one_act_is_carried_on_or_kept_in_the_best_fit_and_never_leaves_a_chapter_empty():
    big = [ev("e4", "Halloway hunts them", weight=3), ev("e5", "Eli decides to broadcast"), ev("e6", "Mara is injured in the struggle")]
    raw = [chapter(4, ["e4"]), chapter(5, ["e4", "e5"])]
    notes = repair.repair_chapters(raw, None, big, ["e4", "e5"], "b2", 4)
    assert raw[0]["events_covered"] == ["e4"] and raw[1]["events_covered"] == ["e5"] and raw[1]["events_continued"] == ["e4"] and any("carries it on" in n for n in notes)
    small = [ev("e5", "Eli decides to broadcast"), ev("e6", "Mara is injured in the struggle")]
    raw = [chapter(4, ["e5", "e6"], title="The struggle"), chapter(5, ["e5"], title="The broadcast", summary="Eli decides to broadcast"), chapter(6, ["e6"], title="Mara is injured")]
    repair.repair_chapters(raw, None, small, ["e5", "e6"], "b2", 4)
    assert [c["events_covered"] for c in raw] == [["e6"], ["e5"], ["e6"]]  # e5 stays where its words fit; e6 is in ch04 and ch06 but ch04 would be left empty
    only = [chapter(4, ["e5"], title="Eli decides to broadcast"), chapter(5, ["e5"], title="Eli decides to broadcast")]
    repair.repair_chapters(only, None, small, ["e5"], "b2", 4)
    assert [c["events_covered"] for c in only] == [["e5"], ["e5"]]  # each would be left empty: the checks decide


def test_chapters_at_the_end_of_an_act_that_tell_only_other_acts_events_are_left_out_and_the_tracks_follow():
    raw = [chapter(4, ["e4"]), chapter(5, ["e5"]), chapter(6, ["e7"]), chapter(7, ["e8"])]  # act events e4, e5: ch06 and ch07 tell act 3's events
    tracks = [dict(id="mara-health", plan=[dict(**{"from": "b2.ch07", "value": "injured"})])]
    notes = repair.repair_chapters(raw, tracks, LEDGER, ["e4", "e5"], "b2", 4)
    assert [c["id"] for c in raw] == ["b2.ch04", "b2.ch05"] and [c["events_covered"] for c in raw] == [["e4"], ["e5"]]
    assert tracks[0]["plan"][0]["from"] == "b2.ch05" and sum("belong to other acts" in n for n in notes) == 2
    lone = [chapter(4, ["e7"])]
    repair.repair_chapters(lone, None, LEDGER, ["e4"], "b2", 4)
    assert len(lone) == 1  # the only chapter of the act is left for the checks
    middle = [chapter(4, ["e4"]), chapter(5, ["e7"]), chapter(6, ["e5"])]
    repair.repair_chapters(middle, None, LEDGER, ["e4", "e5"], "b2", 4)
    assert [c["events_covered"] for c in middle] == [["e4"], ["e5"]]  # swapped into story order first, then it is the tail
    carrying = [chapter(4, ["e4"]), dict(chapter(5, ["e7"]), events_continued=["e4"])]
    repair.repair_chapters(carrying, None, LEDGER, ["e4"], "b2", 4)
    assert len(carrying) == 2  # one that carries an event on is not filler
