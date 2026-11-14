"""Acts, chapters and scenes planned from the ledger: contracts enforced, hard findings fed back, then blocking."""

import copy
import json

import pytest
import yaml
from conftest import RuleLLM
from ledger_structure_fakes import acts, chapters, dump, events, install_ledger, rules, scenes
from structure_fakes import ready

from bookforge.bible import store
from bookforge.layers import HANDLERS
from bookforge.layers.runner import run


def project_ready(project):
    p = ready(project)
    install_ledger(p)
    return p


def test_the_whole_structure_is_planned_from_the_ledger(project):
    p = project_ready(project)
    llm = RuleLLM(rules())
    summary = run(p, llm, HANDLERS, until="scenes")
    assert summary.ran == ["acts", "chapters", "scenes"], summary.detail
    assert [a.events for a in store.load_acts(p)] == [["e1", "e2"], ["e3", "e4"]]
    ch = store.load_chapters(p)
    assert [c.events_covered for c in ch] == [["e1"], ["e2"], ["e3"], ["e4"]] and all(c.end_state for c in ch)
    assert all(s.end_state and s.events is not None for s in store.load_scenes(p))
    for stage in ("acts", "chapters", "scenes"):
        assert json.loads((p.book_dir / "validation" / f"{stage}.json").read_text())["summary"]["hard"] == 0
    first_acts_prompt = llm.calls[0]["messages"][-1]["content"]
    assert "every event of the ledger belongs to exactly one act" in first_acts_prompt.lower() or "EVERY event of the ledger" in first_acts_prompt


def test_the_chapter_planner_is_told_what_is_done_and_what_is_reserved(project):
    p = project_ready(project)
    llm = RuleLLM(rules())
    run(p, llm, HANDLERS, until="chapters")
    act2 = next(c for c in llm.calls if "b1.ch03 to b1.ch04" in c["messages"][-1]["content"])["messages"][-1]["content"]
    assert "DONE (already told" in act2 and "e1 (once" in act2 and "[told in b1.ch01]" in act2
    act1 = next(c for c in llm.calls if "b1.ch01 to b1.ch02" in c["messages"][-1]["content"])["messages"][-1]["content"]
    assert "RESERVED FOR LATER" in act1 and "e3 (once" in act1.split("RESERVED FOR LATER")[1]  # act 2's events are off limits in act 1
    assert "Reference only" in act1 and "must never become a beat" in act1


def test_an_act_that_leaves_out_the_resolution_is_corrected_then_blocks(project):
    p = project_ready(project)
    bad = copy.deepcopy(acts())
    bad["acts"][1]["events"] = ["e3"]
    llm = RuleLLM([("Divide the book into ACTS by assigning", dump(bad))])
    summary = run(p, llm, HANDLERS, until="acts")
    assert summary.stopped == "failed" and "resolution" in summary.detail and p.state.layers["acts"].status == "flagged"
    assert any("event_in_no_act" in c["messages"][-1]["content"] for c in llm.calls[1:])  # the error was fed back


def test_chapters_that_retell_an_event_or_use_a_reserved_one_are_refused(project):
    p = project_ready(project)
    bad = chapters(1)
    bad["chapters"][1]["events_covered"] = ["e1"]  # tells e1 again, and e2 is never told
    other = [("Plan exactly 2 chapters, b1.ch01 to b1.ch02", dump(bad))]
    summary = run(p, RuleLLM(other + rules()), HANDLERS, until="chapters")
    assert summary.stopped == "failed"
    assert "once_only_repeated" in summary.detail or "chapter_nothing_new" in summary.detail or "event_not_covered" in summary.detail
    reserved = chapters(1)
    reserved["chapters"][1]["events_covered"] = ["e2", "e3"]  # e3 belongs to act 2
    llm = RuleLLM([("Plan exactly 2 chapters, b1.ch01 to b1.ch02", dump(reserved))] + rules()[:2])
    summary = run(p, llm, HANDLERS, until="chapters")
    assert summary.stopped == "failed" and "event_from_other_act" in " ".join(c["messages"][-1]["content"] for c in llm.calls)


def test_derived_complications_join_the_ledger_and_obey_the_rules(project):
    p = project_ready(project)
    good = chapters(1)
    good["derived_events"] = [dict(id="e1.1", text="A dockhand sees her take it", parent="e1", after=["e1"], weight=1, kind="event")]
    good["chapters"][0]["events_covered"] = ["e1", "e1.1"]
    summary = run(p, RuleLLM([("Plan exactly 2 chapters, b1.ch01 to b1.ch02", dump(good))] + rules()), HANDLERS, until="chapters")
    assert summary.ran == ["acts", "chapters"], summary.detail
    led = store.load_ledger(p)
    child = next(e for e in led.events if e.id == "e1.1")
    assert child.source == "derived" and child.parent == "e1" and [e.id for e in led.events][:2] == ["e1", "e1.1"]
    major = copy.deepcopy(good)
    major["derived_events"][0]["weight"] = 3
    p2 = project_ready(__import__("conftest").Project.create(p.root.parent / "second", "x\n"))
    s2 = run(p2, RuleLLM([("Plan exactly 2 chapters, b1.ch01 to b1.ch02", dump(major))] + rules()), HANDLERS, until="chapters")
    assert s2.stopped == "failed" and "derived_not_minor" in s2.detail


def test_scenes_must_show_every_chapter_event_once_with_an_end_state(project):
    p = project_ready(project)
    run(p, RuleLLM(rules()), HANDLERS, until="chapters")
    p.state.approve_checkpoint("structure") if p.state.checkpoints["structure"].status == "waiting" else None
    bad = scenes(1)
    bad["scenes"][0]["events"] = []
    bad["scenes"][1]["end_state"] = ""
    llm = RuleLLM([("Scene ids are consecutive: b1.ch01.s1", dump(bad))] + rules())
    summary = run(p, llm, HANDLERS, until="scenes")
    assert summary.stopped in ("failed", "checkpoint") and (p.state.layers["scenes"].status == "flagged" or "chapter_event_not_in_scenes" in summary.detail)
    fed = " ".join(c["messages"][-1]["content"] for c in llm.calls)
    assert "chapter_event_not_in_scenes" in fed and "scene_without_end_state" in fed


def test_flat_tension_across_the_book_blocks_the_chapters_layer(project):
    from bookforge.errors import LayerError
    from bookforge.layers.structure import _book_chapter_checks
    from bookforge.bible.models import Chapter
    p = project_ready(project)
    run(p, RuleLLM(rules()), HANDLERS, until="chapters")
    chapters_ = store.load_chapters(p)
    flat = [c.model_copy(update={"tension": 9}) for c in chapters_] * 2  # eight chapters, tension 9 throughout
    flat = [c.model_copy(update={"id": f"b1.ch{i:02d}"}) for i, c in enumerate(flat, 1)]
    with pytest.raises(LayerError):
        _book_chapter_checks(p, flat, store.load_ledger(p))
    saved = json.loads((p.book_dir / "validation" / "chapters.json").read_text())
    assert any(f["code"] == "flat_tension" and f["severity"] == "hard" for f in saved["findings"])
