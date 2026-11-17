"""A confirmed end_state_overreach is corrected in the chapter's own wording, once; the rewrite stays only if the check then passes."""

import json

from conftest import RuleLLM
from bookforge.bible.models import Chapter
from bookforge.layers.runner import StepContext
from bookforge.qc import overreach_fix
from bookforge.validators import HARD, state_claims


def chapter(i, events, summary, end_state):
    return Chapter(id=f"b2.ch{i:02d}", act="b2.act1", title="t", purpose="p", summary=summary, pov="eli", setting="mine", tension=5, events_covered=events, end_state=end_state)


EVENTS = [dict(id="e10", text="Eli decides to broadcast the data to the whole network", once_only=True),
          dict(id="e12", text="Eli uploads the data, triggering a lockdown and worsening Mara's condition", once_only=True)]


def chapters():
    return [chapter(10, ["e10"], "Eli decides to share what he found with the network and the data is now public.", "Eli has chosen. The data is now public on the local network."),
            chapter(12, ["e12"], "The lockdown begins.", "The lockdown.")]


def test_the_chapters_wording_is_rewritten_and_kept_when_the_check_then_passes(project):
    chs = chapters()
    found = state_claims.end_state_overreach([c.model_dump() for c in chs], EVENTS)
    assert [f.severity for f in found] == [HARD]
    fixed = json.dumps({"summary": "Eli decides to share what he found with the network; he has not yet done it.", "end_state": "Eli has chosen. The decision weighs on him."})
    llm = RuleLLM([("The summary and end_state of one chapter of a story plan report", fixed)])
    notes = overreach_fix.fix(StepContext(project=project, layer="chapters", llm=llm), chs, EVENTS, found)
    assert len(notes) == 1 and "b2.ch10" in notes[0] and "e12" in notes[0]
    assert chs[0].end_state == "Eli has chosen. The decision weighs on him." and chs[1].end_state == "The lockdown."
    assert state_claims.end_state_overreach([c.model_dump() for c in chs], EVENTS) == []


def test_a_rewrite_that_still_reports_the_outcome_is_thrown_away_and_the_finding_stands(project):
    chs = chapters()
    before = (chs[0].summary, chs[0].end_state)
    found = state_claims.end_state_overreach([c.model_dump() for c in chs], EVENTS)
    same = json.dumps({"summary": "Eli decides to share what he found and the data is public.", "end_state": "The data is now public on the local network, Eli has chosen."})
    llm = RuleLLM([("The summary and end_state of one chapter of a story plan report", same)])
    assert overreach_fix.fix(StepContext(project=project, layer="chapters", llm=llm), chs, EVENTS, found) == []
    assert (chs[0].summary, chs[0].end_state) == before


def test_no_model_a_failing_model_or_the_switch_off_leaves_everything_alone(project):
    chs = chapters()
    found = state_claims.end_state_overreach([c.model_dump() for c in chs], EVENTS)
    assert overreach_fix.fix(StepContext(project=project, layer="chapters", llm=None), chs, EVENTS, found) == []
    assert overreach_fix.fix(StepContext(project=project, layer="chapters", llm=RuleLLM([])), chs, EVENTS, found) == []  # no rule matches: the call raises
    project.config.qc.fix_overreach = False
    llm = RuleLLM([("The summary and end_state", json.dumps({"summary": "a", "end_state": "b"}))])
    assert overreach_fix.fix(StepContext(project=project, layer="chapters", llm=llm), chs, EVENTS, found) == [] and llm.calls == []


LONG = [dict(id="e1", text="Eli uploads the contamination data to the local network, triggering an alarm and forcing a lockdown of the sector", once_only=True),
        dict(id="e2", text="Eli boards the Kestrel and starts the launch sequence", once_only=True)]


def retelling_chapters():
    one = chapter(11, ["e1"], "Eli uploads the data and the lockdown begins.", "The sector is sealed.")
    one.purpose = "Eli decides to upload the contamination data to the network."
    two = chapter(12, ["e2"], "Eli uploads the contamination data to the local network, triggering an alarm and forcing a lockdown of the sector before he boards.", "Eli is aboard.")
    two.purpose = "To upload the contamination data to the local network and force a lockdown of the sector."
    return [one, two]


