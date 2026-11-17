"""Phase 5d: a scene may not report an outcome a later scene or chapter tells; event ids never reach the text."""

import json

from conftest import RuleLLM
from bookforge.bible import normalize
from bookforge.bible.models import Chapter, Scene
from bookforge.layers.runner import StepContext
from bookforge.qc import overreach_fix
from bookforge.validators import HARD, state_claims

EVENTS = [dict(id="e1", text="Eli finds the data drive", once_only=True),
          dict(id="e2", text="Eli uploads the data to the whole network, which triggers a lockdown", once_only=True),
          dict(id="e3", text="Mara dies in the cockpit", once_only=True)]


def chapter(i, ev):
    return Chapter(id=f"b2.ch{i:02d}", act="b2.act1", title="t", purpose="p", summary="s", pov="eli", setting="mine", tension=5, events_covered=ev, end_state="x")


def scene(ch, n, ev, purpose, beats, end):
    return Scene(id=f"b2.ch{ch:02d}.s{n}", chapter=f"b2.ch{ch:02d}", purpose=purpose, pov="eli", setting="mine", characters=["eli"], beats=beats, end_state=end, events=ev)


def plan():
    chs = [chapter(1, ["e1"]), chapter(2, ["e2"]), chapter(3, ["e3"])]
    scs = [scene(1, 1, ["e1"], "Eli finds the drive.", ["Eli finds the drive.", "He decides to upload the data to the whole network."], "Eli holds the drive; the data is now uploaded and public on the network."),
           scene(2, 1, ["e2"], "The upload.", ["Eli uploads the data."], "A lockdown seals the sector."),
           scene(3, 1, ["e3"], "Mara dies.", ["Mara dies in the cockpit."], "Mara is dead.")]
    return chs, scs


def test_a_scene_that_reports_a_later_events_outcome_is_found():
    chs, scs = plan()
    found = state_claims.scene_end_state_overreach([s.model_dump() for s in scs], [c.model_dump() for c in chs], EVENTS)
    assert [(f.code, f.items[:2], f.severity) for f in found] == [("end_state_overreach", ["b2.ch01.s1", "e2"], HARD)]
    assert "scene" in found[0].message and found[0].evidence[0].startswith("chapter:")


def test_a_scene_that_only_decides_is_not_flagged():
    chs, scs = plan()
    scs[0].end_state = "Eli holds the drive and has decided what to do with it."
    scs[0].beats = ["Eli finds the drive.", "He decides what to do with it."]  # (a plan that says 'decides to upload' is for the critic's confirm question, not the word check)
    assert state_claims.scene_end_state_overreach([s.model_dump() for s in scs], [c.model_dump() for c in chs], EVENTS) == []


def test_a_carry_on_scene_owns_the_events_of_the_scene_before_it():
    chs, scs = plan()
    scs[1].end_state = "The data is uploaded; a lockdown seals the sector."
    scs.insert(2, scene(2, 2, [], "Aftermath.", ["Eli stares at the alarms."], "The data is uploaded and public."))  # goes on with s1: owns e2
    found = state_claims.scene_end_state_overreach([s.model_dump() for s in scs], [c.model_dump() for c in chs], EVENTS)
    assert not any(f.items[0] == "b2.ch02.s2" for f in found)


def test_the_wording_is_rewritten_once_and_kept_when_the_check_passes(project):
    chs, scs = plan()
    plain = lambda: state_claims.scene_end_state_overreach([s.model_dump() for s in scs], [c.model_dump() for c in chs], EVENTS)
    found = plain()
    reply = json.dumps({"purpose": "Eli finds the drive.", "beats": ["Eli finds the drive.", "He weighs what to do with it."], "end_state": "Eli holds the drive and has not decided."})
    llm = RuleLLM([("purpose, beats and end state of one scene", reply)])
    notes = overreach_fix.fix_scene_overreach(StepContext(project=project, layer="scenes", llm=llm), scs, chs, EVENTS, found)
    assert len(notes) == 1 and "b2.ch01.s1" in notes[0] and plain() == []


def test_event_ids_are_taken_out_of_the_text():
    items = [{"id": "b2.ch22.s1", "purpose": "Eli secures the drive, preserving the evidence as per event e17.",
              "beats": ["He keeps it (e17) safe.", "Nothing about e18, event e19 or anything."], "end_state": "Done."}]
    notes = normalize.scrub_ids(items, ["e17", "e18", "e19"], ("purpose", "beats", "end_state"))
    assert len(notes) == 2 and "e17" not in json.dumps(items) and "e19" not in json.dumps(items)
    assert items[0]["purpose"] == "Eli secures the drive, preserving the evidence."
    assert normalize.scrub_ids([{"purpose": "Meet at e1x."}], ["e1"], ("purpose",)) == []
