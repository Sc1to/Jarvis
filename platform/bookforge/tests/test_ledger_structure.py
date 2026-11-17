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
    assert "every event belongs to exactly one act" in first_acts_prompt.lower() and "e1, e2, e3, e4" in first_acts_prompt


def test_the_chapter_planner_is_told_what_is_done_and_nothing_of_what_comes_later(project):
    p = project_ready(project)
    llm = RuleLLM(rules())
    run(p, llm, HANDLERS, until="chapters")
    act2 = next(c for c in llm.calls if "events need, b1.ch03 onward" in c["messages"][-1]["content"])["messages"][-1]["content"]
    assert "DONE (already told" in act2 and "e1 (once" in act2 and "[told in b1.ch01]" in act2
    act1 = next(c for c in llm.calls if "events need, b1.ch01 onward" in c["messages"][-1]["content"])["messages"][-1]["content"]
    assert "RESERVED FOR LATER" not in act1 and "e3 (once" not in act1 and "NOT YET TOLD" in act1  # act 2's events are not shown at all in act 1 (need-to-know)
    assert "Reference only" in act1 and "must never become a beat" in act1


def test_acts_whose_events_interleave_are_corrected_then_block(project):
    p = project_ready(project)
    bad = copy.deepcopy(acts())
    bad["acts"][0]["events"] = ["e1", "e3"]  # the two acts take turns: judgement, not a slip
    bad["acts"][1]["events"] = ["e2", "e4"]
    llm = RuleLLM([("Divide the book into ACTS by assigning", dump(bad))])
    summary = run(p, llm, HANDLERS, until="acts")
    assert summary.stopped == "failed" and "acts_out_of_order" in summary.detail and p.state.layers["acts"].status == "flagged"
    assert any("acts_out_of_order" in c["messages"][-1]["content"] for c in llm.calls[1:])  # the error was fed back


def test_chapters_that_retell_an_event_are_put_right_and_the_slip_is_told_once(project):
    p = project_ready(project)
    bad = chapters(1)
    bad["chapters"][0]["events_covered"] = ["e1", "e2"]
    bad["chapters"][1]["events_covered"] = ["e1", "e2"]  # both chapters tell both events: a mechanical slip, told once where the words fit
    other = [("Plan the chapters this act's events need, b1.ch01 onward", dump(bad))]
    summary = run(p, RuleLLM(other + rules()), HANDLERS, until="chapters")
    assert summary.ran == ["acts", "chapters"], summary.detail
    told = [x for c in store.load_chapters(p)[:2] for x in c.events_covered]
    assert sorted(told) == ["e1", "e2"]


def test_derived_complications_join_the_ledger_and_obey_the_rules(project):
    p = project_ready(project)
    good = chapters(1)
    good["derived_events"] = [dict(id="e1.1", text="A dockhand sees her take it", parent="e1", after=["e1"], weight=1, kind="event")]
    good["chapters"][0]["events_covered"] = ["e1", "e1.1"]
    summary = run(p, RuleLLM([("Plan the chapters this act's events need, b1.ch01 onward", dump(good))] + rules()), HANDLERS, until="chapters")
    assert summary.ran == ["acts", "chapters"], summary.detail
    led = store.load_ledger(p)
    child = next(e for e in led.events if e.id == "e1.1")
    assert child.source == "derived" and child.parent == "e1" and [e.id for e in led.events][:2] == ["e1", "e1.1"]
    major = copy.deepcopy(good)
    major["derived_events"][0]["weight"] = 3
    p2 = project_ready(__import__("conftest").Project.create(p.root.parent / "second", "x\n"))
    s2 = run(p2, RuleLLM([("Plan the chapters this act's events need, b1.ch01 onward", dump(major))] + rules()), HANDLERS, until="chapters")
    assert s2.ran == ["acts", "chapters"], s2.detail  # a complication is minor by construction: the weight the model wrote is replaced
    assert next(e for e in store.load_ledger(p2).events if e.id == "e1.1").weight == 1