def test_a_chapter_that_retells_an_earlier_event_has_its_purpose_and_summary_rewritten_and_kept_when_the_check_passes(project):
    from bookforge.validators import ledger as ledger_checks
    chs = retelling_chapters()
    found = [f for f in ledger_checks.check_chapter_texts([c.model_dump() for c in chs], LONG) if f.code == "chapter_retells_event"]
    assert [(f.severity, f.items) for f in found] == [(HARD, ["b2.ch12", "e1"])]
    fixed = json.dumps({"purpose": "To get Eli aboard the Kestrel and start the launch.", "summary": "Eli reaches the Kestrel and boards her, then starts the launch sequence while the sector is already sealed behind him."})
    llm = RuleLLM([("describe an event that an EARLIER chapter already told", fixed)])
    notes = overreach_fix.fix_retells(StepContext(project=project, layer="chapters", llm=llm), chs, LONG, found)
    assert len(notes) == 1 and "b2.ch12" in notes[0] and "e1" in notes[0] and "b2.ch11" in notes[0]
    assert chs[1].purpose.startswith("To get Eli aboard") and chs[0].purpose.startswith("Eli decides")
    assert [f for f in ledger_checks.check_chapter_texts([c.model_dump() for c in chs], LONG) if f.code == "chapter_retells_event"] == []


def test_a_rewrite_that_still_retells_it_is_thrown_away_and_a_chapter_without_events_of_its_own_is_left(project):
    from bookforge.validators import ledger as ledger_checks
    chs = retelling_chapters()
    before = (chs[1].purpose, chs[1].summary)
    found = [f for f in ledger_checks.check_chapter_texts([c.model_dump() for c in chs], LONG) if f.code == "chapter_retells_event"]
    same = json.dumps({"purpose": "To upload the contamination data to the local network and cause an alarm and a lockdown of the sector.", "summary": "Eli uploads the contamination data to the local network, triggering an alarm and a lockdown of the sector, then boards."})
    llm = RuleLLM([("describe an event that an EARLIER chapter already told", same)])
    assert overreach_fix.fix_retells(StepContext(project=project, layer="chapters", llm=llm), chs, LONG, found) == [] and (chs[1].purpose, chs[1].summary) == before
    chs[1].events_covered = []
    llm2 = RuleLLM([("describe an event that an EARLIER chapter already told", same)])
    assert overreach_fix.fix_retells(StepContext(project=project, layer="chapters", llm=llm2), chs, LONG, found) == [] and llm2.calls == []
    project.config.qc.fix_retells = False
    assert overreach_fix.fix_retells(StepContext(project=project, layer="chapters", llm=llm2), chs, LONG, found) == []


def test_the_per_act_check_leaves_a_retold_event_to_the_whole_book_fix_unless_the_fix_is_off(project):
    from bookforge.bible import validate
    from bookforge.bible.models import Act, Ledger, StoryEvent
    base = dict(once_only=True, kind="event", weight=2, source="synopsis")
    ledger = Ledger(events=[StoryEvent(id=e["id"], text=e["text"], **base) for e in LONG])
    act = Act(id="b2.act2", title="t", summary="s", purpose="p", turning_point="x", chapter_count=1, events=["e2"], turning_point_event="e2", sizing_reason="r")
    before, now = retelling_chapters()[:1], retelling_chapters()[1:]
    for c in before + now:
        c.act = "b2.act1" if c.id == "b2.ch11" else "b2.act2"
    ctx = StepContext(project=project, layer="chapters", llm=RuleLLM([]))
    problems: list[str] = []
    validate._ledger_chapter_checks(project, {}, now, act, ledger, before, [act], problems, ctx)
    assert not any("chapter_retells_event" in p for p in problems)  # the whole-book check fixes it (and saves the fix)
    project.config.qc.fix_retells = False
    problems = []
    validate._ledger_chapter_checks(project, {}, now, act, ledger, before, [act], problems, ctx)
    assert any("chapter_retells_event" in p for p in problems)  # with the fix off the act is sent back as before


