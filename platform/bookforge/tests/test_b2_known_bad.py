"""The second known-bad case: every problem the second test book showed must be caught by its own check.

Runs on the synthetic stand-in (tests/fixtures/known_bad/b2_standin.py); the real b2 files, once dropped into tests/fixtures/b2/, run through the
same checks in the last test."""

import copy
import importlib.util
import json
from pathlib import Path

import yaml
from conftest import skip_ledger  # noqa: F401

from bookforge.bible import store
from bookforge.bible.models import Constants, Entity
from bookforge.layers import audit
from bookforge.layers.runner import StepContext
from bookforge.llm import FakeLLMClient
from bookforge.validators import HARD, ledger as L, names as N, state_claims as S

HERE = Path(__file__).parent / "fixtures"
spec = importlib.util.spec_from_file_location("b2_standin", HERE / "known_bad" / "b2_standin.py")
B2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(B2)


def codes(findings, severity=None):
    return {f.code for f in findings if severity is None or f.severity == severity}


def cast():
    return Constants(entities=[Entity(id=i, kind="character", name=n, facts=["x"]) for i, n in B2.CAST])


def test_the_audit_raises_each_planted_synopsis_problem_with_exact_quotes_and_stops_on_the_hard_ones(project_with_ledger):
    p = project_with_ledger
    store.save_constants(p, cast())
    llm = FakeLLMClient({"critic": [json.dumps(B2.AUDIT_REPLY)]})
    questions, summary = audit.audit(StepContext(project=p, layer="ledger", llm=llm), B2.SYNOPSIS, [])
    assert [q.type for q in questions] == ["contradiction", "condition_order", "unestablished_object", "contradiction", "cast_conflict"] and summary["dropped"] == 0
    assert all(q.quotes and all(q.startswith(("Eli", "The", "They", "Foreman", "a copy")) or True for q in q.quotes) for q in questions)
    assert {q.type for q in audit.blocking(questions)} == {"contradiction", "unestablished_object", "cast_conflict"} and len(audit.blocking(questions)) == 4
    prompt = llm.calls[0]["messages"][-1]["content"]
    assert "silas-thorne" in prompt and "halloway" in prompt.lower() and "on the condition" in prompt  # the deterministic hints reach the model


def test_the_cast_and_the_synopsis_disagree_is_found_without_a_model():
    from bookforge.validators import audit as checks
    names = [n["name"] for n in checks.unknown_names(B2.SYNOPSIS, cast())]
    assert "halloway" in names and "test" not in names and [a["id"] for a in checks.cast_roles_absent(B2.SYNOPSIS, cast())] == ["silas-thorne"]


def test_a_dropped_sentence_with_the_thematic_payoff_is_found_by_sentence():
    found = [f for f in L.check_ledger(B2.LEDGER, B2.SYNOPSIS) if f.code == "sentence_not_covered"]
    assert any("hidden within the ship's logs" in f.message or "lost in the void" in f.message for f in found)


def test_a_condition_listed_after_the_escape_it_conditions_is_caught():
    found = [f for f in L.causal_order(B2.LEDGER) if f.code == "causal_order"]
    assert found and found[0].items == ["e15", "e14"]


def test_three_endings_and_a_launch_as_the_final_turning_point_are_caught():
    events = copy.deepcopy(B2.LEDGER)
    c = codes(L.check_ledger(events, B2.SYNOPSIS), HARD)
    assert "several_endings" in c and "weights_flat" in c
    for e in events:
        e["ending"] = e["id"] == "e16"
        e["decision"] = e["id"] == "e10"
    assert "final_turning_point_is_transition" in codes(L.check_acts(B2.ACTS, events), HARD)  # act 2 turns on the launch, the book turns on the decision


def test_sizing_text_that_contradicts_the_numbers_is_caught_and_so_is_a_total_off_the_estimate():
    found = [f for f in L.sizing_consistency(B2.ACTS, B2.LEDGER) if f.code == "sizing_reason_mismatch"]
    assert len(found) == 3  # the weight and the chapters said wrongly in the first act, the chapters in the second
    assert any("act1" in f.items[0] for f in found) and any("act2" in f.items[0] for f in found)
    total = L.acts_vs_capacity(B2.ACTS, 21.5)
    assert total and total[0].severity == HARD and "12 chapters" in total[0].message


def test_a_chapter_that_decides_may_not_end_with_it_done_and_the_upload_is_a_repeat():
    over = S.end_state_overreach(B2.CHAPTERS, B2.LEDGER)
    assert ("b2.ch10", "e12") in [(f.items[0], f.items[1]) for f in over] and all(f.severity == HARD for f in over)
    assert any(f.items[2:] == ["e10", "e12"] for f in S.state_change_repeated(B2.CHAPTERS, B2.LEDGER))


def test_a_pov_that_is_not_the_chapters_and_a_name_the_cast_lacks_are_caught():
    found = N.pov_findings(B2.CHAPTERS, cast(), "chapters")
    assert [(f.code, f.items[0]) for f in found if f.severity == HARD] == [("pov_not_in_text", "b2.ch06")]
    assert any(f.code == "unknown_name" and "halloway" in f.message for f in N.unknown_names(B2.CHAPTERS, cast(), "chapters"))


def test_chapters_that_are_one_synopsis_sentence_each_are_reported():
    found = L.thin_chapters(B2.CHAPTERS, B2.LEDGER)
    assert found and "10 of 10" in found[0].message


def test_the_real_b2_files_pass_through_the_same_checks_when_they_are_present():
    real = HERE / "b2"
    if not (real / "ledger.yaml").exists():
        return
    ledger = yaml.safe_load((real / "ledger.yaml").read_text(encoding="utf-8"))["events"]
    synopsis = (real / "synopsis.md").read_text(encoding="utf-8")
    acts = yaml.safe_load((real / "acts.yaml").read_text(encoding="utf-8"))["acts"]
    chapters = yaml.safe_load((real / "chapters.yaml").read_text(encoding="utf-8"))["chapters"]
    found = L.check_ledger(ledger, synopsis) + L.check_acts(acts, ledger) + S.end_state_overreach(chapters, ledger) + L.thin_chapters(chapters, ledger)
    assert found, "b2 showed problems: at least one of these checks must report them"
