"""One topic, one decision: near-duplicate needs merge, scopes widen, disagreements are one item, the policy settles the minor ones."""

import json

from conftest import RuleLLM
from bookforge import answers, ops
from bookforge.layers.runner import StepContext
from bookforge.research import consolidate, topics
from bookforge.research.notes import approved_decisions, stores_for, waiting_decisions
from bookforge.research.search import FakeWebClient
from bookforge.research.step import run_research


def add(project, question, rule="", status="proposed", stance="extrapolate", applies_to=None, decided_by="", query=""):
    return stores_for(project)["book"].add_need(layer="chapters", question=question, stance=stance, rule=rule, query=query, status=status,
                                               decided_by=decided_by, applies_to=applies_to or [])


def test_near_duplicate_wordings_share_a_topic():
    a = topics.topic_stems("How does rapid-hardening polymer concrete cure in a vacuum?", "polymer concrete cure vacuum")
    b = topics.topic_stems("How long does the polymer concrete take to harden?", "polymer concrete hardening time")
    c = topics.topic_stems("How do plasma cutters behave in microgravity?", "plasma cutter microgravity")
    assert topics.same_topic(a, b) and not topics.same_topic(a, c)


def test_widen_scope_goes_whole_book_at_two_chapters():
    assert topics.widen_scope(["b2.ch01"], ["b2.ch01.s2"]) == ["b2.ch01", "b2.ch01.s2"]
    assert topics.widen_scope(["b2.ch01"], ["b2.ch05"]) == []
    assert topics.widen_scope([], ["b2.ch05"]) == []


def invent_question(question, rule):
    return json.dumps({"questions": [{"question": question, "stance": "invent", "query": "", "setting": "any", "reason": "r", "rule": rule, "sensitive": False}]})


def test_a_question_on_a_known_topic_adds_the_chapter_instead_of_a_new_need(project):
    first = add(project, "How does the polymer sealant cure?", "It cures in about fifteen minutes.", applies_to=["b2.ch01"], query="polymer sealant cure")
    llm = RuleLLM([("Decide what the author needs", invent_question("How long until the polymer sealant has cured?", "It sets in a quarter hour."))])
    run_research(StepContext(project=project, layer="chapters", llm=llm, web=FakeWebClient()), "book", "f", "doc", applies_to=["b2.ch05"])
    needs = stores_for(project)["book"].live_needs()
    assert len(needs) == 1 and needs[0].id == first.id and needs[0].applies_to == []  # two chapters: the whole book


def test_the_generator_prompt_lists_what_exists(project):
    add(project, "How does the polymer sealant cure?", "It cures in about fifteen minutes.")
    llm = RuleLLM([("Decide what the author needs", json.dumps({"questions": []}))])
    run_research(StepContext(project=project, layer="chapters", llm=llm, web=FakeWebClient()), "book", "f", "doc")
    assert "Already decided or waiting" in llm.calls[0]["messages"][-1]["content"] and "polymer sealant cure" in llm.calls[0]["messages"][-1]["content"]


def test_disagreeing_numbers_are_one_item_and_neither_is_canon(project):
    a = add(project, "How does the polymer sealant cure?", "It cures within 15 minutes.", status="approved", decided_by="author", query="polymer sealant cure")
    b = add(project, "How long does the polymer sealant take to set?", "It is fully cured only after 24 hours.", status="approved", decided_by="author", query="polymer sealant set")
    items = consolidate.contradiction_items(project)
    assert len(items) == 1 and [o["id"] for o in items[0]["options"]] == ["merge", "a", "b"] and items[0]["options"][0]["recommended"]
    assert approved_decisions(project) == []
    consolidate.resolve_contradiction(StepContext(project=project, layer="chapters", llm=None), a.id, b.id, "a")
    assert [n.id for n in approved_decisions(project)] == [a.id] and not consolidate.contradiction_items(project)


def test_quantities_extract_words_and_numbers():
    assert topics.disagree("cures within seconds", "cures within hours")
    assert not topics.disagree("cures in 10 minutes", "cures in 15 minutes")
    assert not topics.disagree("it is grey", "it is loud")


def merged_reply(question="How does the polymer sealant behave?", rule="It cures in about fifteen minutes and reaches full strength in a day."):
    return json.dumps({"question": question, "rule": rule})


def test_consolidation_merges_keeps_members_and_can_be_undone(project):
    ids = [add(project, f"How does the polymer sealant {w}?", f"Rule {w}.", status="approved", decided_by="author", applies_to=[f"b2.ch0{i}"], query="polymer sealant").id
           for i, w in enumerate(["cure", "set", "harden"], 1)]
    other = add(project, "How does a plasma cutter work in vacuum?", "Self-contained gas.", query="plasma cutter vacuum").id
    llm = RuleLLM([("ONE topic", merged_reply())])
    out = ops.consolidate_needs(project, llm, apply=True)
    store = stores_for(project)["book"]
    live = store.live_needs()
    assert out["before"] == 4 and out["after"] == 2 and {n.id for n in live} >= {other}
    merged = next(n for n in live if n.id != other)
    assert merged.merged_from == ids and merged.applies_to == [] and merged.status == "approved" and merged.decided_by == "tool"
    assert all(n.merged_into == merged.id for n in store.needs() if n.id in ids)  # nothing deleted
    assert ops.consolidate_needs(project, llm, apply=False)["groups"] == []  # idempotent
    assert ops.undo_consolidation(project, merged.id) == ids
    assert {n.id for n in store.live_needs()} == set(ids) | {other}


def test_a_failing_merge_call_leaves_the_members_alone(project):
    add(project, "How does the polymer sealant cure?", "A.", query="polymer sealant")
    add(project, "How does the polymer sealant harden?", "B.", query="polymer sealant")
    out = ops.consolidate_needs(project, RuleLLM([("ONE topic", "not json")]), apply=True)
    assert out["merged"] == [] and len(stores_for(project)["book"].live_needs()) == 2


def test_policy_settles_minor_needs_in_assist_mode_and_leaves_major_ones(project):
    answers.set_policy(project, "invent")
    minor = add(project, "How does the airlock cycle?", "It cycles in a minute.")
    major = add(project, "Who betrays the crew?", "Mara betrays the crew in 2041.")
    assert consolidate.settle_minor(project) == []  # shadow mode: nothing
    answers.set_mode(project, "assist")
    assert consolidate.settle_minor(project) == [minor.id]
    assert [n.id for n in waiting_decisions(project)] == [major.id]