def flat_chapters(n=8, tension=8):
    out = []
    for i in range(n):
        c = chapter(10 + i, [f"e{i}"], f"Things happen in chapter {i}.", f"State {i}.")
        c.tension = tension
        out.append(c)
    return out


def test_a_flat_stretch_is_rated_again_from_the_chapters_and_kept_when_the_check_passes(project):
    from bookforge.validators import tension as T
    chs = flat_chapters()
    found = [f for f in T.flat_stretches([c.model_dump() for c in chs]) if f.severity == HARD]
    assert found and found[0].code == "flat_tension"
    ids = found[0].items
    new = {cid: v for cid, v in zip(ids, [5, 8, 4, 9, 6, 9, 3, 10][:len(ids)])}
    llm = RuleLLM([("Rate the tension of the chapters listed below again", json.dumps({"tension": new}))])
    notes = overreach_fix.fix_tension(StepContext(project=project, layer="chapters", llm=llm), chs, found)
    assert len(notes) == 1 and ids[0] in notes[0] and [c.tension for c in chs[:len(ids)]] == list(new.values())
    assert not [f for f in T.flat_stretches([c.model_dump() for c in chs]) if f.severity == HARD]


def test_ratings_that_are_still_flat_or_incomplete_leave_the_saved_tension_alone(project):
    from bookforge.validators import tension as T
    chs = flat_chapters()
    found = [f for f in T.flat_stretches([c.model_dump() for c in chs]) if f.severity == HARD]
    ids = found[0].items
    flat = RuleLLM([("Rate the tension of the chapters listed below again", json.dumps({"tension": {i: 7 + (k % 2) for k, i in enumerate(ids)}}))])
    assert overreach_fix.fix_tension(StepContext(project=project, layer="chapters", llm=flat), chs, found) == [] and {c.tension for c in chs} == {8}
    partial = RuleLLM([("Rate the tension of the chapters listed below again", json.dumps({"tension": {ids[0]: 3}}))])
    assert overreach_fix.fix_tension(StepContext(project=project, layer="chapters", llm=partial), chs, found) == [] and {c.tension for c in chs} == {8}
    project.config.qc.fix_tension = False
    assert overreach_fix.fix_tension(StepContext(project=project, layer="chapters", llm=partial), chs, found) == []


def test_what_the_fixes_could_not_clear_is_kept_as_a_warning_but_structural_findings_stay_hard():
    from bookforge.validators import findings as F
    kept = overreach_fix.demote_unfixable([F.hard("chapters", "end_state_overreach", "over", ["b2.ch10", "e12"]), F.hard("chapters", "flat_tension", "flat", ["b2.ch12"]),
                                           F.hard("chapters", "chapter_retells_event", "retold", ["b2.ch14", "e14"]), F.hard("chapters", "event_not_covered", "gone", ["e10"])])
    assert [(f.code, f.severity) for f in kept] == [("end_state_overreach", "soft"), ("flat_tension", "soft"), ("chapter_retells_event", "soft"), ("event_not_covered", "hard")]
    assert kept[0].message.startswith("(the tool tried to fix this and could not; kept as a warning)")
    accepted = F.hard("chapters", "flat_tension", "flat", ["b2.ch12"])
    accepted.accepted = True
    assert overreach_fix.demote_unfixable([accepted])[0].severity == "hard"


HALLOWAY = "Foreman Halloway arrives at the site with a security team, not to negotiate but to enforce a containment seal that will bury the Kestrel and every occupant inside it."


def twins():
    one = chapter(10, ["e1"], "Halloway holds the bay.", "The bay is held.")
    one.title, one.summary = "The Seal", HALLOWAY
    two = chapter(12, ["e2"], "Eli boards.", "Eli is aboard.")
    two.title, two.summary = "The Hunt", HALLOWAY.replace("arrives at the site", "arrives")
    return [one, two]


