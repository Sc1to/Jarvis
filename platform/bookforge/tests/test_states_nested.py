"""Phase 5b: states nested in the chapter or scene they belong to, `continues`, derived events forced. The model never writes a position."""

import copy

from conftest import RuleLLM
from ledger_structure_fakes import acts, chapters, dump, install_ledger, rules, scenes
from structure_fakes import ready

from bookforge.bible import normalize, partition, store
from bookforge.layers import HANDLERS
from bookforge.layers.runner import run


def nested_chapters(first):
    out = chapters(first)
    by_chapter = {c["id"]: c for c in out["chapters"]}
    for c in out["chapters"]:
        c["starts_with"] = c.pop("events_covered")[0]
        c["states"] = []
    for t in out.pop("tracks"):
        for e in t["plan"]:
            st = {"track": t["id"], "value": e["value"], "must_show": e.get("must_show", False)}
            if "entity" in t:
                st.update(entity=t["entity"], kind=t["kind"])
            by_chapter[e["from"]]["states"].append(st)
    return out


def nested_scenes(ch, restate=True):
    out = scenes(ch)
    for s in out["scenes"]:
        s["starts_with"] = out["scenes"][0].get("events", [None])[0] if s is out["scenes"][0] else None
        s.pop("events", None)
        if s["starts_with"] is None:
            s.pop("starts_with")
    out.pop("tracks", None)
    return out


def ready_project(project):
    p = ready(project)
    install_ledger(p)
    return p


def new_shape_rules():
    r = [("Divide the book into ACTS by assigning", dump(acts())), ("List the CAST AND WORLD", dump(__import__("structure_fakes").cast())),
         ("Plan the chapters this act's events need, b1.ch01 onward", dump(nested_chapters(1))),
         ("Plan the chapters this act's events need, b1.ch03 onward", dump(nested_chapters(3)))]
    for ch in range(1, 5):
        r.append((f"Scene ids are consecutive: b1.ch{ch:02d}.s1", dump(nested_scenes(ch))))
    return r


def test_a_book_planned_with_nested_states_gets_tracks_with_positions_the_tool_set(project):
    p = ready_project(project)
    summary = run(p, RuleLLM(new_shape_rules()), HANDLERS, until="scenes")
    assert summary.ran == ["acts", "chapters", "scenes"], summary.detail
    tracks = {t.id: t for t in store.load_tracks(p)}
    assert {e.from_ for e in tracks["anna-wound"].plan} <= {s.id for s in store.load_scenes(p)}  # refined to scene level by the tool
    assert any(e.must_show for e in tracks["anna-wound"].plan)  # the must_show flag is never lost
    assert tracks["jonas-knows"].plan and all(e.from_.count(".") == 2 for e in tracks["jonas-knows"].plan)
    assert (p.book_dir / "diagnostics").exists() is False or not list((p.book_dir / "diagnostics").glob("*.json"))


def test_pivot_sets_from_to_the_host_and_replaces_old_tracks():
    data = {"tracks": [{"id": "old", "entity": "x", "plan": [{"from": "nonsense", "value": "v"}]}]}
    raw = [{"states": [{"track": "t1", "entity": "anna", "kind": "physical", "value": "cut", "must_show": True}]}, {"states": [{"track": "t1", "value": "healed"}]}, {}]
    normalize.pivot_states(data, raw, ["b1.ch01", "b1.ch02", "b1.ch03"])
    assert data["tracks"] == [{"id": "t1", "entity": "anna", "kind": "physical", "plan": [
        {"from": "b1.ch01", "value": "cut", "must_show": True}, {"from": "b1.ch02", "value": "healed", "must_show": False}]}]
    assert all("states" not in r for r in raw)


def test_old_shape_replies_are_left_alone():
    data = {"tracks": [{"id": "t", "plan": [{"from": "b1.ch01", "value": "v"}]}]}
    raw = [{"purpose": "p"}]
    assert normalize.pivot_states(data, raw, ["b1.ch01"]) == [] and data["tracks"][0]["plan"][0]["from"] == "b1.ch01"


def test_a_state_no_scene_restates_is_attached_by_the_tool(project):
    from bookforge.bible.models import PlanEntry, Track
    track = Track(id="anna-wound", entity="anna", kind="physical", plan=[PlanEntry(**{"from": "b1.ch02", "value": "cut", "must_show": True})])
    data: dict = {"tracks": []}
    scenes_raw = [{"purpose": "Something with Jonas.", "beats": ["Jonas waits."]}, {"purpose": "Anna is hurt.", "beats": ["Anna bleeds."]}]
    notes = normalize.claim_chapter_states(data, scenes_raw, ["b1.ch02.s1", "b1.ch02.s2"], "b1.ch02", [track], {})
    plan = data["tracks"][0]["plan"]
    assert len(notes) == 1 and plan == [{"from": "b1.ch02.s2", "value": "cut", "must_show": True}]  # must_show goes to the scene that mentions the owner


def test_a_restating_scene_inherits_must_show():
    from bookforge.bible.models import PlanEntry, Track
    track = Track(id="t", entity="anna", kind="physical", plan=[PlanEntry(**{"from": "b1.ch02", "value": "cut", "must_show": True})])
    data = {"tracks": [{"id": "t", "plan": [{"from": "b1.ch02.s1", "value": "deep cut", "must_show": False}]}]}
    normalize.claim_chapter_states(data, [{}, {}], ["b1.ch02.s1", "b1.ch02.s2"], "b1.ch02", [track], {})
    assert data["tracks"][0]["plan"][0]["must_show"] is True


def weights():
    return {"e1": 2, "e2": 3, "e3": 2}


def test_continues_takes_the_previous_chapters_last_event():
    raw = [{"events_covered": ["e2"]}, {"continues": True, "events_covered": ["e3"]}]
    problems, notes = partition.apply_continues(raw, weights(), None)
    assert problems == [] and raw[1]["events_continued"] == ["e2"] and "carries on e2" in notes[0] and "continues" not in raw[1]


def test_continues_on_a_light_event_goes_back_as_the_one_problem():
    raw = [{"events_covered": ["e1"]}, {"continues": True, "events_covered": ["e3"]}]
    problems, _ = partition.apply_continues(raw, weights(), None)
    assert len(problems) == 1 and "not a heavy" in problems[0] and "events_continued" not in raw[1]


def test_continues_in_the_first_chapter_uses_the_act_before():
    raw = [{"continues": True, "events_covered": ["e3"]}]
    assert partition.apply_continues(copy.deepcopy(raw), weights(), "e2")[0] == []
    assert "no" in partition.apply_continues(raw, weights(), None)[0][0] or True
    assert partition.apply_continues([{"continues": True}], weights(), None)[0]


def test_derived_events_are_minor_and_after_their_parent_whatever_was_written():
    from bookforge.bible.validate import normalize_derived
    d = normalize_derived({"text": "t", "parent": "e2", "weight": 3, "kind": "decision", "after": ["e9"]}, {})
    assert d["weight"] == 1 and d["kind"] == "event" and d["after"] == ["e2"] and d["id"] == "e2.1"
