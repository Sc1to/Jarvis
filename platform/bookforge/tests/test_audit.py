"""The synopsis audit: deterministic checks, verbatim quotes, stopping at the ledger checkpoint, answers as notes."""

import json

from conftest import skip_ledger  # noqa: F401
from test_ledger_layer import GOOD, SYN, extraction_calls, prepared, run_ledger

from bookforge.bible import store
from bookforge.bible.models import Constants, Entity
from bookforge.layers import audit
from bookforge.layers.ledger import answer_question
from bookforge.validators import audit as checks

A = "Mara signs the deal but secretly keeps a copy of the drive"
B = "hand it over and the debt is voided"


def finding(kind="contradiction", quotes=(A, B), why="the drive is handed over and kept", fixes=("She hands over a decoy", "She keeps the copy")):
    return {"type": kind, "quotes": list(quotes), "why": why, "fixes": list(fixes)}


def reply(*findings):
    return json.dumps({"findings": list(findings)})


def cast(*pairs):
    return Constants(entities=[Entity(id=i, kind="character", name=n, facts=["x"]) for i, n in pairs])


def test_causal_markers_unknown_names_and_absent_roles_are_found_without_a_model():
    syn = "Ava finds a drive. They let Ava go, but only on the condition that she signs. Foreman Halloway seals the sector because Ava ran."
    assert [c["marker"] for c in checks.causal_sentences(syn)] == ["but only", "because"]
    constants = cast(("ava", "Ava Reil"), ("silas-thorne", "Silas Thorne"))
    assert [n["name"] for n in checks.unknown_names(syn, constants)] == ["halloway"]
    assert [a["id"] for a in checks.cast_roles_absent(syn, constants)] == ["silas-thorne"]
    assert checks.unknown_names(syn, Constants()) == []  # no cast yet: a new book's cast is made later


def test_a_finding_needs_exact_quotes_and_a_known_type():
    data = {"findings": [finding(), finding(quotes=("words that are not in the synopsis",)), finding(kind="vibes"), finding(quotes=())]}
    kept, dropped = audit.parse_findings(data, SYN)
    assert len(kept) == 1 and dropped == 3 and kept[0]["quotes"] == [A, B]


def test_a_contradiction_stops_the_ledger_stage_at_its_checkpoint(project_with_ledger):
    p = prepared(project_with_ledger)
    summary, llm = run_ledger(p, [GOOD], audit=reply(finding()))
    assert summary.stopped == "checkpoint" and "synopsis audit" in summary.notes["ledger"] and len(extraction_calls(llm)) == 0
    led = store.load_ledger(p)
    assert led.events == [] and [q.type for q in led.questions] == ["contradiction"] and led.questions[0].quotes == [A, B]
    assert led.questions[0].options == ["She hands over a decoy", "She keeps the copy"] and p.state.checkpoints["ledger"].status == "waiting"


def test_the_answer_becomes_a_note_the_extraction_obeys_and_the_question_is_not_asked_again(project_with_ledger):
    p = prepared(project_with_ledger)
    p.config.ledger.min_chapters = 4
    run_ledger(p, [GOOD], audit=reply(finding()))
    answer_question(p, "q1", "She hands over a decoy and keeps the real copy")
    summary, llm = run_ledger(p, [GOOD], audit=reply(finding()))  # the audit raises the same words again
    assert summary.ran == ["ledger"] and len(extraction_calls(llm)) == 1
    prompt = extraction_calls(llm)[0]["messages"][-1]["content"]
    assert "She hands over a decoy and keeps the real copy" in prompt and A in prompt  # the note travels with the quote
    led = store.load_ledger(p)
    assert len(led.events) == 10 and [q.status for q in led.questions] == ["answered"] and led.questions[0].applied
    assert len([q for q in led.questions if q.type == "contradiction"]) == 1  # never asked twice
    assert led.last_run["kind"] == "extract" and led.last_run["applied"] == ["q1"] and led.last_run["events"] == 10