def test_two_chapters_that_plan_the_same_event_get_the_later_one_rewritten_and_kept_when_the_check_passes(project):
    from bookforge.validators import repeats
    chs = twins()
    plain = [c.model_dump() for c in chs]
    found = [f for f in repeats.repeated_events(plain, [], ledger_events=LONG) if f.severity == HARD]
    assert found and found[0].code == "event_repeated" and found[0].items == ["b2.ch10", "b2.ch12"]
    fixed = json.dumps({"purpose": "To get Eli aboard the Kestrel.", "summary": "Eli reaches the hatch and boards the Kestrel, then begins the launch sequence while the lockdown holds the sector."})
    llm = RuleLLM([("describe an event that an EARLIER chapter already told", fixed)])
    notes = overreach_fix.fix_retells(StepContext(project=project, layer="chapters", llm=llm), chs, LONG, found)
    assert len(notes) == 1 and "b2.ch12" in notes[0] and "b2.ch10" in notes[0]
    assert chs[0].summary == HALLOWAY and chs[1].summary.startswith("Eli reaches the hatch")  # the earlier chapter is untouched
    assert not [f for f in repeats.repeated_events([c.model_dump() for c in chs], [], ledger_events=LONG) if f.severity == HARD]


def test_a_rewrite_that_repeats_the_earlier_chapter_again_is_thrown_away(project):
    from bookforge.validators import repeats
    chs = twins()
    found = [f for f in repeats.repeated_events([c.model_dump() for c in chs], [], ledger_events=LONG) if f.severity == HARD]
    again = json.dumps({"purpose": "Halloway arrives with a security team.", "summary": HALLOWAY})
    llm = RuleLLM([("describe an event that an EARLIER chapter already told", again)])
    before = chs[1].summary
    assert overreach_fix.fix_retells(StepContext(project=project, layer="chapters", llm=llm), chs, LONG, found) == [] and chs[1].summary == before


def scene(cid, n, events, purpose, beats):
    from bookforge.bible.models import Scene
    return Scene(id=f"{cid}.s{n}", chapter=cid, purpose=purpose, pov="eli", setting="mine", characters=["eli"], beats=beats, events=events, end_state="x")


def retelling_scenes():
    first = scene("b2.ch11", 1, ["e1"], "Eli decides to upload the contamination data.", ["Eli plugs the drive into the network."])
    second = scene("b2.ch12", 1, ["e2"], "Eli boards the Kestrel.", ["Eli uploads the contamination data to the local network, triggering an alarm and forcing a lockdown of the sector.", "He boards."])
    return [first, second]


def test_a_scene_that_retells_an_event_of_another_chapter_has_its_purpose_and_beats_rewritten_and_kept_when_the_check_passes(project):
    from bookforge.validators import ledger as ledger_checks
    scs, chs = retelling_scenes(), retelling_chapters()
    found = [f for f in ledger_checks.check_scene_texts([s.model_dump() for s in scs], [c.model_dump() for c in chs], LONG) if f.code == "scene_retells_event" and f.severity == HARD]
    assert found and found[0].items == ["b2.ch12.s1", "e1"]
    fixed = json.dumps({"purpose": "Eli boards the Kestrel and starts the launch.", "beats": ["Eli crosses the bay to the Kestrel.", "He boards her and starts the launch sequence."]})
    llm = RuleLLM([("describe something that happens elsewhere in the story", fixed)])
    notes = overreach_fix.fix_scene_retells(StepContext(project=project, layer="scenes", llm=llm), scs, chs, LONG, found)
    assert len(notes) == 1 and "b2.ch12.s1" in notes[0] and "e1" in notes[0] and scs[1].beats[0].startswith("Eli crosses") and scs[0].beats == ["Eli plugs the drive into the network."]
    assert not [f for f in ledger_checks.check_scene_texts([s.model_dump() for s in scs], [c.model_dump() for c in chs], LONG) if f.code == "scene_retells_event" and f.severity == HARD]


