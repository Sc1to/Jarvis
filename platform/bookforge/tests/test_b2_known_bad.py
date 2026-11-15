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
    return Constants(entities=[Entity(id=i, kind="character", name=n, facts=B2.CAST_FACTS.get(i, ["x"])) for i, n in B2.CAST])


def test_the_audit_raises_each_planted_synopsis_problem_with_exact_quotes_and_stops_on_the_hard_ones(project_with_ledger):
    p = project_with_ledger
    store.save_constants(p, cast())
    llm = FakeLLMClient({"critic": [json.dumps(B2.AUDIT_REPLY)]})
    questions, summary = audit.audit(StepContext(project=p, layer="ledger", llm=llm), B2.SYNOPSIS, [])
    assert [q.type for q in questions] == ["condition_order", "contradiction", "unestablished_object", "contradiction", "unknown_name", "cast_conflict"]  # the condition is found without the model and not asked twice
    assert summary["dropped"] == 0 and {q.type for q in questions} == {"contradiction", "condition_order", "unestablished_object", "unknown_name", "cast_conflict"}
    assert all(q.quotes for q in questions) and "The cast (silas-thorne) says" in questions[-1].why
    assert all(audit.is_blocking(q) for q in questions) and len(audit.blocking(questions)) == len(questions)
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


REAL = HERE / "b2"


def test_the_real_b2_acts_say_one_size_and_plan_another():
    """b2's real acts.yaml (from the mini PC): act 1 quotes weight 8 against a computed 9; acts 2 and 3 say 'eight' and 'nine' chapters and plan six."""
    acts = yaml.safe_load((REAL / "acts.yaml").read_text(encoding="utf-8"))["acts"]
    found = L.sizing_consistency(acts, [])  # no ledger at hand: the computed note inside the reason carries the weight
    by_act = {}
    for f in found:
        by_act.setdefault(f.items[0], []).append(f.message)
    assert set(by_act) == {"b2.act1", "b2.act2", "b2.act3"}
    assert any("weight 8" in m for m in by_act["b2.act1"]) and any("eight chapters" in m for m in by_act["b2.act2"]) and any("nine chapters" in m for m in by_act["b2.act3"])
    assert L.acts_vs_capacity(acts, 21.5)  # the ledger estimated 21.5 chapters, the acts planned 16


def test_the_real_b2_audit_keeps_the_real_finding_drops_the_two_wrong_ones_and_finds_the_condition_without_a_model():
    """What the model said about b2's real synopsis (the saved ledger.yaml of the first audit run): q1 was right; q2 attached an unrelated second
    sentence to a contradiction inside one sentence; q3 invented a conflict with the cast. And the condition stated after the escape was missed."""
    synopsis = (REAL / "synopsis.md").read_text(encoding="utf-8")
    cast_ = Constants(entities=[Entity(id="eli-vance", kind="character", name="Eli Vance", facts=["a debtor"]), Entity(id="mara-kovic", kind="character", name="Mara Kovic", facts=["a technician"]),
                                Entity(id="silas-thorne", kind="character", name="Silas Thorne", facts=["the site foreman"]),
                                Entity(id="kestrel", kind="object", name="Kestrel", facts=["buried behind a collapsed toxic waste bulkhead"])])
    q1 = ["Foreman Halloway, a ruthless enforcer who views Eli as a liability, begins hunting them down.", "Halloway intercepts them at the launch bay, armed with a plasma cutter and backed by automated drones."]
    lost = "The drive containing the truth is lost in the void, hidden within the ship's internal logs, available only for future generations to discover."
    unrelated = "Eli realizes that he cannot save her; the medical supplies are insufficient, and the corporation will not provide aid to a worker who has become a liability."
    q3 = ["She warns Eli that his grandfather did not simply vanish; he was executed by the corporation for discovering that the mining operations were destabilizing the asteroid's core to maximize yield.",
          "The corporation buried the ship and the evidence to protect its structural stability, prioritizing the asset over the lives of the workers."]
    model = {"findings": [
        {"type": "unknown_name", "quotes": q1, "why": "The synopsis repeatedly names the antagonist 'Halloway', but the cast defines the site foreman as 'Silas Thorne'.", "fixes": ["Replace Halloway with Silas Thorne"]},
        {"type": "contradiction", "quotes": [lost, unrelated], "why": "The synopsis states the drive is 'lost in the void' but immediately says it is 'hidden within the ship's internal logs'.",
         "fixes": ["Clarify that the physical drive was destroyed but the information was saved to the ship's internal logs"]},
        {"type": "cast_conflict", "quotes": q3, "why": "The synopsis says the corporation buried the ship to protect structural stability, but the cast entry for the Kestrel says it is buried behind a collapsed bulkhead.",
         "fixes": ["Revise the synopsis"]}]}
    kept, dropped = audit.parse_findings(model, synopsis, cast_)
    assert [(f["type"], len(f["quotes"])) for f in kept] == [("unknown_name", 2), ("contradiction", 1)] and kept[1]["quotes"] == [lost] and dropped == 1  # the cast conflict names no cast fact
    found = audit.deterministic_findings(synopsis)
    assert len(found) == 1 and found[0]["type"] == "condition_order" and found[0]["quotes"][1].startswith("They allow Eli to escape, but only on the condition")
    assert found[0]["quotes"][0].startswith("The ship breaks through the asteroid's crust, escaping")
    from bookforge.validators import audit as checks
    things = {t["noun"] for t in checks.unintroduced_things(synopsis, cast_)}
    assert {"drive", "data"} <= things  # the objects the text never introduces are among the model's starting points