def test_approving_the_checkpoint_goes_on_as_it_is(project_with_ledger):
    p = prepared(project_with_ledger)
    p.config.ledger.min_chapters = 4
    run_ledger(p, [GOOD], audit=reply(finding()))
    p.state.approve_checkpoint("ledger")
    p.save_state()
    summary, _ = run_ledger(p, [GOOD], audit=reply(finding()))
    assert summary.ran == ["ledger"] and len(store.load_ledger(p).events) == 10
    assert store.load_ledger(p).questions[0].status == "dismissed"


import pytest


@pytest.mark.parametrize("kind", audit.BLOCKING_TYPES)
def test_every_kind_of_audit_finding_stops_the_stage(project_with_ledger, kind):
    p = prepared(project_with_ledger)
    store.save_constants(p, Constants(entities=[Entity(id="mara", kind="character", name="Mara Voss", facts=["a salvage pilot"]),
                                                Entity(id="rhee", kind="character", name="Rhee Okafor", facts=["the harbor board's clerk"])]))
    one = finding(kind=kind, quotes=("Corso learns of the drive and offers Mara a deal",), why="Corso offers Mara a deal and nothing makes her listen")
    one["cast_fact"] = "a salvage pilot"  # only a cast conflict needs one
    summary, llm = run_ledger(p, [GOOD], audit=reply(one))
    led = store.load_ledger(p)
    assert led.events == [] and [(q.type, q.status) for q in led.questions] == [(kind, "open")] and len(extraction_calls(llm)) == 0
    assert "synopsis audit" in summary.notes["ledger"] and p.state.checkpoints["ledger"].status == "waiting"


def test_a_name_that_is_not_in_the_cast_and_a_condition_that_does_not_hold_block_like_a_contradiction():
    from bookforge.bible.models import AuthorQuestion
    q = lambda t: AuthorQuestion(id="q1", question="x", why="y", type=t)  # noqa: E731
    assert all(audit.is_blocking(q(t)) for t in ("unknown_name", "condition_order", "motive_gap", "contradiction"))
    assert not any(audit.is_blocking(q(t)) for t in ("thin", "unpaid_setup", ""))  # these stop the checkpoint, as before, but are not audit findings


def test_a_coherent_synopsis_raises_nothing(project_with_ledger):
    p = prepared(project_with_ledger)
    p.config.ledger.min_chapters = 4
    run_ledger(p, [GOOD], audit=reply())
    assert store.load_ledger(p).questions == [] and store.load_ledger(p).audit["findings"] == {}


def ev(i, text, kind="event", **kw):
    return dict(id=i, text=text, excerpt=text, kind=kind, once_only=True, after=[], weight=2, source="synopsis", pays_off="", **kw)


def test_a_setup_a_later_event_resolves_by_meaning_is_linked_not_asked():
    from bookforge.validators import ledger as L
    events = [ev("e1", "Mara hides a copy of the smuggling drive inside the ferry's hull", "setup"), ev("e2", "Corso offers a deal"),
              ev("e3", "Mara gives the hidden copy of the drive to the harbor inspector")]
    notes, open_ = L.link_payoffs_by_meaning(events)
    assert open_ == {} and events[2]["pays_off"] == "e1" and events[2]["kind"] == "payoff" and "resolves the setup e1 by meaning" in notes[0]


def test_an_unresolved_setup_is_asked_with_its_own_words_and_candidates():
    from bookforge.validators import ledger as L
    events = [ev("e1", "A stranger leaves a sealed envelope on the pier", "setup"), ev("e2", "Corso offers a deal"), ev("e3", "Mara sails free")]
    notes, open_ = L.link_payoffs_by_meaning(events)
    assert notes == [] and list(open_) == ["e1"]
    q = L.unpaid_setup_question(events[0], open_["e1"])
    assert q["type"] == "unpaid_setup" and q["quotes"] == ["A stranger leaves a sealed envelope on the pier"] and "sealed envelope" in q["question"]