def test_a_scene_rewrite_that_still_retells_it_is_thrown_away(project):
    from bookforge.validators import ledger as ledger_checks
    scs, chs = retelling_scenes(), retelling_chapters()
    found = [f for f in ledger_checks.check_scene_texts([s.model_dump() for s in scs], [c.model_dump() for c in chs], LONG) if f.code == "scene_retells_event" and f.severity == HARD]
    again = json.dumps({"purpose": "Eli boards.", "beats": ["Eli uploads the contamination data to the local network, triggering an alarm and forcing a lockdown of the sector."]})
    llm = RuleLLM([("describe something that happens elsewhere in the story", again)])
    before = (scs[1].purpose, list(scs[1].beats))
    assert overreach_fix.fix_scene_retells(StepContext(project=project, layer="scenes", llm=llm), scs, chs, LONG, found) == [] and (scs[1].purpose, scs[1].beats) == before
    scs[1].events = []  # no event of its own for a retold event: judgement
    assert overreach_fix.fix_scene_retells(StepContext(project=project, layer="scenes", llm=llm), scs, chs, LONG, found) == []
    project.config.qc.fix_retells = False
    scs[1].events = ["e2"]
    assert overreach_fix.fix_scene_retells(StepContext(project=project, layer="scenes", llm=llm), scs, chs, LONG, found) == []


def test_scene_retold_findings_are_warnings_when_the_fix_could_not_clear_them_and_never_in_the_per_chapter_loop():
    from bookforge.validators import findings as F
    kept = overreach_fix.demote_unfixable([F.hard("scenes", "scene_retells_event", "r", ["b2.ch12.s1", "e1"]), F.hard("scenes", "scene_repeats_scene", "r", ["a", "b"]),
                                           F.hard("scenes", "once_only_repeated", "x", ["e1"])])
    assert [f.severity for f in kept] == ["soft", "soft", "hard"]


# ── phase 5: the b2 scenes flood ──────────────────────────────────────────

def test_a_track_that_goes_back_to_an_earlier_state_gets_the_scenes_purpose_as_its_cause():
    from bookforge.bible import normalize
    from bookforge.bible.models import Track
    track = Track(id="containment-seal-status", entity="eli", kind="other", plan=[
        dict(**{"from": "b2.ch11.s1"}, value="Outer seal breached by plasma cutter; inner door sealed"),
        dict(**{"from": "b2.ch12.s1"}, value="Fully hardened; sector isolated from external access"),
        dict(**{"from": "b2.ch14.s1"}, value="Outer seal breached by plasma cutter; inner door sealed")])
    scenes = [scene("b2.ch14", 1, ["e1"], "The Kestrel breaks through the seal. Smoke fills the bay.", ["x"])]
    notes = normalize.attach_return_causes([track], scenes, [])
    assert len(notes) == 1 and track.plan[2].cause == "The Kestrel breaks through the seal" and track.plan[0].cause == "" and track.plan[1].cause == ""
    from bookforge.validators import state as S
    assert S.track_regressions([track.model_dump(by_alias=True)]) == []  # the check can no longer be raised for it
    assert normalize.attach_return_causes([track], scenes, []) == []  # idempotent


def test_every_hard_finding_that_is_not_structural_ends_as_a_warning_and_a_structural_one_still_stops():
    from bookforge.validators import findings as F
    kept = overreach_fix.demote_unfixable([
        F.hard("scenes", "pov_not_in_text", "x", ["a"]), F.hard("scenes", "timeline_flat", "x", ["a"]), F.hard("scenes", "action_pattern_repeated", "x", ["a"]),
        F.hard("chapters", "end_state_overreach", "x", ["a"]), F.hard("scenes", "two_places_at_once", "x", ["o", "p"]),
        F.hard("ledger", "event_cycle", "x", ["a"]),  # a decision at the ledger stage: later layers would be built on it
        F.hard("chapters", "event_not_covered", "x", ["e1"]), F.hard("scenes", "chapter_event_not_in_scenes", "x", ["c"]), F.hard("scenes", "not_a_known_code", "x", ["a"])])
    assert [f.severity for f in kept] == ["soft", "soft", "soft", "soft", "soft", "hard", "hard", "hard", "hard"]


