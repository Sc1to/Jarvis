"""Stage 4: what you invent in an answer becomes canon, held like a researched fact."""

import json

from conftest import RuleLLM
from test_prose_qc import book  # noqa: F401  (a fixture: a planned book with chapters and scenes)

from bookforge import canon, cast
from bookforge.bible import store
from bookforge.bible.models import Constants, Entity
from bookforge.research.notes import approved_decisions

ANSWER = "Eli copies the data onto a brass keycard called the Ledger Key, which Mara hides in her boot. Every airlock on Erebus-7 logs who passes through it."
QUESTION = 'Used before it is established: "Halloway attempts to destroy the drive containing the evidence"'


def reply(entities=None, rules=None):
    return json.dumps({"entities": entities if entities is not None else [{"name": "Ledger Key", "kind": "object", "facts": ["a brass keycard Eli copies the data onto", "Mara hides it in her boot"]}],
                       "rules": rules if rules is not None else ["Every airlock on Erebus-7 logs who passes through it."]})


def llm(text):
    return RuleLLM([("An author answered a question about their story", text)])


def test_what_holds_up_is_kept_and_what_does_not_is_dropped():
    found = canon.verify(json.loads(reply(
        entities=[{"name": "Ledger Key", "kind": "object", "facts": ["a brass keycard Eli copies the data onto", "it grants access to every vault on the moon"]},
                  {"name": "Captain Zhao", "kind": "character", "facts": ["a captain"]},  # a name the answer never wrote
                  {"name": "Mara", "kind": "character", "facts": ["Mara hides it in her boot"]},  # already in the cast
                  {"name": "Brass", "kind": "weapon", "facts": ["a brass keycard"]}],  # not a kind of thing
        rules=["Every airlock on Erebus-7 logs who passes through it.", "Airlocks open for no one."])), ANSWER, {"mara", "eli"})
    assert found == {"entities": [{"name": "Ledger Key", "kind": "object", "facts": ["a brass keycard Eli copies the data onto"]}],
                     "rules": ["Every airlock on Erebus-7 logs who passes through it."]}  # an invented fact and an invented rule are not the author's words


def test_an_invention_becomes_a_cast_entry_and_an_approved_canon_rule_that_the_continuity_check_holds_like_a_fact(book):
    entry = canon.intake(book, "question:q1", QUESTION, ANSWER, llm(reply()))
    assert entry["entities"] == ["ledger-key"] and len(entry["needs"]) == 1 and entry["answer"] == ANSWER and not entry["undone"]
    ent = next(e for e in store.load_constants(book).entities if e.id == "ledger-key")
    assert ent.kind == "object" and ent.facts == ["a brass keycard Eli copies the data onto", "Mara hides it in her boot"]
    [need] = approved_decisions(book)
    assert need.canon and need.status == "approved" and need.stance == "invent" and need.decided_by == "author" and "airlock" in need.rule
    from bookforge.qc.continuity import build_questions
    scene = store.load_scenes(book)[0]
    questions, _ = build_questions(book, scene, store.load_scenes(book))
    rule_q = next(q for q in questions if "airlock" in q.text)
    assert rule_q.severity == "block"  # your own invention is a fact to the check, not a warning


def test_the_name_then_resolves_in_the_audit_and_a_contradiction_with_the_cast_fact_is_a_hard_question(book):
    canon.intake(book, "question:q1", QUESTION, ANSWER, llm(reply()))
    from bookforge.validators import audit as checks
    syn = "Eli copies the data onto the Ledger Key. Mara hides the Ledger Key in her boot."
    assert "ledger" not in [n["name"] for n in checks.unknown_names(syn, store.load_constants(book))]  # a name you introduced is in the cast


def test_answering_again_replaces_what_the_first_answer_introduced(book):
    canon.intake(book, "question:q1", QUESTION, ANSWER, llm(reply()))
    second = "Eli copies the data onto a steel token called the Ash Token. Dockers use the Ash Token to open the lock-ups."
    entry = canon.intake(book, "question:q1", QUESTION, second, llm(reply(entities=[{"name": "Ash Token", "kind": "object", "facts": ["a steel token Eli copies the data onto"]}], rules=[])))
    ids = {e.id for e in store.load_constants(book).entities}
    assert "ash-token" in ids and "ledger-key" not in ids and approved_decisions(book) == []
    assert [e["id"] for e in canon.active(book)] == [entry["id"]] and len(canon.load(book)) == 2


def test_undo_removes_the_cast_entry_and_the_rule_but_keeps_what_the_book_already_uses(book):
    entry = canon.intake(book, "question:q1", QUESTION, ANSWER, llm(reply()))
    done = canon.undo(book, entry["id"])
    assert done["undone"] and done["kept"] == [] and "ledger-key" not in {e.id for e in store.load_constants(book).entities} and approved_decisions(book) == []
    again = canon.intake(book, "question:q2", QUESTION, ANSWER, llm(reply()))
    scenes = store.load_scenes(book)
    scenes[0].characters = list(scenes[0].characters) + ["ledger-key"]  # a scene now uses it
    store.save_scenes(book, scenes)
    kept = canon.undo(book, again["id"])
    assert kept["kept"] == ["ledger-key"] and "ledger-key" in {e.id for e in store.load_constants(book).entities}  # in use: the cast keeps it and says so


def test_nothing_is_recorded_for_a_choice_a_short_answer_a_failed_model_or_no_model(book):
    assert canon.intake(book, "question:q1", QUESTION, "Keep A", llm(reply())) is None
    assert canon.intake(book, "question:q1", QUESTION, ANSWER, llm(reply(entities=[], rules=[]))) is None
    assert canon.intake(book, "question:q1", QUESTION, ANSWER, llm("not json at all")) is None
    assert canon.intake(book, "question:q1", QUESTION, ANSWER, None) is None
    assert canon.intake(book, "question:q1", QUESTION, ANSWER, RuleLLM([])) is None  # the model call raises: the answer still stands
    assert canon.load(book) == []
