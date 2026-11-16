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
