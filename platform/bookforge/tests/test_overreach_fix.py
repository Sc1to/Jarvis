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