def test_a_derived_complication_no_chapter_tells_is_left_out_not_a_failure(project):
    p = project_ready(project)
    unused = chapters(1)
    unused["derived_events"] = [dict(id="e1.1", text="A dockhand sees her take it", parent="e1", after=["e1"], weight=1, kind="event")]  # declared, never listed
    summary = run(p, RuleLLM([("Plan the chapters this act's events need, b1.ch01 onward", dump(unused))] + rules()), HANDLERS, until="chapters")
    assert summary.ran == ["acts", "chapters"], summary.detail
    assert "e1.1" not in {e.id for e in store.load_ledger(p).events}


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
    assert "scene_without_end_state" in fed and "chapter_event_not_in_scenes" not in fed  # the event left out of the scenes was put right; an empty end_state is for the model


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
    s = run(p, RuleLLM([("Plan the chapters this act's events need, b1.ch01 onward", dump(padded))] + rules()), HANDLERS, until="chapters")
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
    assert any("Make the harbor feel colder." in t and "events need" in t for t in prompts)
    assert any("Keep every scene short." in t and "Scene ids are consecutive" in t for t in prompts)


def test_a_whole_book_failure_plans_the_involved_acts_again_with_the_findings(project, monkeypatch):
    from bookforge import steering
    from bookforge.validators import findings as F, tension
    p = project_ready(project)
    calls = {"n": 0}

    def flat_once(chapters, stage="chapters", spread=2):
        calls["n"] += 1
        return [F.hard("chapters", "event_before_cause", "b1.ch04 covers an event before its cause", ["b1.ch03", "b1.ch04"])] if calls["n"] == 1 else []

    monkeypatch.setattr(tension, "flat_stretches", flat_once)
    first = run(p, RuleLLM(rules()), HANDLERS, until="chapters")
    assert first.stopped == "failed" and "act2 will be planned again" in first.detail
    note = steering.read(p, "chapters")
    assert steering.CHECKS_MARKER in note and "event_before_cause" in note
    llm = RuleLLM(rules())
    second = run(p, llm, HANDLERS, until="chapters")
    assert second.ran == ["chapters"], second.detail
    asked = [next(m["content"] for m in c["messages"] if m["role"] == "user") for c in llm.calls]
    act2 = [t for t in asked if "Plan the chapters this act's events need, b1.ch03 onward" in t]
    assert act2 and "Why the previous attempt was rejected" in act2[0] and "event_before_cause" in act2[0]
    assert not any("Plan the chapters this act's events need, b1.ch01 onward" in t for t in asked)  # act 1 was fine: its saved piece is reused
    assert steering.read(p, "chapters") == ""  # the note is gone once the layer is accepted


def test_a_whole_book_scene_failure_plans_only_the_chapters_it_names_again(project, monkeypatch):
    from bookforge.validators import findings as F, repeats
    p = project_ready(project)
    state = {"n": 0}

    def action_once(scenes, chapters, names=frozenset(), stage="scenes"):
        state["n"] += 1
        return [F.hard("scenes", "chapter_event_not_in_scenes", "an event is shown in no scene", ["b1.ch02", "b1.ch03.s1"])] if state["n"] == 1 else []

    monkeypatch.setattr(repeats, "action_patterns", action_once)
    first = run(p, RuleLLM(rules()), HANDLERS, until="scenes")
    assert first.stopped == "failed" and "Chapters ch02, ch03 will be planned again" in first.detail
    llm = RuleLLM(rules())
    second = run(p, llm, HANDLERS, until="scenes")
    assert second.ran == ["scenes"], second.detail
    asked = " ".join(next(m["content"] for m in c["messages"] if m["role"] == "user") for c in llm.calls)
    assert "Scene ids are consecutive: b1.ch02.s1" in asked and "Scene ids are consecutive: b1.ch03.s1" in asked
    assert "Scene ids are consecutive: b1.ch01.s1" not in asked and "Scene ids are consecutive: b1.ch04.s1" not in asked


