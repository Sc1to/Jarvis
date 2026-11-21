"""Phase 1 of the intake: an edit that names a character the cast lacks is not refused outright; it offers to add the character and saves both together."""

import pytest
import yaml

from bookforge import documents
from bookforge.bible import store
from bookforge.layers import HANDLERS
from bookforge.layers.runner import run
from bookforge.project import Project
from conftest import RuleLLM
from structure_fakes import ready, rules


@pytest.fixture
def book(project):
    p = ready(project)
    assert run(p, RuleLLM(rules()), HANDLERS).stopped == "checkpoint"
    return Project.open(p.root)


def edited(book, new_id="sheriff-marek"):
    doc = documents.find(book, "scenes")
    data = yaml.safe_load(documents.read(doc)[0])
    first = data["scenes"][0]
    first["characters"].append(new_id)
    first["beats"].append("Sheriff Marek arrives at the harbor and questions Anna about the missing ledger.")
    return doc, yaml.safe_dump(data, sort_keys=False)


def test_an_edit_naming_an_unknown_character_offers_to_add_it(book):
    doc, text = edited(book)
    before = documents.read(doc)[0]
    with pytest.raises(documents.EditNeedsCast) as e:
        documents.save(book, doc, text)
    item = e.value.proposal[0]
    assert item["id"] == "sheriff-marek" and item["kind"] == "character" and item["name"] == "Sheriff Marek"
    assert any("Sheriff Marek arrives at the harbor" in f for f in item["facts"])  # the author's own words
    assert documents.read(doc)[0] == before  # nothing was saved


def test_saving_with_the_cast_adds_both_or_neither(book):
    doc, text = edited(book)
    added = documents.save_with_cast(book, doc, text, [{"id": "sheriff-marek", "kind": "character", "name": "Sheriff Marek", "facts": ["He questions Anna about the ledger."]}])
    assert added == ["sheriff-marek"]
    assert any(e.id == "sheriff-marek" for e in store.load_constants(book).entities)
    assert "sheriff-marek" in documents.read(doc)[0]


def test_a_second_name_for_an_existing_entity_changes_the_text_not_the_cast(book):
    cast = {e.id: e for e in store.load_constants(book).entities}
    existing = next(i for i, e in cast.items() if e.kind == "character")
    doc, text = edited(book, new_id="the-" + existing.split("-")[0])
    with pytest.raises(documents.EditNeedsCast) as e:
        documents.save(book, doc, text)
    assert existing in e.value.proposal[0]["may_be"]
    before = len(cast)
    documents.save_with_cast(book, doc, text, [{"id": "the-" + existing.split("-")[0], "alias_of": existing}])
    assert len(store.load_constants(book).entities) == before and "the-" + existing.split("-")[0] not in documents.read(doc)[0]


def test_a_refused_edit_takes_the_added_entities_out_again(book):
    doc, text = edited(book)
    broken = text + "\nnot: [valid"
    with pytest.raises(Exception):
        documents.save_with_cast(book, doc, broken, [{"id": "sheriff-marek", "kind": "character", "name": "Sheriff Marek", "facts": ["x is here."]}])
    assert not any(e.id == "sheriff-marek" for e in store.load_constants(book).entities)


def test_other_problems_are_still_a_plain_refusal(book):
    doc = documents.find(book, "scenes")
    data = yaml.safe_load(documents.read(doc)[0])
    data["scenes"][0]["pov"] = "ghost-person"
    data["scenes"][0]["chapter"] = "b1.ch99"
    with pytest.raises(documents.EditRefused) as e:
        documents.save(book, doc, yaml.safe_dump(data, sort_keys=False))
    assert not isinstance(e.value, documents.EditNeedsCast)
