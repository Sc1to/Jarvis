"""Phase 4 of the intake: the book's mode decides whether the tool applies what the prose brought in; Undo; the record; the impact lines."""

import json

import pytest

from bookforge import answers, changes, ops, resolve
from bookforge.bible import store
from bookforge.layers import HANDLERS
from bookforge.layers.runner import run
from bookforge.project import Project
from conftest import RuleLLM
from ledger_structure_fakes import install_ledger, rules
from structure_fakes import ready

ENTITY = {"kind": "entity", "name": "Marek", "entity_kind": "character", "quote": "Marek stood at the end of it with his coat open",
          "facts": ["Marek stood at the end of the quay with his coat open"], "same_as": ""}
EVENT = {"kind": "event", "text": "Marek accuses Anna of taking the ledger", "quote": "Marek did not look at her; he watched the water"}


@pytest.fixture
def book(project):
    p = ready(project)
    install_ledger(p)
    assert run(p, RuleLLM(rules()), HANDLERS, until="scenes").ran == ["acts", "chapters", "scenes"]
    return Project.open(p.root)


def scene(book):
    return next(s for s in store.load_scenes(book) if s.id == "b1.ch01.s1")


def cast_ids(book):
    return {e.id for e in store.load_constants(book).entities}


def test_shadow_applies_nothing(book):
    crs = changes.file_new(book, scene(book), [ENTITY, EVENT])
    assert [c.status for c in crs] == ["pending", "pending"] and "marek" not in cast_ids(book)


def test_assist_applies_a_verified_entity_and_leaves_the_development(book):
    answers.set_mode(book, "assist")
    ent, ev = changes.file_new(book, scene(book), [ENTITY, EVENT])
    assert (ent.status, ent.decided_by) == ("applied", "tool") and "marek" in cast_ids(book)
    assert ev.status == "pending"
    assert resolve.decision_stats(book)["intake_entity"]["applied"] == 1


def test_auto_also_registers_a_minor_development(book):
    answers.set_mode(book, "auto")
    ent, ev = changes.file_new(book, scene(book), [ENTITY, EVENT])
    assert ev.status == "applied" and ev.proposal["event_id"] == "e1.1"
    assert any(e.id == "e1.1" for e in store.load_ledger(book).events)


def test_a_possible_alias_a_weak_kind_or_no_facts_is_never_applied_by_the_tool(book):
    answers.set_mode(book, "auto")
    existing = next(e for e in store.load_constants(book).entities if e.kind == "character")
    alias = {**ENTITY, "name": existing.name.split()[0] + "s"[:0]}  # shares a name with someone in the cast
    group = {**ENTITY, "name": "Harbourfolk", "entity_kind": "group"}
    nofacts = {**ENTITY, "name": "Perrin", "facts": []}
    for item in (alias, group, nofacts):
        [cr] = changes.file_new(book, scene(book), [item])
        assert cr.status == "pending", item["name"]


def test_an_alias_is_settled_as_nothing_to_add(book):
    answers.set_mode(book, "assist")
    existing = next(e for e in store.load_constants(book).entities if e.kind == "character")
    before = cast_ids(book)
    [cr] = changes.file_new(book, scene(book), [{**ENTITY, "name": "The Warden", "same_as": existing.id}])
    assert cr.status == "applied" and cast_ids(book) == before
    assert "another name for" in changes.impact(book, cr)[0]


def test_a_demoted_outcome_is_only_suggested(book):
    answers.set_mode(book, "assist")
    for i in range(6):
        resolve.log_outcome(book, f"cr-x{i}", "intake_entity", "overridden", "proposal")
    assert "intake_entity" in resolve.demoted(book)
    [cr] = changes.file_new(book, scene(book), [ENTITY])
    assert cr.status == "pending"


def test_a_refused_application_leaves_the_request_waiting_with_the_reason(book):
    answers.set_mode(book, "auto")
    for i in range(3):
        changes.file_new(book, scene(book), [{**EVENT, "text": f"Complication number {i} happens at the quay"}])
    [cr] = changes.file_new(book, scene(book), [{**EVENT, "text": "One complication too many at the quay"}])
    assert cr.status == "pending" and "could not" in changes.get(book, cr.id).reason


def test_undo_takes_the_entry_and_the_development_back(book):
    answers.set_mode(book, "auto")
    ent, ev = changes.file_new(book, scene(book), [ENTITY, EVENT])
    ops.undo_change(book, ent.id)
    ops.undo_change(book, ev.id)
    assert "marek" not in cast_ids(book) and not any(e.id == "e1.1" for e in store.load_ledger(book).events)
    assert {changes.get(book, c.id).status for c in (ent, ev)} == {"pending"}
    assert "e1.1" not in next(c for c in store.load_chapters(book) if c.id == "b1.ch01").events_covered
    assert resolve.decision_stats(book)["intake_entity"]["undone"] == 1
    with pytest.raises(changes.ChangeError):
        ops.undo_change(book, ent.id)  # no longer applied by the tool


def test_undo_is_refused_while_the_plan_uses_the_entity(book):
    answers.set_mode(book, "assist")
    [cr] = changes.file_new(book, scene(book), [ENTITY])
    scenes = store.load_scenes(book)
    scenes[0].characters.append("marek")
    store.save_scenes(book, scenes)
    with pytest.raises(changes.ChangeError, match="still used|cannot take"):
        ops.undo_change(book, cr.id)
    assert "marek" in cast_ids(book)


def test_what_you_decide_is_recorded_in_every_mode(book):
    a, b = changes.file_new(book, scene(book), [ENTITY, EVENT])
    ops.decide_change(book, a.id, True)
    ops.decide_change(book, b.id, False, dismiss=True)
    stats = resolve.decision_stats(book)
    assert stats["intake_entity"]["accepted"] == 1 and stats["intake_event"]["overridden"] == 1


def test_the_impact_lines_say_what_approving_does(book):
    ent, ev = changes.file_new(book, scene(book), [ENTITY, EVENT])
    assert any("Add Marek (character) to the cast" in l for l in changes.impact(book, ent))
    lines = changes.impact(book, ev)
    assert lines[0].startswith("Register a minor complication under e1") and "b1.ch01.s1" in lines[1]


def test_the_report_lists_what_the_tool_applied(book):
    from bookforge import report
    answers.set_mode(book, "assist")
    [cr] = changes.file_new(book, scene(book), [ENTITY])
    text = report.build_report(book)
    assert f"The tool applied change request **{cr.id}**" in text and f"changes --undo {cr.id}" in text