@pytest.mark.real_prose_checks
def test_a_written_scene_that_never_shows_its_listed_event_is_a_soft_finding(project):
    from bookforge import scenefiles
    from bookforge.validators.book import prose_findings
    p = project_ready(project)
    run(p, RuleLLM(rules()), HANDLERS, until="scenes")
    sc = store.load_scenes(p)
    first = next(s for s in sc if s.events)  # lists e1: "Anna finds the ledger"
    weather = "The fog rolled in over the grey water and the gulls complained along the pier while the fishermen mended their nets in silence. " * 25
    scenefiles.scene_dir(p, first.id).mkdir(parents=True, exist_ok=True)
    scenefiles.final_path(p, first.id).write_text(weather)
    found, _ = prose_findings(p)
    assert any(f.code == "prose_misses_event" and f.items == [first.id, first.events[0]] and f.severity == "soft" for f in found)
    scenefiles.final_path(p, first.id).write_text(weather + " Anna found the ledger half buried under the nets, a black ledger bound in cloth. " * 3)
    assert not any(f.code == "prose_misses_event" for f in prose_findings(p)[0])


def test_a_derived_complication_written_loosely_is_understood():
    from bookforge.bible.validate import normalize_derived
    per = {}
    first = normalize_derived({"description": "A guard nearly spots her", "parent": "e3"}, per)
    second = normalize_derived({"summary": "The gate sticks", "parent": "e3", "weight": 1}, per)
    assert first == {"description": "A guard nearly spots her", "parent": "e3", "text": "A guard nearly spots her", "id": "e3.1", "after": ["e3"], "weight": 1, "kind": "event"}
    assert second["id"] == "e3.2" and second["text"] == "The gate sticks"
    assert normalize_derived({"id": "e5.1", "text": "x"}, {})["parent"] == "e5"  # the parent follows from the id
    assert "text" not in normalize_derived({"id": "e5.1"}, {})  # nothing to use: the validator says so


def test_the_chapter_planner_of_an_act_sees_neither_other_acts_summaries_nor_its_own(project):
    p = project_ready(project)
    llm = RuleLLM(rules())
    run(p, llm, HANDLERS, until="chapters")
    act1 = next(next(m["content"] for m in c["messages"] if m["role"] == "user") for c in llm.calls if "events need, b1.ch01 onward" in c["messages"][-1]["content"])
    assert "What happens in act 1." not in act1 and "What happens in act 2." not in act1 and "The turn of act 2." not in act1
    assert "b1.act2 Act 2 (2 chapters) (planned later: nothing of it may appear here)" in act1 and "purpose" in act1
    from bookforge.ledger_view import carried_text  # noqa: F401  (the event texts reach the planner through the ledger status instead)
    assert "ASSIGNED HERE" in act1 and "Anna finds the ledger" in act1


def test_a_cast_that_was_saved_by_an_earlier_failed_run_and_is_listed_again_does_not_fail_the_layer(project):
    import structure_fakes as sf
    from bookforge.bible.models import Constants, Entity, Rule
    p = project_ready(project)
    data = sf.cast()
    store.save_constants(p, Constants(entities=[Entity(**e) for e in data["entities"]], rules=[Rule(**r) for r in data["rules"]]))  # what the failed run left behind
    summary = run(p, RuleLLM(rules()), HANDLERS, until="chapters")  # the scripted model lists the whole cast again
    assert summary.ran == ["acts", "chapters"], summary.detail
    assert len(store.load_constants(p).entities) == 5  # nothing duplicated


