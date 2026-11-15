"""Stage 3: the tool answers a fact about the world by the book's policy; a story decision stays yours."""

import json
from types import SimpleNamespace

from bookforge import answers, resolve
from bookforge.research.hits import Hit


def item(kind="question", type_="unestablished_object", title="The plasma cutter is used but never explained", why="no one says how it works"):
    return {"id": "question:q1", "kind": kind, "type": type_, "title": title, "why": why, "quotes": [], "options": [], "status": "open"}


def asker(classify=None, invent=None):
    def ask(template, **slots):
        if template == "gap_classify":
            return classify or {}
        if template == "world_fact_invent":
            slots_seen.append(slots)
            return invent or {}
        return {}
    slots_seen = ask.slots = []
    return ask


def research_returning(facts, reason=""):
    calls = []

    def fn(ctx, web, q, document, seen):
        calls.append(q)
        return SimpleNamespace(facts=facts, reason=reason)
    fn.calls = calls
    return fn


HIT = Hit("https://history.example/parish", "Parish records")
FACT = {"claim": "Parish clerks kept death records by hand in the 1880s.", "quote": "the clerk entered each death by hand in the register"}


def test_the_policy_is_read_from_the_realism_statement_and_yours_wins(project):
    assert answers.derive_policy("A historical novel, accurate to the period.")[0] == "research"
    assert answers.derive_policy("Hard science fiction with plausible physics.")[0] == "extrapolate"
    assert answers.derive_policy("Space opera in invented worlds.")[0] == "invent"
    assert answers.policy_for(project)["world_facts"] == "extrapolate" and "realism" in answers.policy_for(project)["source"]
    answers.set_policy(project, "research")
    assert answers.policy_for(project) == {"world_facts": "research", "invention": "minor", "source": "you"}
    answers.set_policy(project, "")
    assert answers.policy_for(project)["source"] != "you"


def test_story_decisions_and_consistency_problems_get_no_answer_from_the_tool():
    ask = asker(classify={"kind": "story_decision", "fact": ""})
    assert resolve.classify_gap(item(type_="motive_gap"), "", ask)["kind"] == "story_decision"
    for t in ("contradiction", "condition_order", "cast_conflict", "unknown_name"):
        assert resolve.classify_gap(item(type_=t), "", ask)["kind"] == "consistency"  # decided without asking a model
    assert resolve.classify_gap(item(type_="thin"), "", ask)["kind"] == "story_decision"
    assert resolve.classify_gap(item(), "", None)["kind"] == "story_decision"  # no model: nothing is guessed
    assert resolve.classify_gap(item(), "", asker(classify={"kind": "world_fact", "fact": ""}))["kind"] == "story_decision"  # a world fact must name the fact


def test_a_historical_book_looks_it_up_and_keeps_the_exact_source_words(project):
    answers.set_policy(project, "research")
    fn = research_returning([(HIT, FACT)])
    p = resolve.propose_world_fact(project, "How did parish clerks record deaths in the 1880s?", "A historical novel", answers.policy_for(project), asker(), object(), fn)
    assert p.outcome == "world_fact" and p.label == "from source" and p.answer.startswith("From sources: Parish clerks kept death records")
    assert p.sources == [{"url": "https://history.example/parish", "quote": "the clerk entered each death by hand in the register"}] and not p.applied
    assert fn.calls[0].context == "A historical novel" and fn.calls[0].sensitive


def test_when_the_sources_are_silent_a_minor_detail_is_invented_and_labelled_a_major_one_is_yours(project):
    answers.set_policy(project, "research")
    fn = research_returning([], reason="no supported facts in the 3 page(s) read")
    minor = asker(invent={"rule": "The registers were kept in a locked press in the vestry.", "basis": "", "changes_what_happens": False, "reason": "a routine"})
    p = resolve.propose_world_fact(project, "Where were the registers kept?", "A historical novel", answers.policy_for(project), minor, object(), fn)
    assert p.outcome == "world_fact" and p.label == "invented: no source found" and p.size == "minor" and "locked press" in p.answer and p.sources == []
    assert "look it up first" in minor.slots[0]["policy"]
    major = asker(invent={"rule": "The vicar was murdered in 1886 to hide the forged entries.", "basis": "", "changes_what_happens": False, "reason": "r"})
    q = resolve.propose_world_fact(project, "Who forged the registers?", "A historical novel", answers.policy_for(project), major, object(), fn)
    assert q.outcome == "options" and q.size == "major" and q.answer == "" and "stays yours" in q.rationale  # a death and a date: never decided by the tool
    flagged = asker(invent={"rule": "The clerk is the culprit.", "basis": "", "changes_what_happens": True, "reason": "r"})
    assert resolve.propose_world_fact(project, "Who did it?", "", answers.policy_for(project), flagged, object(), fn).outcome == "options"  # the model says it changes what happens


def test_a_hard_science_book_grounds_and_extends_and_a_soft_one_invents(project):
    answers.set_policy(project, "extrapolate")
    ask = asker(invent={"rule": "Radiation-damaged memory is treated with shielded sleep cycles.", "basis": "chronic radiation exposure is known to impair memory", "changes_what_happens": False, "reason": "extends known effects"})
    p = resolve.propose_world_fact(project, "What does radiation do to Mara's memory?", "Hard science fiction", answers.policy_for(project), ask, None, None)
    assert p.label == "extrapolated" and p.size == "minor" and p.rationale.startswith("Basis: chronic radiation")
    answers.set_policy(project, "invent")
    soft = asker(invent={"rule": "Scrip is minted from ore quotas.", "basis": "", "changes_what_happens": False, "reason": "an institution"})
    q = resolve.propose_world_fact(project, "How is scrip issued?", "Space opera", answers.policy_for(project), soft, None, None)
    assert q.label == "invented" and "Scrip is minted" in q.answer


def test_no_model_and_no_source_means_the_question_stays_with_you(project):
    answers.set_policy(project, "research")
    p = resolve.propose_world_fact(project, "x", "", answers.policy_for(project), None, object(), research_returning([], reason="no page could be read"))
    assert p.outcome == "options" and p.label == "no source found" and "no page could be read" in p.rationale


def test_the_size_check_treats_dates_deaths_and_turning_points_as_major_and_is_conservative():
    assert resolve.size_of("The registers were kept in a locked press.", False) == "minor"
    for text in ("The mine was founded in 1887.", "The foreman dies in the collapse.", "The clerk betrays the vicar.", "He decides to leave the colony."):
        assert resolve.size_of(text, False) == "major"
    assert resolve.size_of("A locked press.", True) == "major"