def test_an_event_repeated_across_chapters_at_the_scenes_stage_gets_the_later_scenes_beats_rewritten(project):
    from bookforge.validators import repeats
    first = scene("b2.ch11", 1, ["e1"], "Eli checks the navigation logs.", ["Eli confirms the Kestrel is on a trajectory toward the unclaimed moon, beyond Dominion jurisdiction."])
    later = scene("b2.ch12", 1, ["e2"], "Eli boards the Kestrel.", ["He checks the navigation console and confirms the trajectory toward the unclaimed moon is locked in, beyond Dominion jurisdiction."])
    third = scene("b2.ch13", 1, ["e2"], "Eli rests.", ["Eli confirms the Kestrel is on a trajectory toward the unclaimed moon, beyond Dominion jurisdiction, again."])
    scs = [first, later, third]
    chs = [chapter(11, ["e1"], "a", "b"), chapter(12, ["e2"], "a", "b"), chapter(13, [], "a", "b")]
    found = [f for f in repeats.repeated_events([c.model_dump() for c in chs], [s.model_dump() for s in scs], ledger_events=LONG, stage="scenes")
             if f.code == "event_repeated" and f.severity == HARD]
    assert found and set(found[0].items) >= {"b2.ch11", "b2.ch12", "b2.ch13"}
    fresh = json.dumps({"purpose": "Eli boards.", "beats": ["Eli crosses the bay and climbs aboard.", "The hatch seals behind him."]})
    llm = RuleLLM([("describe something that happens elsewhere in the story", fresh)])
    notes = overreach_fix.fix_scene_retells(StepContext(project=project, layer="scenes", llm=llm), scs, chs, LONG, found)
    assert len(notes) == 2 and scs[0].beats[0].startswith("Eli confirms") and scs[1].beats[0].startswith("Eli crosses") and scs[2].beats[0].startswith("Eli crosses")
    assert not [f for f in repeats.repeated_events([c.model_dump() for c in chs], [s.model_dump() for s in scs], ledger_events=LONG, stage="scenes") if f.code == "event_repeated" and f.severity == HARD]


def test_a_flat_timeline_is_dated_again_from_what_happens_and_kept_only_when_the_days_then_differ(project):
    from bookforge.bible.models import TimelineEntry
    from bookforge.validators import state as S
    scs = [scene("b2.ch%02d" % i, 1, ["e1"], f"Something happens in chapter {i}.", ["x"]) for i in range(1, 9)]
    tl = [TimelineEntry(id=s.id, day=1, time="morning") for s in scs]
    found = S.timeline_flat([t.model_dump() for t in tl])
    assert found
    new = json.dumps({"days_later": {s.id: v for s, v in zip(scs, [0, 0, 1, 0, 2, 1, 0, 3])}})
    llm = RuleLLM([("all happen on the same story day", new)])
    notes = overreach_fix.fix_timeline(StepContext(project=project, layer="scenes", llm=llm), scs, tl, found)
    assert len(notes) == 1 and [t.day for t in tl] == [1, 1, 2, 2, 4, 5, 5, 8]
    assert S.timeline_flat([t.model_dump() for t in tl]) == []
    tl2 = [TimelineEntry(id=s.id, day=1, time="morning") for s in scs]
    zeros = json.dumps({"days_later": {s.id: 0 for s in scs}})
    assert overreach_fix.fix_timeline(StepContext(project=project, layer="scenes", llm=RuleLLM([("all happen on the same story day", zeros)])), scs, tl2, found) == [] and {t.day for t in tl2} == {1}
    partial = json.dumps({"days_later": {scs[0].id: 0}})
    assert overreach_fix.fix_timeline(StepContext(project=project, layer="scenes", llm=RuleLLM([("all happen on the same story day", partial)])), scs, tl2, found) == []
    project.config.qc.fix_timeline = False
    assert overreach_fix.fix_timeline(StepContext(project=project, layer="scenes", llm=RuleLLM([("all happen on the same story day", new)])), scs, tl2, found) == []
