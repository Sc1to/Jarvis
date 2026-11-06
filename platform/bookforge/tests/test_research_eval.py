"""research-eval: judge the whole research stage for a story."""

import json

from typer.testing import CliRunner

from bookforge import cli
from bookforge.layers.runner import StepContext
from bookforge.research import evaluate
from bookforge.research.notes import stores_for
from conftest import RuleLLM
from test_needs import GROUND, INVENT, asking, need_item
from test_research_step import CHECK_ALL, URL_A, URL_B, facts, run, web

PAGE_FACT = ("Clavicle fractures usually heal in about six weeks.", "Most clavicle fractures heal in six weeks")
AUDIT = "Audit the facts below"
CLEAN = (AUDIT, json.dumps({"unsupported": []}))
UNANSWERABLE = need_item("What colour was the harbour master's hat?", "ground", "sling history", reason="a detail")  # page B has nothing
SLING = need_item("What would a laser weapon need to work?", "extrapolate", "sling history", rule="A backpack battery gives ten shots.")


def ctx(project, llm, w):
    return StepContext(project=project, layer="synopsis", llm=llm, web=w)


def eval_rules(*items, audit=CLEAN, reader=None, reader_b=None):
    return [asking(*items), (f"Source page: {URL_A}", reader or facts(PAGE_FACT)),
            (f"Source page: {URL_B}", reader_b or facts()), CHECK_ALL, audit]


def evaluate_items(project, items, **kw):
    llm = RuleLLM(eval_rules(*items, **kw))
    w = web()
    c = ctx(project, llm, w)
    return evaluate.evaluate(c, w, evaluate.propose(c, "A story.", 8), "A story.")


def test_every_need_is_run_and_invented_ones_are_not_searched(project):
    rows = evaluate_items(project, [GROUND, INVENT, SLING], reader_b=facts(("Slings were in wide use by the 1800s.", "The sling was widely used from the 1800s")))
    assert [r.question.stance for r in rows] == ["ground", "invent", "extrapolate"]
    assert rows[1].attempt is None and rows[0].answered and rows[2].answered
    s = evaluate.summarize(rows)
    assert (s["needs"], s["lookups"], s["answered"], s["decisions"], s["unsupported"]) == (3, 2, 2, 2, 0)
    assert s["share"] == 1.0 and evaluate.bar_met(rows)


def test_a_claim_the_audit_finds_unsupported_is_reported(project):
    bad = (AUDIT, json.dumps({"unsupported": [{"n": 1, "why": "claim says clerk, quote says Comptroller"}]}))
    rows = evaluate_items(project, [GROUND], audit=bad)
    assert [(u["why"]) for u in rows[0].unsupported] == ["claim says clerk, quote says Comptroller"]
    text = "\n".join(evaluate.describe(rows, "searxng", "Historical", "premise.md"))
    assert "1 fact(s), 1 bad" in text and "! UNSUPPORTED" in text and "claims their quote does not support: 1" in text


def test_audit_numbers_that_do_not_exist_are_ignored_and_a_failing_audit_is_noted(project):
    weird = (AUDIT, json.dumps({"unsupported": [{"n": 9, "why": "x"}, {"n": True, "why": "y"}, "junk"]}))
    assert evaluate_items(project, [GROUND], audit=weird)[0].unsupported == []

    def offline(messages):
        from bookforge.errors import BookforgeError
        raise BookforgeError("model offline")

    rows = evaluate_items(project, [GROUND], audit=(AUDIT, offline))
    assert rows[0].answered and rows[0].audit_error == "model offline"
    assert "(audit failed: model offline)" in "\n".join(evaluate.describe(rows, "s", "", "d"))


def test_the_bar_is_half_of_the_lookups_answered(project):
    # one answered (page A), one with nothing to find: exactly half meets the bar, none misses it
    half = evaluate_items(project, [GROUND, UNANSWERABLE])
    assert evaluate.summarize(half)["share"] == 0.5 and evaluate.bar_met(half)
    none = evaluate_items(project, [UNANSWERABLE])
    assert evaluate.summarize(none)["share"] == 0.0 and not evaluate.bar_met(none)
    assert "MISSED" in "\n".join(evaluate.describe(none, "s", "", "d")) and "MET" in "\n".join(evaluate.describe(half, "s", "", "d"))


def test_only_inventions_means_nothing_to_miss(project):
    rows = evaluate_items(project, [INVENT])
    assert evaluate.summarize(rows)["share"] is None and evaluate.bar_met(rows)
    assert "no lookups proposed" in "\n".join(evaluate.describe(rows, "s", "", "d"))


