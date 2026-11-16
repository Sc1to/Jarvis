"""The model names where each chapter starts; the tool cuts the act's events there. What used to need checks and repairs cannot be written any more."""

import copy

from conftest import RuleLLM
from ledger_structure_fakes import chapters, dump, rules
from test_ledger_structure import HANDLERS, project_ready, run  # noqa: F401
from bookforge.bible import partition, store
from bookforge.bible.models import StoryEvent

ORDER = ["e1", "e2", "e3", "e4", "e5", "e6"]


def ch(*start, cont=None):
    c = {"title": "t"}
    if start:
        c["starts_with"] = start[0]
    if cont:
        c["events_continued"] = cont
    return c


def test_each_chapter_tells_the_stretch_from_its_starting_event_to_the_next_chapters_and_the_last_runs_to_the_end():
    raw = [ch("e1"), ch("e3"), ch("e4")]
    assert partition.assign(raw, ORDER) == []
    assert [c["events_covered"] for c in raw] == [["e1", "e2"], ["e3"], ["e4", "e5", "e6"]] and all("starts_with" not in c for c in raw)
    every = [x for c in raw for x in c["events_covered"]]
    assert every == ORDER  # every event once, in ledger order, whatever the model wrote


def test_the_first_chapter_takes_the_events_before_its_start_and_a_chapter_that_only_continues_tells_nothing_new():
    raw = [ch("e2"), ch(cont=["e2"]), ch("e4")]
    assert partition.assign(raw, ORDER) == []
    assert [c["events_covered"] for c in raw] == [["e1", "e2", "e3"], [], ["e4", "e5", "e6"]]
    spanning = [ch("e1"), ch("e2", cont=["e1"]), ch("e3")]
    partition.assign(spanning, ORDER)
    assert [c["events_covered"] for c in spanning] == [["e1"], ["e2"], ["e3", "e4", "e5", "e6"]]


def test_a_start_that_is_not_an_event_of_the_act_or_goes_backwards_is_handed_back_to_the_model():
    foreign = partition.assign([ch("e1"), ch("e9")], ORDER)
    assert len(foreign) == 1 and "'e9'" in foreign[0] and "not an event of this act" in foreign[0] and "e1, e2" in foreign[0]
    backwards = partition.assign([ch("e3"), ch("e2")], ORDER)
    assert len(backwards) == 1 and "later and later events" in backwards[0]
    twice = partition.assign([ch("e3"), ch("e3")], ORDER)
    assert len(twice) == 1
    bare = partition.assign([ch("e1"), ch()], ORDER)
    assert len(bare) == 1 and "neither `starts_with`" in bare[0]


def test_a_reply_that_still_lists_events_covered_is_taken_as_it_is():
    raw = [dict(title="t", events_covered=["e1"]), dict(title="t", events_covered=["e2"])]
    before = copy.deepcopy(raw)
    assert partition.assign(raw, ORDER) == [] and raw == before


def test_derived_complications_sit_right_after_their_parent_so_they_belong_to_the_chapter_that_tells_it():
    events = [StoryEvent(id=i, text="x", once_only=True, kind="event", weight=2, source="synopsis") for i in ("e1", "e2", "e3")]
    order = partition.act_order(events, ["e1", "e2", "e3"], [dict(id="e1.1", parent="e1"), dict(id="e1.2", parent="e1"), dict(id="e9.1", parent="e9")])
    assert order == ["e1", "e1.1", "e1.2", "e2", "e3"]  # a complication of an event outside the act is ignored
    raw = [ch("e1"), ch("e2")]
    partition.assign(raw, order)
    assert raw[0]["events_covered"] == ["e1", "e1.1", "e1.2"]


def starts_reply(first, starts):
    """The small book's chapters of one act, written the new way: only where each chapter starts."""
    out = copy.deepcopy(chapters(first))
    for c, s in zip(out["chapters"], starts):
        c.pop("events_covered")
        c["starts_with"] = s
    return out


def test_a_whole_act_planned_with_starting_events_is_saved_with_the_events_the_tool_cut(project):
    p = project_ready(project)
    act1 = starts_reply(1, ["e1", "e2"])
    summary = run(p, RuleLLM([("Plan the chapters this act's events need, b1.ch01 onward", dump(act1))] + rules()), HANDLERS, until="chapters")
    assert summary.ran == ["acts", "chapters"], summary.detail
    saved = {c.id: c.events_covered for c in store.load_chapters(p)}
    assert saved["b1.ch01"] == ["e1"] and saved["b1.ch02"] == ["e2"]


def test_a_start_the_act_does_not_own_is_corrected_by_the_model_not_left_to_you(project):
    p = project_ready(project)
    bad = starts_reply(1, ["e1", "e3"])  # e3 belongs to act 2
    llm = RuleLLM([("Plan the chapters this act's events need, b1.ch01 onward", dump(bad))] + rules()[:2])
    summary = run(p, llm, HANDLERS, until="chapters")
    assert summary.stopped == "failed"
    assert any("starts_with is 'e3', which is not an event of this act" in c["messages"][-1]["content"] for c in llm.calls)
