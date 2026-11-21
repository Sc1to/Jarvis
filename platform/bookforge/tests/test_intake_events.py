"""Phase 2 of the intake: a new development written into a beat can be registered as a minor complication in the ledger, chapter and scene."""

import pytest
import yaml

from bookforge import documents, intake
from bookforge.bible import store
from bookforge.layers import HANDLERS
from bookforge.layers.runner import run
from bookforge.project import Project
from conftest import RuleLLM
from ledger_structure_fakes import install_ledger, rules
from structure_fakes import ready


@pytest.fixture
def book(project):
    p = ready(project)
    install_ledger(p)
    assert run(p, RuleLLM(rules()), HANDLERS, until="scenes").ran == ["acts", "chapters", "scenes"]
    return Project.open(p.root)


NEW = "The harbor master arrives unannounced and demands to see every logbook before the tide turns."


def edit(book, beat=NEW):
    doc = documents.find(book, "scenes")
    old = documents.read(doc)[0]
    data = yaml.safe_load(old)
    data["scenes"][0]["beats"].append(beat)
    return doc, old, yaml.safe_dump(data, sort_keys=False)


def test_a_beat_that_no_event_accounts_for_is_found_and_a_detailed_event_is_not(book):
    doc, old, new = edit(book)
    found = intake.new_event_candidates(book, old, new)
    assert len(found) == 1 and found[0]["scene"] == "b1.ch01.s1" and found[0]["beat"] == NEW and found[0]["parent"] == "e1"
    _, old2, new2 = edit(book, "Anna finds the ledger half buried in the netting near the quay and takes it.")  # tells the chapter's own event in more detail
    assert intake.new_event_candidates(book, old2, new2) == []
    assert intake.new_event_candidates(book, old, old) == []


def test_registering_adds_a_minor_complication_to_ledger_chapter_and_scene(book):
    doc, old, new = edit(book)
    documents.save(book, doc, new)
    ids = intake.register_events(book, [{"scene": "b1.ch01.s1", "parent": "e1", "text": NEW.rstrip(".")}])
    assert ids == ["e1.1"]
    ledger = store.load_ledger(book)
    ev = next(e for e in ledger.events if e.id == "e1.1")
    assert (ev.source, ev.parent, ev.weight, ev.after) == ("derived", "e1", 1, ["e1"])
    assert [e.id for e in ledger.events][:2] == ["e1", "e1.1"]
    assert "e1.1" in next(c for c in store.load_chapters(book) if c.id == "b1.ch01").events_covered
    assert "e1.1" in next(s for s in store.load_scenes(book) if s.id == "b1.ch01.s1").events


def test_a_fourth_complication_is_refused_and_nothing_changes(book):
    for i in range(3):
        intake.register_events(book, [{"scene": "b1.ch01.s1", "parent": "e1", "text": f"Complication number {i} happens at the harbor."}])
    before = store.ledger_path(book).read_text()
    with pytest.raises(intake.IntakeError):
        intake.register_events(book, [{"scene": "b1.ch01.s1", "parent": "e1", "text": "One too many complications."}])
    assert store.ledger_path(book).read_text() == before


def test_a_bad_parent_or_scene_is_refused(book):
    with pytest.raises(intake.IntakeError):
        intake.register_events(book, [{"scene": "b1.ch01.s1", "parent": "e99", "text": "Something happens somewhere."}])
    with pytest.raises(intake.IntakeError):
        intake.register_events(book, [{"scene": "b1.ch09.s9", "parent": "e1", "text": "Something happens somewhere."}])
