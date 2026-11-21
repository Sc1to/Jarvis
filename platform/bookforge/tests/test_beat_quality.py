"""Beat quality: placeholders, thin material, the optional situation/learns fields, unestablished states, and the beat review gate."""

import json

import pytest

from bookforge.bible import store
from bookforge.bible.models import PlanEntry, Track
from bookforge.briefing import build_briefing
from bookforge.layers import HANDLERS
from bookforge.layers.runner import StepContext, run
from bookforge.project import Project
from bookforge.qc import beat_review
from bookforge.validators import beats as beat_checks
from conftest import RuleLLM
from structure_fakes import ready, rules

SC = {"id": "b1.ch03.s1", "beats": ["Nora notices something unusual about the fridge.", "They find another clue."], "situation": "", "learns": ""}


def test_placeholder_beats_are_found_and_named_ones_are_not():
    found = beat_checks.vague_beats([SC])
    assert [f.code for f in found] == ["beat_vague"] and found[0].severity == "soft" and "beat 1" in found[0].message
    good = {"id": "b1.ch03.s2", "beats": ["Nora opens the fridge in the lodge, closed for three weeks: it holds one opened carton of milk with a use-by date after the closure."]}
    assert beat_checks.vague_beats([good]) == []
    assert beat_checks.vague_beats([{"id": "x", "beats": ["She leaves."]}])[0].code == "beat_vague"  # too short to carry an event


def test_a_scene_far_thinner_than_its_length_is_called_thin():
    thin = {"id": "s", "beats": ["Dan arrives at the lodge and greets Nora politely."], "situation": "", "learns": ""}
    assert [f.code for f in beat_checks.thin_for_range([thin], lambda s: (2000, 3000))] == ["beats_thin_for_range"]
    assert beat_checks.thin_for_range([thin], lambda s: (100, 150)) == []


@pytest.fixture
def book(project):
    p = ready(project)
    assert run(p, RuleLLM(rules()), HANDLERS).stopped == "checkpoint"
    return Project.open(p.root)


def test_situation_and_learns_reach_the_briefing_and_empty_ones_change_no_fingerprint(book):
    sid = "b1.ch02.s2"
    before = build_briefing(book, sid)
    scenes = store.load_scenes(book)
    sc = next(s for s in scenes if s.id == sid)
    assert "Where things stand when it opens" not in next(x.body for x in before.sections if x.heading == "This scene")
    sc.situation, sc.learns = "Anna thinks the ledger is lost.", "Anna learns Jonas has read it."
    store.save_scenes(book, scenes)
    after = build_briefing(book, sid)
    body = next(x.body for x in after.sections if x.heading == "This scene")
    assert "Where things stand when it opens (including what the viewpoint character knows or believes): Anna thinks the ledger is lost." in body
    assert "What is new by the end: Anna learns Jonas has read it." in body
    assert after.deps.scene != before.deps.scene
    sc.situation = sc.learns = ""
    store.save_scenes(book, scenes)
    assert build_briefing(book, sid).deps.scene == before.deps.scene  # an unfilled optional field never makes a scene stale


def test_a_suspected_state_is_shown_apart_and_asked_about_as_not_established(book):
    tracks = store.load_tracks(book)
    tracks.append(Track(id="jonas-suspicion", entity="jonas", kind="knowledge", plan=[PlanEntry(**{"from": "b1.ch01", "value": "Jonas suspects Anna took the ledger", "status": "hypothesis"})]))
    store.save_tracks(book, tracks)
    b = build_briefing(book, "b1.ch02.s1")
    heads = [s.heading for s in b.sections]
    assert any(h.startswith("Suspected or believed, NOT established") for h in heads)
    est = next(s.body for s in b.sections if s.heading.startswith("Story state"))
    assert "Jonas suspects Anna" not in est
    from bookforge.qc.continuity import build_questions
    qs, _ = build_questions(book, next(s for s in store.load_scenes(book) if s.id == "b1.ch02.s1"), store.load_scenes(book))
    assert any("Not established" in q.text and "Jonas suspects Anna" in q.text for q in qs)


def _ctx(book, llm):
    return StepContext(project=book, layer="scenes", llm=llm)


def test_a_critical_review_rewrites_the_beats_once_and_a_warning_stays_a_finding(book):
    scenes = store.load_scenes(book)
    chapters = store.load_chapters(book)
    ch = next(c for c in chapters if c.id == "b1.ch02")
    mine = [s for s in scenes if s.chapter == ch.id]
    mine[0].beats = ["Anna finds something unusual in the ledger.", "She decides what to do."]
    review = json.dumps({"scenes": [{"id": mine[0].id, "verdict": "critical", "issue": "the discovery is not named", "fix": "name the entry she finds"},
                                    *[{"id": s.id, "verdict": "warning", "issue": "thin for its length", "fix": ""} for s in mine[1:]]]})
    fixed = json.dumps({"purpose": mine[0].purpose, "situation": "", "beats": ["Anna finds her own name written in the ledger on the third page, in her mother's hand.", "She decides to hide it from Jonas."], "learns": ""})
    llm = RuleLLM([("Review the planned scenes of ONE chapter", review), ("The beats of one planned scene leave the writer", fixed)])
    findings, notes = beat_review.review_chapters(_ctx(book, llm), [ch], mine, store.load_tracks(book), lambda s: (300, 600))
    assert "her own name written in the ledger" in mine[0].beats[0] and len(notes) == 1
    assert [f.code for f in findings] == ["beat_review"] * len(mine[1:]) and all(f.severity == "soft" for f in findings)


def test_a_rewrite_that_stays_vague_is_thrown_away_and_a_failing_model_changes_nothing(book):
    scenes = store.load_scenes(book)
    ch = store.load_chapters(book)[1]
    mine = [s for s in scenes if s.chapter == ch.id]
    before = list(mine[0].beats)
    review = json.dumps({"scenes": [{"id": s.id, "verdict": "critical" if s is mine[0] else "ok", "issue": "vague", "fix": ""} for s in mine]})
    still_vague = json.dumps({"purpose": "p", "situation": "", "beats": ["She notices something unusual here today.", "She goes on."], "learns": ""})
    llm = RuleLLM([("Review the planned scenes of ONE chapter", review), ("The beats of one planned scene leave the writer", still_vague)])
    findings, notes = beat_review.review_chapters(_ctx(book, llm), [ch], mine, [], lambda s: (300, 600))
    assert mine[0].beats == before and notes == [] and [f.code for f in findings] == ["beat_review"]
    broken = RuleLLM([("Review the planned scenes of ONE chapter", "not json")])
    assert beat_review.review_chapters(_ctx(book, broken), [ch], mine, [], lambda s: (300, 600)) == ([], [])


def test_the_gate_is_off_with_the_switch(book):
    cfg = book.config.model_copy(deep=True)
    cfg.qc.beat_review = False
    off = Project(root=book.root, book=book.book, config=cfg, state=book.state) if hasattr(book, "state") else None
    if off is not None:
        assert beat_review.review_chapters(_ctx(off, RuleLLM([])), [], [], [], lambda s: (1, 2)) == ([], [])
