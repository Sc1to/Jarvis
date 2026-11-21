"""Phase 3 of the intake: a written scene that brings in a new person or development becomes a change request you decide."""

import json

import pytest

from bookforge import changes
from bookforge.bible import store
from bookforge.layers import HANDLERS
from bookforge.layers.runner import StepContext, run
from bookforge.project import Project
from bookforge.qc import critic, intake_prose
from conftest import RuleLLM
from ledger_structure_fakes import install_ledger, rules
from structure_fakes import ready

TEXT = ("Anna reached the quay as the fog lifted. Marek stood at the end of it with his coat open, and she knew the harbour master by his walk. "
        "Marek did not look at her; he watched the water. \"You took the ledger,\" Marek said at last, and Anna said nothing.")


@pytest.fixture
def book(project):
    p = ready(project)
    install_ledger(p)
    assert run(p, RuleLLM(rules()), HANDLERS, until="scenes").ran == ["acts", "chapters", "scenes"]
    return Project.open(p.root)


def ctx(book, llm):
    return StepContext(project=book, layer="prose", llm=llm)


def test_only_a_name_used_twice_and_missing_from_the_cast_is_a_candidate(book):
    constants = store.load_constants(book)
    assert intake_prose.candidate_names(TEXT, constants) == ["marek"]
    assert intake_prose.candidate_names("Anna met Jonas. Fog came on Tuesday, then Perrin left.", constants) == []  # known names; single mentions


def reply(**over):
    item = {"name": "marek", "verdict": "new_entity", "kind": "character", "same_as": "", "quote": "Marek stood at the end of it with his coat open",
            "facts": ["Marek stood at the end of the quay with his coat open", "Marek is a retired admiral of the fleet"]}
    item.update(over)
    return json.dumps({"names": [item]})


def test_a_new_name_is_classified_and_only_facts_the_scene_states_are_kept(book):
    scene = store.load_scenes(book)[0]
    found = intake_prose.new_entities(ctx(book, RuleLLM([("These capitalised names appear in it", reply())])), scene, TEXT)
    assert len(found) == 1 and found[0]["entity_kind"] == "character"
    assert found[0]["facts"] == ["Marek stood at the end of the quay with his coat open"]  # the invented admiral is dropped


def test_an_unquoted_or_unasked_name_is_dropped(book):
    scene = store.load_scenes(book)[0]
    bad = RuleLLM([("These capitalised names appear in it", reply(quote="words that are not in the scene at all"))])
    assert intake_prose.new_entities(ctx(book, bad), scene, TEXT) == []
    other = RuleLLM([("These capitalised names appear in it", reply(name="Zed"))])
    assert intake_prose.new_entities(ctx(book, other), scene, TEXT) == []


def test_the_critics_unplanned_developments_must_quote_the_scene():
    raw = [{"what": "Marek accuses Anna of taking the ledger", "quote": "Marek did not look at her; he watched the water"},
           {"what": "a storm destroys the quay", "quote": "the storm tore the quay to pieces and nothing remained"}]
    kept = critic.clean_unplanned(raw, TEXT)
    assert [k["what"] for k in kept] == ["Marek accuses Anna of taking the ledger"]
    assert intake_prose.new_events({"critic": {"unplanned": kept}}, TEXT)[0]["kind"] == "event"


def test_approving_a_new_entity_adds_it_to_the_cast_and_rejecting_leaves_the_cast(book):
    scene = store.load_scenes(book)[0]
    found = [{"kind": "entity", "name": "Marek", "entity_kind": "character", "quote": "Marek stood at the end of it with his coat open",
              "facts": ["Marek stood at the end of the quay with his coat open"], "same_as": ""}]
    [cr] = changes.file_new(book, scene, found)
    assert (cr.kind, cr.status, cr.observed) == ("entity", "pending", "Marek")
    assert changes.file_new(book, scene, found) == []  # not proposed twice
    changes.approve(book, cr.id)
    assert any(e.id == "marek" and e.kind == "character" for e in store.load_constants(book).entities)
    assert "not in the plan or the cast" in changes.get(book, cr.id).message()


def test_approving_a_new_event_registers_it_in_the_ledger(book):
    scene = next(s for s in store.load_scenes(book) if s.id == "b1.ch01.s1")
    [cr] = changes.file_new(book, scene, [{"kind": "event", "text": "Marek accuses Anna of taking the ledger", "quote": "Marek did not look at her; he watched the water"}])
    assert cr.kind == "event"
    changes.approve(book, cr.id)
    ev = next(e for e in store.load_ledger(book).events if e.text.startswith("Marek accuses"))
    assert ev.source == "derived" and ev.parent == "e1"


def test_dismissing_changes_nothing_in_the_plan(book):
    scene = store.load_scenes(book)[0]
    [cr] = changes.file_new(book, scene, [{"kind": "event", "text": "Something else happens at the quay", "quote": "x y z a b c"}])
    before = store.ledger_path(book).read_text()
    changes.dismiss(book, cr.id)
    assert store.ledger_path(book).read_text() == before and changes.get(book, cr.id).status == "dismissed"