def test_no_needs_is_said_plainly(project):
    assert evaluate.describe([], "s", "", "d")[-1] == "no needs were proposed"


def test_recorded_needs_are_taken_from_the_stores(project):
    run(project, RuleLLM([asking(GROUND, INVENT), (f"Source page: {URL_A}", facts(PAGE_FACT)), CHECK_ALL]), web())
    got = evaluate.recorded_questions(project)
    assert [(q.question, q.stance, q.query) for q in got] == [(GROUND["question"], "ground", "clavicle healing")]  # an invention has nothing to run


def test_the_command_prints_the_table_and_exits_by_the_bar(project, monkeypatch):
    (project.root / "config.yaml").write_text("research:\n  model_pick: false\n  check_support: false\n")
    llm = RuleLLM(eval_rules(GROUND, INVENT))
    monkeypatch.setattr(cli, "build_client", lambda p: llm)
    monkeypatch.setattr(cli, "build_web_client", lambda p: web())
    out = CliRunner().invoke(cli.app, ["research-eval", str(project.root)])
    assert out.exit_code == 0, out.output
    for needle in ("needs from: premise.md", "ground", "invent", "to decide", "lookups answered: 1/1 (100%)", "MET", "claims their quote does not support: 0"):
        assert needle in out.output, needle
    assert not (project.root / "research" / "sources.jsonl").exists()  # it stores nothing
    monkeypatch.setattr(cli, "build_client", lambda p: RuleLLM(eval_rules(UNANSWERABLE)))
    miss = CliRunner().invoke(cli.app, ["research-eval", str(project.root)])
    assert miss.exit_code == 1 and "MISSED" in miss.output


def test_the_command_can_read_another_document_and_refuses_a_missing_one(project, monkeypatch):
    (project.root / "research-notes.md").write_text("A synopsis.\n")
    seen = []

    def spy(messages):
        seen.append(messages[-1]["content"])
        return json.dumps({"questions": []})

    monkeypatch.setattr(cli, "build_client", lambda p: RuleLLM([("Decide what the author needs", spy)]))
    monkeypatch.setattr(cli, "build_web_client", lambda p: web())
    ok = CliRunner().invoke(cli.app, ["research-eval", str(project.root), "--document", "research-notes.md"])
    assert ok.exit_code == 0 and "needs from: research-notes.md" in ok.output and "A synopsis." in seen[0]
    gone = CliRunner().invoke(cli.app, ["research-eval", str(project.root), "--document", "nope.md"])
    assert gone.exit_code == 1 and "cannot read" in gone.output


def test_the_command_can_run_recorded_needs(project, monkeypatch):
    run(project, RuleLLM([asking(GROUND), (f"Source page: {URL_A}", facts(PAGE_FACT)), CHECK_ALL]), web())
    (project.root / "config.yaml").write_text("research:\n  model_pick: false\n  check_support: false\n")
    monkeypatch.setattr(cli, "build_client", lambda p: RuleLLM([(f"Source page: {URL_A}", facts(PAGE_FACT)), CHECK_ALL, CLEAN]))
    monkeypatch.setattr(cli, "build_web_client", lambda p: web())
    out = CliRunner().invoke(cli.app, ["research-eval", str(project.root), "--recorded"])
    assert out.exit_code == 0 and "needs from: recorded needs" in out.output and "lookups answered: 1/1" in out.output


def test_the_pipeline_audit_catches_are_reported_and_a_second_audit_is_not_run(project):
    project.config.research.check_support = True
    bad = ("Audit the facts below", json.dumps({"unsupported": [{"n": 1, "why": "claim says clerk, quote says Comptroller"}]}))
    rows = evaluate_items(project, [GROUND], audit=bad)
    assert [c["why"] for c in rows[0].caught][0].endswith("claim says clerk, quote says Comptroller")
    assert rows[0].unsupported == [] and not rows[0].answered
    text = "\n".join(evaluate.describe(rows, "s", "", "d"))
    assert "x dropped by the audit" in text and "0 kept, 1 caught and dropped" in text


def test_realism_given_on_the_command_line_reaches_the_proposal_and_the_output(project, monkeypatch):
    seen = []

    def spy(messages):
        seen.append(messages[-1]["content"])
        return json.dumps({"questions": []})

    monkeypatch.setattr(cli, "build_client", lambda p: RuleLLM([("Decide what the author needs", spy)]))
    monkeypatch.setattr(cli, "build_web_client", lambda p: web())
    out = CliRunner().invoke(cli.app, ["research-eval", str(project.root), "--realism", "Hard SF: physics must hold."])
    assert out.exit_code == 0 and "realism: Hard SF: physics must hold." in out.output
    assert "Hard SF: physics must hold." in seen[0]
