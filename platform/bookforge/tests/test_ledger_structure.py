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


def test_too_many_derived_complications_for_an_act_are_refused(project):
    p = project_ready(project)
    padded = chapters(1)
    padded["derived_events"] = [dict(id=f"e1.{i}", text=f"A small delay number {i} slows her", parent="e1", after=["e1"], weight=1, kind="event") for i in (1, 2)]
    padded["chapters"][0]["events_covered"] = ["e1", "e1.1", "e1.2"]
    s = run(p, RuleLLM([("Plan exactly 2 chapters, b1.ch01 to b1.ch02", dump(padded))] + rules()), HANDLERS, until="chapters")
    assert s.stopped == "failed" and "too_many_derived" in s.detail


def test_the_plan_review_sees_the_ledger(project):
    from bookforge.project import Project
    from qc_fakes import PLAN_REVIEW, plan_review
    from structure_fakes import SMALL_CONFIG
    p = ready(project)
    (p.root / "config.yaml").write_text(SMALL_CONFIG.replace("review_structure: false", "review_structure: true"))
    p = Project.open(p.root)
    install_ledger(p)
    llm = RuleLLM([(PLAN_REVIEW, plan_review(None))] + rules())
    run(p, llm, HANDLERS, until="chapters")
    prompts = [next(m["content"] for m in c["messages"] if m["role"] == "user") for c in llm.calls]
    reviews = [t for t in prompts if PLAN_REVIEW in t]
    assert reviews and all("RESERVED FOR LATER" in t or "- e1 (" in t for t in reviews)
    assert any("RESERVED FOR LATER" in t and "tells every event assigned here" in t for t in reviews)


def test_state_inherited_from_earlier_books_reaches_every_planning_prompt_and_the_briefing(project):
    from bookforge.briefing import build_briefing
    p = project_ready(project)
    (p.root / "ledger.yaml").write_text("open_threads: []\nend_of_book_states:\n  book1: Captain Rhee signed a debt contract with the harbor board.\n")
    llm = RuleLLM(rules())
    run(p, llm, HANDLERS, until="scenes")
    prompts = [next(m["content"] for m in c["messages"] if m["role"] == "user") for c in llm.calls]
    planning = [t for t in prompts if "Already true when this book begins" in t]
    assert len(planning) >= 1 + 2 + 4 and all("signed a debt contract" in t for t in planning)  # acts, both chapter calls, every scene call
    b = build_briefing(p, "b1.ch01.s1")
    assert any(s.heading.startswith("Already true when this book begins") and "debt contract" in s.body for s in b.sections)
    q = project_ready(__import__("conftest").Project.create(p.root.parent / "first", "x\n"))
    assert "nothing: this is the first book" in __import__("bookforge.ledger_view", fromlist=["x"]).carried_for_prompt(q)


# ── downstream of the chapters: continued events, notes, whole-book retries, scenes within a chapter ──

def test_a_continued_event_is_shown_to_the_scene_planner_as_continuing_not_done():
    from bookforge.bible.models import Chapter, Ledger
    from bookforge.ledger_view import status_text
    from ledger_structure_fakes import events as fake_events
    ledger = Ledger(events=fake_events())
    ch1 = Chapter(id="b1.ch01", act="b1.act1", title="t", purpose="p", summary="s", pov="anna", setting="harbor", tension=3, events_covered=["e1"])
    text = status_text(ledger, {"e2"}, [ch1], "SHOWN IN THIS CHAPTER", continuing={"e1"})
    done, rest = text.split("CONTINUING FROM THE CHAPTER BEFORE")
    assert "e1 (" not in done and "e1 (" in rest.split("SHOWN IN THIS CHAPTER")[0] and "begun in b1.ch01" in rest
    assert "CONTINUING" not in status_text(ledger, {"e2"}, [ch1], "SHOWN IN THIS CHAPTER")


def test_the_authors_note_reaches_the_ledger_mode_chapter_and_scene_prompts(project):
    from bookforge import steering
    p = project_ready(project)
    steering.write(p, "chapters", "Make the harbor feel colder.")
    steering.write(p, "scenes", "Keep every scene short.")
    llm = RuleLLM(rules())
    run(p, llm, HANDLERS, until="scenes")
    prompts = [next(m["content"] for m in c["messages"] if m["role"] == "user") for c in llm.calls]
    assert any("Make the harbor feel colder." in t and "Plan exactly 2 chapters" in t for t in prompts)
    assert any("Keep every scene short." in t and "Scene ids are consecutive" in t for t in prompts)


def test_a_whole_book_failure_plans_the_involved_acts_again_with_the_findings(project, monkeypatch):
    from bookforge import steering
    from bookforge.validators import findings as F, tension
    p = project_ready(project)
    calls = {"n": 0}

    def flat_once(chapters, stage="chapters", spread=2):
        calls["n"] += 1
        return [F.hard("chapters", "flat_tension", "tension is flat for 4 chapters", ["b1.ch03", "b1.ch04"])] if calls["n"] == 1 else []

    monkeypatch.setattr(tension, "flat_stretches", flat_once)
    first = run(p, RuleLLM(rules()), HANDLERS, until="chapters")
    assert first.stopped == "failed" and "act2 will be planned again" in first.detail
    note = steering.read(p, "chapters")
    assert steering.CHECKS_MARKER in note and "flat_tension" in note
    llm = RuleLLM(rules())
    second = run(p, llm, HANDLERS, until="chapters")
    assert second.ran == ["chapters"], second.detail
    asked = [next(m["content"] for m in c["messages"] if m["role"] == "user") for c in llm.calls]
    act2 = [t for t in asked if "Plan exactly 2 chapters, b1.ch03 to b1.ch04" in t]
    assert act2 and "Why the previous attempt was rejected" in act2[0] and "flat_tension" in act2[0]
    assert not any("Plan exactly 2 chapters, b1.ch01 to b1.ch02" in t for t in asked)  # act 1 was fine: its saved piece is reused
    assert steering.read(p, "chapters") == ""  # the note is gone once the layer is accepted


def test_a_whole_book_scene_failure_plans_only_the_chapters_it_names_again(project, monkeypatch):
    from bookforge.validators import findings as F, repeats
    p = project_ready(project)
    state = {"n": 0}

    def action_once(scenes, chapters, names=frozenset(), stage="scenes"):
        state["n"] += 1
        return [F.hard("scenes", "action_pattern_repeated", "the same action recurs", ["b1.ch02", "b1.ch03.s1"])] if state["n"] == 1 else []

    monkeypatch.setattr(repeats, "action_patterns", action_once)
    first = run(p, RuleLLM(rules()), HANDLERS, until="scenes")
    assert first.stopped == "failed" and "Chapters ch02, ch03 will be planned again" in first.detail
    llm = RuleLLM(rules())
    second = run(p, llm, HANDLERS, until="scenes")
    assert second.ran == ["scenes"], second.detail
    asked = " ".join(next(m["content"] for m in c["messages"] if m["role"] == "user") for c in llm.calls)
    assert "Scene ids are consecutive: b1.ch02.s1" in asked and "Scene ids are consecutive: b1.ch03.s1" in asked
    assert "Scene ids are consecutive: b1.ch01.s1" not in asked and "Scene ids are consecutive: b1.ch04.s1" not in asked