def test_a_failed_layer_leaves_the_bible_exactly_as_it_was(project, monkeypatch):
    from bookforge.layers import structure
    p = project_ready(project)
    before = {n: (f.read_bytes() if f.exists() else None) for n, f in (("constants", store.constants_path(p)), ("tracks", store.tracks_path(p)),
                                                                      ("chapters", store.chapters_path(p)), ("ledger", store.ledger_path(p)))}
    monkeypatch.setattr(structure, "validate_chapters_file", lambda project: ["the assembled chapters do not hold together (a test)"])
    failed = run(p, RuleLLM(rules()), HANDLERS, until="chapters")
    assert failed.stopped == "failed"
    after = {n: (f.read_bytes() if f.exists() else None) for n, f in (("constants", store.constants_path(p)), ("tracks", store.tracks_path(p)),
                                                                     ("chapters", store.chapters_path(p)), ("ledger", store.ledger_path(p)))}
    assert after == before  # no cast, no track, no chapter, no derived event from the failed attempt
    monkeypatch.undo()
    assert run(p, RuleLLM(rules()), HANDLERS, until="chapters").ran == ["chapters"]  # and the saved pieces still make the rerun cheap


def test_a_failed_scenes_layer_leaves_the_bible_exactly_as_it_was(project, monkeypatch):
    from bookforge.layers import structure
    p = project_ready(project)
    run(p, RuleLLM(rules()), HANDLERS, until="chapters")
    paths = {"constants": store.constants_path(p), "tracks": store.tracks_path(p), "timeline": store.timeline_path(p), "scenes": store.scenes_path(p)}
    before = {n: (f.read_bytes() if f.exists() else None) for n, f in paths.items()}
    monkeypatch.setattr(structure, "validate_scenes_file", lambda project: ["the assembled scenes do not hold together (a test)"])
    assert run(p, RuleLLM(rules()), HANDLERS, until="scenes").stopped == "failed"
    assert {n: (f.read_bytes() if f.exists() else None) for n, f in paths.items()} == before


def test_an_act_whose_events_run_out_ends_with_fewer_chapters_than_its_ceiling(project):
    p = project_ready(project)
    p.config.layers["chapters"].count = None  # no fixed total: the model sizes the acts
    plan = copy.deepcopy(acts())
    for a in plan["acts"]:
        a["chapter_count"] = 3  # an estimate of 3 for events that only fill 2
        a["sizing_reason"] = "override: the author asked for a longer act than the weights suggest"
    first = [("Plan the chapters this act's events need, b1.ch01 onward", dump(chapters(1)))]
    second = [("Plan the chapters this act's events need, b1.ch03 onward", dump(chapters(3)))]  # the second act starts at chapter 3: the first ended after 2
    llm = RuleLLM([("Divide the book into ACTS by assigning", dump(plan))] + first + second + rules())
    summary = run(p, llm, HANDLERS, until="chapters")
    assert summary.ran == ["acts", "chapters"], summary.detail
    assert [a.chapter_count for a in store.load_acts(p)] == [2, 2] and len(store.load_chapters(p)) == 4


def test_a_last_chapter_that_only_repeats_the_acts_events_is_dropped(project):
    p = project_ready(project)
    p.config.layers["chapters"].count = None
    plan = copy.deepcopy(acts())
    for a in plan["acts"]:
        a["chapter_count"] = 3
        a["sizing_reason"] = "override: the author asked for a longer act than the weights suggest"
    padded = chapters(1)
    extra = copy.deepcopy(padded["chapters"][1])
    extra["id"] = "b1.ch03"
    padded["chapters"].append(extra)  # the same event as chapter 2, nothing new
    llm = RuleLLM([("Divide the book into ACTS by assigning", dump(plan)), ("Plan the chapters this act's events need, b1.ch01 onward", dump(padded)),
                   ("Plan the chapters this act's events need, b1.ch03 onward", dump(chapters(3)))] + rules())
    summary = run(p, llm, HANDLERS, until="chapters")
    assert summary.ran == ["acts", "chapters"], summary.detail
    assert len(store.load_chapters(p)) == 4 and [a.chapter_count for a in store.load_acts(p)] == [2, 2]


