"""Stage 5: auto mode answers minor facts about the world; an outcome you keep overriding is switched off by itself."""

import json

from test_prose_qc import book  # noqa: F401

from bookforge import answers, inbox, report, resolve
from bookforge.bible import store
from bookforge.bible.models import AuthorQuestion, Ledger
from bookforge.research.notes import approved_decisions

FACT = "How does a plasma cutter work?"


def seed(project, *proposals):
    store.save_ledger(project, Ledger(events=[], questions=[AuthorQuestion(id="q1", question="The plasma cutter is used but never explained", why="w", type="unestablished_object"),
                                                           AuthorQuestion(id="q2", question="Why does Mara yield?", why="w", type="motive_gap")]))
    resolve.save(project, {f"question:q{i}": p for i, p in enumerate(proposals, 1)})


def proposal(outcome="world_fact", label="invented", size="minor", answer="It cuts by a confined arc of ionised gas.", quote=FACT, applied=False):
    return dict(outcome=outcome, answer=answer, rationale="r", label=label, target="", sources=[], size=size, confidence="medium", decided_by="tool", applied=applied, mode="shadow", quote=quote, need="")


def test_auto_mode_records_a_minor_rule_as_the_tools_decision_and_answers_the_question_with_it(book):
    seed(book, proposal())
    proposals = resolve.load(book)
    assert resolve.apply_world_facts(book, proposals, answers.load(book)) == 1
    [need] = approved_decisions(book)
    assert need.decided_by == "tool" and not need.canon and need.stance == "invent" and "ionised gas" in need.rule  # a decision of the tool's: it only warns
    q = store.load_ledger(book).questions[0]
    assert (q.status, q.decided_by, q.applied) == ("answered", "tool", False) and q.answer == proposals["question:q1"]["answer"]
    resolve.save(book, proposals)
    item = next(i for i in inbox.collect(book) if i["id"] == "question:q1")
    assert item["status"] == "resolved" and not item["blocking"] and item["proposal"]["applied"] and inbox.summary(book)["resolved"] == 1 and inbox.summary(book)["open"] == 1


def test_undo_rejects_the_rule_reopens_the_question_and_the_tool_leaves_it_alone(book):
    seed(book, proposal())
    proposals = resolve.load(book)
    resolve.apply_world_facts(book, proposals, answers.load(book))
    resolve.save(book, proposals)
    resolve.undo(book, "question:q1")
    assert approved_decisions(book) == []
    q = store.load_ledger(book).questions[0]
    assert (q.status, q.answer, q.decided_by) == ("open", "", "") and not resolve.load(book)["question:q1"]["applied"]
    again = resolve.load(book)
    assert resolve.apply_world_facts(book, again, answers.load(book)) == 0  # you took it back: the tool does not decide it again


def test_only_a_minor_rule_is_ever_applied_never_a_major_one_a_source_backed_answer_or_a_story_question(book):
    seed(book, proposal(size="major", outcome="options", label="proposal"), proposal(label="from source"))
    p = resolve.load(book)
    assert resolve.apply_world_facts(book, p, answers.load(book)) == 0 and approved_decisions(book) == []
    seed(book, proposal(label="no source found", outcome="options"))
    assert resolve.apply_world_facts(book, resolve.load(book), answers.load(book)) == 0
    seed(book, proposal())
    assert resolve.apply_world_facts(book, resolve.load(book), answers.load(book), {"world_fact"}) == 0  # switched off by demotion


def decisions(project, rows):
    path = resolve.path(project).with_name("decisions.jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(dict(item="x", outcome=o, label="l", mode="assist", verdict=v, at=at)) + "\n" for o, v, at in rows), encoding="utf-8")


def test_an_outcome_you_keep_overriding_is_switched_off_and_you_can_switch_it_back_on(book):
    rows = [("waive", v, f"2026-11-15T10:0{i}:00+00:00") for i, v in enumerate(["applied"] * 4 + ["undone", "undone", "undone", "applied", "undone", "applied"])]
    decisions(book, rows)
    off = resolve.demoted(book)
    assert list(off) == ["waive"] and off["waive"]["of"] == 10 and off["waive"]["rate"] == 0.67 and resolve.decision_stats(book)["waive"]["override_rate"] == 0.67  # four undone against six applied
    assert resolve.apply_housekeeping(book, {"finding:a": dict(outcome="waive", quote="A sentence.", answer="a", rationale="r", applied=False)}, answers.load(book), set(off)) == 0
    answers.reenable(book, "waive")
    assert resolve.demoted(book) == {}  # only decisions from now on count
    assert resolve.apply_housekeeping(book, {"finding:a": dict(outcome="waive", quote="A sentence.", answer="a", rationale="r", applied=False)}, answers.load(book), set()) == 1


def test_too_few_decisions_or_mostly_agreed_ones_do_not_switch_anything_off(book):
    decisions(book, [("waive", "undone", f"2026-11-15T10:0{i}:00+00:00") for i in range(4)])  # four: nothing to judge yet
    assert resolve.demoted(book) == {}
    decisions(book, [("attach", "applied", f"2026-11-15T10:0{i}:00+00:00") for i in range(8)] + [("attach", "undone", "2026-11-15T10:09:00+00:00")])
    assert resolve.demoted(book) == {}  # one in nine disagreed


def test_the_morning_report_says_what_the_tool_decided_and_what_it_stopped_doing(book):
    decisions(book, [("waive", "applied", f"2026-11-15T10:0{i}:00+00:00") for i in range(3)] + [("waive", "undone", f"2026-11-15T10:0{i}:00+00:00") for i in range(3, 8)])
    text = report.build_report(book)
    assert "## The tool's decisions" in text and "waive: 3 applied" in text and "Switched off" in text
    assert "## The tool's decisions" not in report.build_report(__import__("conftest").Project.create(book.root.parent / "other", "x\n"))  # nothing to say before any decision
