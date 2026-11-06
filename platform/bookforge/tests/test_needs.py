"""Knowledge needs: a stance for each thing the story must know or decide (ground, extrapolate, bend, invent)."""

import json

import pytest
from typer.testing import CliRunner

from bookforge import cli, ops, report as morning_report
from bookforge.errors import BookforgeError
from bookforge.research.notes import stores_for
from bookforge.research.step import generate_questions, run_research
from bookforge.layers.runner import StepContext

from conftest import RuleLLM
from test_research_step import CHECK_ALL, PAGE_A, URL_A, facts, run, web


def need_item(question="How does the laser rifle behave?", stance="invent", query="", rule="", reason="space opera", sensitive=False):
    return {"question": question, "stance": stance, "query": query, "setting": "a far future", "reason": reason, "rule": rule, "sensitive": sensitive}


def asking(*items):
    return ("Decide what the author needs", json.dumps({"questions": list(items)}))


def lookup_rules(*items):
    return [asking(*items), (f"Source page: {URL_A}", facts(("Clavicle fractures usually heal in about six weeks.", "Most clavicle fractures heal in six weeks"))), CHECK_ALL]


GROUND = need_item("How long does a collarbone take to heal?", "ground", "clavicle healing", reason="medicine must be right", sensitive=True)
INVENT = need_item(rule="The rifle is silent and has no recoil.")
EXTRAPOLATE = need_item("What would a laser weapon need to work?", "extrapolate", "clavicle healing", rule="A backpack battery gives ten shots.")


def test_a_ground_need_is_looked_up_and_needs_no_approval(project):
    run(project, RuleLLM(lookup_rules(GROUND)), web())
    [n] = stores_for(project)["series"].needs()
    assert (n.id, n.stance, n.status, n.decided_by, n.fact_ids) == ("s-n001", "ground", "approved", "auto", ["s-0001"])
    assert n.reason == "medicine must be right" and n.sensitive


def test_an_invented_rule_is_not_searched_and_waits_for_approval(project):
    llm = RuleLLM([asking(INVENT)])  # a search or page read would hit a rule-less prompt and fail
    w = web()
    outcome = run(project, llm, w)
    assert outcome.asked == 0 and outcome.decisions == 1 and w.calls == []
    [n] = stores_for(project)["series"].needs()
    assert (n.stance, n.status, n.rule, n.fact_ids) == ("invent", "proposed", "The rifle is silent and has no recoil.", [])
    assert "1 decision(s) waiting for you" in outcome.summary()


def test_an_extrapolation_is_researched_and_its_assumption_waits(project):
    outcome = run(project, RuleLLM(lookup_rules(EXTRAPOLATE)), web())
    [n] = stores_for(project)["series"].needs()
    assert (n.stance, n.status, n.fact_ids) == ("extrapolate", "proposed", ["s-0001"])
    assert outcome.answered == 1 and outcome.decisions == 1


def test_a_missing_or_unknown_stance_is_a_ground_lookup_and_unusable_items_are_dropped(project):
    items = [
        {"question": "No stance given?", "query": "clavicle healing"},
        need_item("Odd stance?", "wibble", "sling history"),
        need_item("Lookup with no query?", "ground", ""),
        need_item("Invention with no rule?", "invent", "", rule=""),
        {"question": "", "query": "q"},
    ]
    llm = RuleLLM([asking(*items)])
    got = generate_questions(StepContext(project=project, layer="series_north_star", llm=llm, web=None), set(), "focus", "doc", 10)
    assert [(q.question, q.stance) for q in got] == [("No stance given?", "ground"), ("Odd stance?", "ground")]


def test_the_prompt_carries_the_realism_setting(project):
    (project.root / "north-star.md").write_text("# S\n\n## Realism\nHard SF: physics must hold.\n", encoding="utf-8")
    llm = RuleLLM([asking()])
    generate_questions(StepContext(project=project, layer="series_north_star", llm=llm, web=None), set(), "focus", "doc", 5)
    assert "Hard SF: physics must hold." in llm.calls[0]["messages"][-1]["content"]


def test_a_recorded_need_is_not_proposed_again(project):
    run(project, RuleLLM([asking(INVENT)]), web())
    seen = []

    def spy(messages):
        seen.append(messages[-1]["content"])
        return json.dumps({"questions": [INVENT]})

    outcome = run(project, RuleLLM([("Decide what the author needs", spy)]), web())
    assert outcome.decisions == 0 and len(stores_for(project)["series"].needs()) == 1


def test_needs_md_lists_stance_status_and_outcome(project):
    run(project, RuleLLM(lookup_rules(GROUND, INVENT)), web())
    text = (project.root / "research" / "needs.md").read_text(encoding="utf-8")
    assert "## s-n001 [ground, approved]" in text and "[s-0001] Clavicle fractures usually heal" in text
    assert "## s-n002 [invent, proposed]" in text and "rule: The rifle is silent" in text


def test_approving_rejecting_and_editing(project):
    run(project, RuleLLM([asking(INVENT)]), web())
    edited = ops.decide_need(project, "s-n001", rule="The rifle hums and has no recoil.")
    assert (edited.status, edited.rule) == ("proposed", "The rifle hums and has no recoil.")  # an edit is not an approval
    approved = ops.decide_need(project, "s-n001", approve=True)
    assert (approved.status, approved.decided_by) == ("approved", "author")
    assert stores_for(project)["series"].needs()[0].status == "approved"
    assert ops.decide_need(project, "s-n001", approve=False).status == "rejected"
    changed = ops.decide_need(project, "s-n001", stance="bend", rule="Real rifles recoil; here they do not, for the chase scene.")
    assert (changed.stance, changed.status) == ("bend", "proposed")
    assert "rule: " not in (project.root / "research" / "needs.md").read_text(encoding="utf-8")  # a bend shows as a deviation


def test_bad_decisions_are_refused(project):
    run(project, RuleLLM([asking(INVENT)]), web())
    with pytest.raises(BookforgeError, match="no need"):
        ops.decide_need(project, "s-n099", approve=True)
    with pytest.raises(BookforgeError, match="stance must be"):
        ops.decide_need(project, "s-n001", stance="wibble")
    with pytest.raises(BookforgeError, match="needs the rule"):
        ops.decide_need(project, "s-n001", rule="   ")


def test_the_needs_command_lists_and_decides(project, monkeypatch):
    run(project, RuleLLM(lookup_rules(GROUND, INVENT)), web())
    runner = CliRunner()
    out = runner.invoke(cli.app, ["needs", str(project.root)])
    assert out.exit_code == 0 and "s-n002 [invent, proposed]" in out.output and "s-n001" not in out.output  # lookups need no decision
    assert "s-n001 [ground, approved]" in runner.invoke(cli.app, ["needs", str(project.root), "--all"]).output
    done = runner.invoke(cli.app, ["needs", str(project.root), "--approve", "s-n002"])
    assert done.exit_code == 0 and "s-n002: approved (invent)" in done.output
    bad = runner.invoke(cli.app, ["needs", str(project.root), "--edit", "s-n002"])
    assert bad.exit_code == 1 and "--stance and/or --rule" in bad.output


def test_a_proposed_decision_is_in_the_morning_report(project):
    run(project, RuleLLM([asking(INVENT)]), web())
    text = morning_report.build_report(project)
    assert "s-n001" in text and "needs --approve s-n001" in text
