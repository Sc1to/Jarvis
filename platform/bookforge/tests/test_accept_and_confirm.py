"""Accepting a hard finding, and the critic's second look at repeat findings."""

import json

import pytest
from conftest import RuleLLM
from ledger_structure_fakes import chapters, dump, install_ledger, rules
from structure_fakes import ready

from bookforge.bible import store
from bookforge.errors import LayerError
from bookforge.layers import HANDLERS
from bookforge.layers.runner import StepContext, run
from bookforge.layers.structure import _book_chapter_checks
from bookforge.qc.repeat_confirm import confirm_repeats
from bookforge.validators import HARD, SOFT, accepted, findings as F, store as findings_store


def flat_book(p):
    ch = [c.model_copy(update={"tension": 9, "id": f"b1.ch{i:02d}"}) for i, c in enumerate(store.load_chapters(p) * 2, 1)]
    return ch


def planned(project):
    p = ready(project)
    install_ledger(p)
    run(p, RuleLLM(rules()), HANDLERS, until="chapters")
    return p


def test_a_hard_finding_blocks_until_the_author_accepts_it_and_then_stays_visible_as_accepted(project):
    p = planned(project)
    ledger = store.load_ledger(p)
    base = [c.model_copy(update={"tension": 9}) for c in store.load_chapters(p)]
    # four chapters are below the size at which flatness is judged: plan eight, event coverage aside, to see the finding itself
    flat = [c.model_copy(update={"id": f"b1.ch{i:02d}", "events_covered": [f"e{(i - 1) % 4 + 1}"]}) for i, c in enumerate(base * 2, 1)]
    try:
        _book_chapter_checks(p, flat, ledger)
    except LayerError:
        pass
    saved = findings_store.load(p, "chapters")
    flat_finding = next(f for f in saved["findings"] if f["code"] == "flat_tension")
    assert flat_finding["severity"] == "hard" and not flat_finding["accepted"]
    accepted.accept(p, "chapters", "flat_tension", flat_finding["items"])
    after = accepted.apply(p, [F.hard("chapters", "flat_tension", "tension is flat", flat_finding["items"])])
    assert after[0].severity == SOFT and after[0].accepted and after[0].message.startswith("(accepted by you)")
    other = accepted.apply(p, [F.hard("chapters", "flat_tension", "tension is flat", ["b1.ch01"])])  # a different finding still blocks
    assert other[0].severity == HARD
    fp = accepted.fingerprint("chapters", "flat_tension", flat_finding["items"])
    assert accepted.unaccept(p, fp) and not accepted.unaccept(p, fp)


def repeat_finding():
    return F.hard("scenes", "event_repeated", "the same event is planned in 2 chapters", ["b1.ch02", "b1.ch05"], ["Anna enters the ferry through the hatch", "Anna slips inside the ferry by the hatch"])


def ctx_with(project, reply):
    return StepContext(project=project, layer="chapters", llm=RuleLLM([("A check found passages", reply)]))


def test_the_critic_can_downgrade_a_repeat_that_is_a_different_event(project):
    out = confirm_repeats(ctx_with(project, json.dumps({"same_event": False, "reason": "the second is the consequence of the first"})), [repeat_finding()])
    assert out[0].severity == SOFT and "different events" in out[0].message


def test_a_confirmed_repeat_an_unclear_answer_and_a_failed_call_all_keep_the_finding(project):
    assert confirm_repeats(ctx_with(project, json.dumps({"same_event": True, "reason": "same hatch, same entry"})), [repeat_finding()])[0].severity == HARD
    assert confirm_repeats(ctx_with(project, "not json at all"), [repeat_finding()])[0].severity == HARD
    assert confirm_repeats(StepContext(project=project, layer="x", llm=RuleLLM([])), [repeat_finding()])[0].severity == HARD  # no rule matches: the call raises


def test_only_repeat_findings_with_two_passages_are_put_to_the_critic(project):
    llm = RuleLLM([("A check found passages", json.dumps({"same_event": False, "reason": "x"}))])
    ctx = StepContext(project=project, layer="chapters", llm=llm)
    other = F.hard("scenes", "flat_tension", "flat", ["b1.ch01"], ["x", "y"])
    no_evidence = F.hard("scenes", "event_repeated", "r", ["a", "b"], ["only one"])
    out = confirm_repeats(ctx, [other, no_evidence])
    assert [f.severity for f in out] == [HARD, HARD] and llm.calls == []
    project.config.qc.confirm_repeats = False
    assert confirm_repeats(ctx, [repeat_finding()])[0].severity == HARD and llm.calls == []


def test_the_critics_second_look_is_remembered_per_passage_pair(project):
    from bookforge.qc import repeat_confirm
    repeat_confirm._ANSWERS.clear()
    llm = RuleLLM([("A check found passages", json.dumps({"same_event": False, "reason": "a consequence"}))])
    ctx = StepContext(project=project, layer="chapters", llm=llm)
    out1 = confirm_repeats(ctx, [repeat_finding()])
    out2 = confirm_repeats(ctx, [repeat_finding()])  # a correction round or a cached reuse asks the same again
    assert out1[0].severity == out2[0].severity == SOFT and len(llm.calls) == 1
    repeat_confirm._ANSWERS.clear()