def test_a_wrong_weight_in_an_acts_reasoning_is_corrected_without_a_correction_round(project):
    p = project_ready(project)
    plan = copy.deepcopy(acts())
    for a in plan["acts"]:
        a["sizing_reason"] = "two events with a combined weight of 7 fill two chapters"  # the real weight is 4
    llm = RuleLLM([("Divide the book into ACTS by assigning", dump(plan))] + rules())
    summary = run(p, llm, HANDLERS, until="acts")
    assert summary.ran == ["acts"], summary.detail
    assert len([c for c in llm.calls if "Divide the book into ACTS" in c["messages"][-1]["content"]]) == 1  # accepted at once
    assert all("weight of 4" in a.sizing_reason and "weight of 7" not in a.sizing_reason for a in store.load_acts(p))


def test_a_flat_stretch_is_fixed_by_the_whole_book_check_or_kept_as_a_warning_when_the_fix_cannot(project, monkeypatch):
    from bookforge import healing
    from bookforge.layers.runner import StepContext
    from bookforge.layers.structure import _book_chapter_checks
    from bookforge.validators import findings as F, tension
    p = project_ready(project)
    run(p, RuleLLM(rules()), HANDLERS, until="chapters")

    def flat_when_all_equal(chapters, stage="chapters", spread=2):  # a stand-in for the real check, which needs a longer book
        return [F.hard("chapters", "flat_tension", "tension is flat", [c["id"] for c in chapters])] if len({c["tension"] for c in chapters}) == 1 else []

    monkeypatch.setattr(tension, "flat_stretches", flat_when_all_equal)
    flat = [c.model_copy(update={"tension": 9}) for c in store.load_chapters(p)]
    ids = [c.id for c in flat]
    good = json.dumps({"tension": {i: v for i, v in zip(ids, [4, 8, 3, 9])}})
    healing.begin(p, "chapters")
    _book_chapter_checks(p, flat, store.load_ledger(p), StepContext(project=p, layer="chapters", llm=RuleLLM([("Rate the tension of the chapters listed below again", good)])))
    assert [c.tension for c in flat] == [4, 8, 3, 9]
    assert any("rated again" in n for n in healing.commit(p, "chapters"))
    flat2 = [c.model_copy(update={"tension": 9}) for c in flat]
    still_flat = json.dumps({"tension": {i: 9 for i in ids}})
    _book_chapter_checks(p, flat2, store.load_ledger(p), StepContext(project=p, layer="chapters", llm=RuleLLM([("Rate the tension of the chapters listed below again", still_flat)])))  # no stop
    saved = json.loads((p.book_dir / "validation" / "chapters.json").read_text())
    warn = [f for f in saved["findings"] if f["code"] == "flat_tension"]
    assert warn and all(f["severity"] == "soft" and "kept as a warning" in f["message"] for f in warn)
    assert [c.tension for c in flat2] == [9, 9, 9, 9]  # the saved ratings were not touched


def test_the_b2_shape_all_scenes_on_day_one_in_different_places_no_longer_stops_the_scenes_stage(project):
    """46 blocking items came from this: every scene on day 1, morning, in different settings, and a track that goes back to an earlier state."""
    from bookforge.layers.runner import StepContext
    from bookforge.layers.structure import _book_scene_checks
    p = project_ready(project)
    run(p, RuleLLM(rules()), HANDLERS, until="scenes")
    chapters_, scenes_, tracks_ = store.load_chapters(p), store.load_scenes(p), store.load_tracks(p)
    timeline = [t.model_copy(update={"day": 1, "time": "morning"}) for t in store.load_timeline(p)]
    for i, s in enumerate(scenes_):
        s.setting = ["harbor", "vestry", "quay", "cockpit"][i % 4]
    rel = _book_scene_checks(p, chapters_, scenes_, timeline, tracks_, store.load_constants(p), store.load_ledger(p), StepContext(project=p, layer="scenes", llm=RuleLLM([])))
    saved = json.loads((p.root / rel).read_text())["findings"]
    assert not any(f["code"] == "two_places_at_once" for f in saved)  # scenes are a sequence: no conflict between them
    flat = [f for f in saved if f["code"] == "timeline_flat"]
    assert flat and all(f["severity"] == "soft" and "kept as a warning" in f["message"] for f in flat)  # reported, and the run goes on
    assert not any(f["severity"] == "hard" for f in saved)
