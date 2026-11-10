"""Milestone 14.13b-e: briefing preview and X-ray, prompt studio, A/B tests, calibration, arc views, rule tests."""

import json
import subprocess

import pytest

from bookforge import ab, arc, calibration, rules, rules_ai, scenefiles, stale, studio, xray
from bookforge.bible import store
from bookforge.layers.runner import StepContext
from bookforge.project import Project
from conftest import RuleLLM
from prose_fakes import prose
from qc_fakes import JUDGE, judge, between, user
from test_prose_qc import SID, book, go, qc_rules  # noqa: F401  (book is a fixture)
from test_report_assemble_bench import full  # noqa: F401  (fixture)

S1, S2 = "b1.ch01.s1", "b1.ch01.s2"
BEATS = "Check which of the planned beats the scene below"


def ctx(project, llm=None):
    return StepContext(project=project, layer="prose", llm=llm)


def beats_llm(happens):
    """Answers the beat check: every beat in `happens` (a set of numbers) is on the page, quoted from the scene's first words."""
    def reply(messages):
        text = between(user(messages), "scene")
        quote = " ".join(text.split()[:8])
        n = len([l for l in user(messages).split("## Planned beats")[1].splitlines() if l[:1].isdigit()])
        return json.dumps({"beats": [{"n": i, "happens": i in happens, "evidence": quote if i in happens else ""} for i in range(1, n + 1)]})
    return reply


# ── briefing preview and X-ray ──────────────────────────────────────────────

def test_the_preview_is_the_briefing_with_the_size_of_each_part(book):
    p = xray.preview(book, S2)
    assert p["tokens"] == sum(s["tokens"] for s in p["sections"]) and p["budget"] > p["tokens"]
    heads = [s["heading"] for s in p["sections"]]
    assert "Series north star" in heads and "This scene" in heads and any(s["text"] for s in p["sections"])


def kinds(project, sid=S2):
    return {f["kind"] for f in xray.input_findings(project, sid)}


def test_input_findings_name_what_the_writer_lacked(book):
    k = kinds(book)
    assert {"no_style_guide", "no_samples", "no_previous_text", "no_research"} <= k and "no_timeline" not in k
    (book.root / "style" / "guide.md").write_text("Plain, dry, short sentences.")
    (book.root / "style" / "samples" / "a.md").write_text("A sample passage about the sea and a clerk.")
    go(book, RuleLLM(qc_rules()))
    k2 = kinds(Project.open(book.root))
    assert not ({"no_style_guide", "no_samples", "no_previous_text"} & k2)


def test_an_unknown_character_is_a_problem(book):
    scenes = store.load_scenes(book)
    scenes[1].characters = ["anna", "ghost"]
    store.save_scenes(book, scenes)
    found = [f for f in xray.input_findings(book, S2) if f["kind"] == "unknown_entity"]
    assert found and found[0]["severity"] == "problem" and "ghost" in found[0]["message"]


def test_must_show_changes_and_trimmed_parts_are_listed(book):
    found = xray.input_findings(book, "b1.ch02.s2")
    assert any(f["kind"] == "must_show" and "deep cut" in f["message"] for f in found)


def test_beat_coverage_needs_a_quote_that_is_really_there(book):
    go(book, RuleLLM(qc_rules()))
    cov = xray.beat_coverage(ctx(book, RuleLLM([(BEATS, beats_llm({1}))])), S1)
    assert [(b["n"], b["happens"]) for b in cov] == [(1, True), (2, False)] and cov[0]["evidence"]
    liar = RuleLLM([(BEATS, lambda m: json.dumps({"beats": [{"n": 1, "happens": True, "evidence": "words that are not in the scene at all"}, {"n": 2, "happens": False, "evidence": ""}]}))])
    assert not xray.beat_coverage(ctx(book, liar), S1)[0]["happens"]


def test_the_diagnosis_separates_missing_input_weak_prompt_and_model_limit(book):
    go(book, RuleLLM(qc_rules()))
    (book.root / "style" / "guide.md").write_text("Plain, dry, short sentences.")
    (book.root / "style" / "samples" / "a.md").write_text("A sample passage about the sea and a clerk.")
    p = Project.open(book.root)
    res = xray.xray(ctx(p, RuleLLM([(BEATS, beats_llm({1}))])), S1, beats=True)
    assert res["diagnosis"]["cause"] == "model_limit"
    assert "likely a limit of the writer model" in res["diagnosis"]["reasons"][0] and "2" in res["diagnosis"]["reasons"][-1]
    studio.save_override(p, "prose", studio.get_template(p, "prose")["default"] + "\nBe brief.\n")
    assert xray.xray(ctx(p, RuleLLM([(BEATS, beats_llm({1}))])), S1, beats=True)["diagnosis"]["cause"] == "weak_prompt"
    assert xray.xray(ctx(p, RuleLLM([(BEATS, beats_llm({1, 2}))])), S1, beats=True)["diagnosis"]["cause"] == "none"


def test_missing_input_wins_over_the_other_causes(book):
    go(book, RuleLLM(qc_rules()))
    res = xray.xray(ctx(book, RuleLLM([(BEATS, beats_llm({1}))])), S1, beats=True)  # no style guide in the fixture
    assert res["diagnosis"]["cause"] == "missing_input" and any("style guide" in r for r in res["diagnosis"]["reasons"])


def test_xray_without_beats_makes_no_model_call(book):
    llm = RuleLLM([])
    res = xray.xray(ctx(book, llm), S1)
    assert not llm.calls and res["beats"] is None and res["findings"]


def test_a_failing_beat_check_is_reported_not_raised(book):
    res = xray.xray(ctx(book, RuleLLM([(BEATS, "not json")])), S1, beats=True)  # S1 has no text yet
    assert res["beats"] is None and "no text yet" in res["beats_error"]


# ── prompt studio ───────────────────────────────────────────────────────────

def test_templates_are_listed_with_their_slots(book):
    t = {x["name"]: x for x in studio.list_templates(book)}
    assert {"prose", "critic", "continuity"} <= set(t) and "briefing" in t["prose"]["slots"] and t["prose"]["overridden"] is False


def test_an_override_is_saved_checked_and_removed(book):
    default = studio.get_template(book, "prose")["default"]
    result = studio.save_override(book, "prose", default.replace("Return only the scene text.", "Return only the scene."))
    assert result == {"errors": [], "warnings": []}
    got = studio.get_template(book, "prose")
    assert got["override"] and "Return only the scene." in got["effective"] and "-Return only the scene text." in got["diff"]
    assert (book.root / "workbench" / "prompts" / "prose.md").exists()
    studio.delete_override(book, "prose")
    assert studio.get_template(book, "prose")["override"] is None
    with pytest.raises(studio.StudioError):
        studio.delete_override(book, "prose")


def test_unknown_slots_are_refused_and_dropped_slots_warned_about(book):
    with pytest.raises(studio.StudioError) as e:
        studio.save_override(book, "prose", "Write {nonsense} now. {briefing}")
    assert "unknown slot" in str(e.value) and "{nonsense}" in str(e.value)
    ok = studio.check_candidate("prose", "Write the scene. {briefing}")
    assert ok["errors"] == [] and any("{scene_id}" in w for w in ok["warnings"])
    with pytest.raises(studio.StudioError):
        studio.save_override(book, "prose", "   ")
    with pytest.raises(studio.StudioError):
        studio.get_template(book, "no_such_prompt")


def test_an_override_changes_what_the_writer_is_asked(book):
    default = studio.get_template(book, "prose")["default"]
    studio.save_override(book, "prose", default.replace("Return only the scene text.", "ZEBRA RULE: return only the scene."))
    llm = RuleLLM(qc_rules())
    go(Project.open(book.root), llm)
    assert any("ZEBRA RULE" in c["messages"][-1]["content"] for c in llm.calls)


# ── A/B tests ───────────────────────────────────────────────────────────────

def ab_llm(marker="ZEBRA"):
    """The writer writes plain prose, and prose with 'Zebra' when the prompt carries the marker; the judge prefers Zebra."""
    def write(messages):
        return prose(3, 22) + (" Zebra." if marker in messages[-1]["content"] else "")
    return RuleLLM([("Write the scene described below", write), (JUDGE, judge("Zebra"))])


def candidate(book):
    default = studio.get_template(book, "prose")["default"]
    return default.replace("Return only the scene text.", "ZEBRA: return only the scene text.")


def test_an_ab_test_runs_both_prompts_on_the_benchmarks_and_judges_them(book):
    s = ab.run_ab(ctx(book, ab_llm()), "prose", candidate(book), only=["quarrel", "reunion"])
    assert s["benchmarks"] == 2 and s["judge"] == {"a": 0, "b": 2, "tie": 0} and s["template"] == "prose"
    d = book.root / "workbench" / "experiments" / s["name"]
    assert (d / "variant-a.md").exists() and "ZEBRA" in (d / "variant-b.md").read_text() and "+ZEBRA" in (d / "diff.patch").read_text()
    assert "Zebra" in (d / "quarrel.b.md").read_text() and "Zebra" not in (d / "quarrel.a.md").read_text()
    assert "experiment" in subprocess.run(["git", "-C", str(book.root), "log", "--format=%s", "-1"], capture_output=True, text=True).stdout


def test_ab_refuses_what_it_cannot_test(book):
    with pytest.raises(ab.ABError):
        ab.run_ab(ctx(book, ab_llm()), "critic", "x {rubric}")
    with pytest.raises(ab.ABError):
        ab.run_ab(ctx(book, ab_llm()), "prose", "Write {nonsense}")
    with pytest.raises(ab.ABError) as e:
        ab.run_ab(ctx(book, ab_llm()), "prose", studio.get_template(book, "prose")["default"])
    assert "same as the current" in str(e.value)


def test_you_vote_blind_and_the_mapping_is_revealed_after_the_vote(book):
    s = ab.run_ab(ctx(book, ab_llm()), "prose", candidate(book), only=["quarrel", "reunion"])
    v = ab.view(book, s["name"])
    assert [p["id"] for p in v["pairs"]] == ["quarrel", "reunion"] and all(not p["voted"] and "first_is" not in p for p in v["pairs"])
    assert {p["first"] for p in v["pairs"]} | {p["second"] for p in v["pairs"]}  # both texts are shown, order hidden from you
    pair = v["pairs"][0]
    zebra_first = "Zebra" in pair["first"]
    after = ab.vote(book, s["name"], "quarrel", "first" if zebra_first else "second")
    voted = after["pairs"][0]
    assert voted["voted"] and voted["vote"] == "b" and {voted["first_is"], voted["second_is"]} == {"a", "b"} and voted["judge"] == "b"
    assert after["yours"] == {"a": 0, "b": 1, "tie": 0, "of": 2} and not after["pairs"][1]["voted"]
    assert v["judge"] is None and after["judge"] is None  # the judge's totals stay hidden until every pair has your vote
    last = ab.vote(book, s["name"], "reunion", "tie")
    assert last["yours"]["tie"] == 1 and last["judge"] == {"a": 0, "b": 2, "tie": 0}
    with pytest.raises(ab.ABError):
        ab.vote(book, s["name"], "nope", "first")
    with pytest.raises(ab.ABError):
        ab.vote(book, s["name"], "quarrel", "left")


def test_the_blind_order_is_not_always_the_same(book):
    orders = set()
    for _ in range(3):
        s = ab.run_ab(ctx(book, ab_llm()), "prose", candidate(book), only=["quarrel"])
        orders.add(tuple(json.loads((book.root / "workbench" / "experiments" / s["name"] / "results.json").read_text())["order"]["quarrel"]))
    assert orders <= {("a", "b"), ("b", "a")}


def test_a_winning_candidate_is_promoted_to_the_series_override(book):
    s = ab.run_ab(ctx(book, ab_llm()), "prose", candidate(book), only=["quarrel"])
    ab.promote(book, s["name"])
    assert "ZEBRA" in studio.get_template(book, "prose")["override"]
    assert ab.list_experiments(book)[0]["promoted"] is True
    with pytest.raises(ab.ABError):
        ab.view(book, "ab-19990101-000000")
    with pytest.raises(ab.ABError):
        ab.view(book, "../x")


# ── calibration ─────────────────────────────────────────────────────────────

def scored(project, sid, scores):
    path = scenefiles.review_path(project, sid)
    data = json.loads(path.read_text())
    data["critic"] = {"scores": scores}
    path.write_text(json.dumps(data))


def all_(n):
    return {c: n for c in calibration.CRITERIA}


def test_calibration_compares_your_scores_with_the_critics_per_criterion(full):
    for sid, (mine, critic) in {"b1.ch01.s1": (5, 4), "b1.ch01.s2": (3, 3), "b1.ch02.s1": (2, 4)}.items():
        calibration.record(full, sid, all_(mine))
        scored(full, sid, all_(critic))
    r = calibration.report(full)
    assert r["compared"] == 3 and r["criteria"]["voice"] == {"n": 3, "mean_abs_diff": 1.0, "bias": -0.33, "within_one": 0.67}
    assert r["ranking_disagreements"] == 1 and r["needs_recalibration"] is False  # one pair disagrees: tolerated


def test_more_than_one_ranking_disagreement_needs_recalibration(full):
    for sid, (mine, critic) in {"b1.ch01.s1": (5, 2), "b1.ch01.s2": (3, 3), "b1.ch02.s1": (1, 5)}.items():
        calibration.record(full, sid, all_(mine))
        scored(full, sid, all_(critic))
    r = calibration.report(full)
    assert r["ranking_disagreements"] == 3 and r["needs_recalibration"] and "critic_rubric.md" in r["advice"]


def test_calibration_input_is_checked(full):
    with pytest.raises(calibration.CalibrationError):
        calibration.record(full, "b1.ch09.s9", all_(3))
    with pytest.raises(calibration.CalibrationError):
        calibration.record(full, S1, {**all_(3), "voice": 6})
    with pytest.raises(calibration.CalibrationError):
        calibration.record(full, S1, {"voice": 3})
    assert calibration.report(full)["compared"] == 0 and "at least 3" in calibration.report(full)["advice"]


def test_scenes_the_critic_did_not_score_are_kept_but_not_compared(full):
    calibration.record(full, S1, all_(4))
    r = calibration.report(full)
    assert r["scenes"][0]["critic"] is None or "critic" in r["scenes"][0]


# ── the arc ─────────────────────────────────────────────────────────────────

def set_tensions(project, values):
    chapters = store.load_chapters(project)
    for c, v in zip(chapters, values):
        c.tension = v
    store.save_chapters(project, chapters)
    return Project.open(project.root)


def test_the_tension_curve_and_its_warnings(book):
    t = arc.tension(set_tensions(book, [3, 4, 5, 6]))
    assert [c["tension"] for c in t["chapters"]] == [3, 4, 5, 6] and t["chapters"][0]["scenes"] == 2
    assert any("no climax" in n for n in t["notes"]) and not any("flat stretch" in n for n in t["notes"])  # a steady rise is not flat
    flat = arc.tension(set_tensions(book, [5, 5, 6, 5]))
    assert any("flat stretch: b1.ch01 to b1.ch04" in n for n in flat["notes"])
    ok = arc.tension(set_tensions(book, [3, 5, 6, 9]))
    assert ok["notes"] == []
    early = arc.tension(set_tensions(book, [9, 4, 3, 5]))
    assert any("before the last third" in n for n in early["notes"])


def test_changing_tension_previews_its_consequence_and_applies_only_when_told(full):
    before = [c.tension for c in store.load_chapters(full)]
    preview = arc.set_tension(full, "b1.ch02", 9)
    assert preview["applied"] is False and preview["written"] == ["b1.ch02.s1", "b1.ch02.s2"] and "affects 2 scene(s), 2 of them written" in preview["consequence"]
    assert [c.tension for c in store.load_chapters(full)] == before
    done = arc.set_tension(full, "b1.ch02", 9, apply=True)
    assert done["applied"] is True and store.load_chapters(full)[1].tension == 9
    assert {s.scene for s in stale.scan(full).scenes} >= {"b1.ch02.s1", "b1.ch02.s2"}  # the chapter changed: its scenes are out of date
    assert arc.set_tension(full, "b1.ch02", 9, apply=True)["consequence"] == "no change"
    for bad in (0, 11, "5", True):
        with pytest.raises(arc.ArcError):
            arc.set_tension(full, "b1.ch02", bad)
    with pytest.raises(arc.ArcError):
        arc.set_tension(full, "b1.ch99", 5)


def test_milestones_are_labels_pinned_to_chapters_in_book_order(full):
    arc.save_milestone(full, "riddle solved", "b1.ch04")
    arc.save_milestone(full, "body found", "b1.ch02")
    m = arc.milestones(full)
    assert [(i["id"], i["label"], i["at"]) for i in m["items"]] == [("m2", "body found", 1), ("m1", "riddle solved", 3)]
    assert m["items"][0]["title"] and m["items"][0]["problem"] is None and len(m["chapters"]) >= 4
    arc.save_milestone(full, "breakthrough", "b1.ch03", "m1")  # change an existing one
    assert {i["id"]: i["chapter"] for i in arc.milestones(full)["items"]}["m1"] == "b1.ch03"
    arc.delete_milestone(full, "m2")
    arc.save_milestone(full, "first suspect", "b1.ch01")
    assert {i["id"] for i in arc.milestones(full)["items"]} == {"m1", "m2"}
    for args in (("", "b1.ch01"), ("x", "b1.ch99"), ("x" * 121, "b1.ch01"), ("x", "b1.ch01", "m9")):
        with pytest.raises(arc.ArcError):
            arc.save_milestone(full, *args)
    with pytest.raises(arc.ArcError):
        arc.delete_milestone(full, "nope")
    assert not stale.scan(full).scenes  # notes only: nothing goes stale


def test_the_thread_map_marks_setups_without_a_payoff(full):
    arc.upsert_thread(full, "ledger", "the ledger's first entry", "b1.ch01.s1", "b1.ch04.s1")
    arc.upsert_thread(full, "key", "the vestry key", "b1.ch02.s1")
    arc.upsert_thread(full, "backwards", "wrong way round", "b1.ch03.s1", "b1.ch01.s2")
    m = arc.thread_map(full)
    by = {t["id"]: t for t in m["threads"]}
    assert by["ledger"]["problem"] is None and by["ledger"]["setup_at"] == 0 and by["ledger"]["payoff_at"] == 6
    assert by["key"]["problem"] == "no payoff yet" and by["backwards"]["problem"] == "the payoff comes before (or in) the setup scene" and m["unpaid"] == 1
    arc.upsert_thread(full, "key", "the vestry key", "b1.ch02.s1", "b1.ch03.s2")
    assert {t["id"]: t for t in arc.thread_map(full)["threads"]}["key"]["problem"] is None
    arc.delete_thread(full, "key")
    assert [t["id"] for t in arc.thread_map(full)["threads"]] == ["backwards", "ledger"]
    for args in (("Bad Id", "n", S1), ("x", "n", "b1.ch09.s1"), ("x", "n", ""), ("x", "n", S1, "nonsense")):
        with pytest.raises(arc.ArcError):
            arc.upsert_thread(full, *args)
    with pytest.raises(arc.ArcError):
        arc.delete_thread(full, "nope")


# ── testing a rule, and feedback to rule ────────────────────────────────────

def test_a_phrase_rule_is_tested_on_chapter_one_without_a_model(full):
    text = scenefiles.final_path(full, S1).read_text()
    phrase = " ".join(text.split()[2:5])
    r = rules.Rule(id="t", type="banned_phrase", phrase=phrase, text="no", severity="warn")
    out = rules_ai.test_rule(ctx(full, RuleLLM([])), r)
    assert out["total_hits"] >= 1 and out["scenes"][0]["scene"] == S1 and phrase.split()[0] in out["scenes"][0]["hits"][0]
    assert {x["scene"] for x in out["scenes"]} == {S1, S2}  # chapter 1 only


def test_a_style_rule_is_tested_by_the_model_and_a_made_up_quote_does_not_count(full):
    text = scenefiles.final_path(full, S1).read_text()
    quote = " ".join(text.split()[:8])
    r = rules.Rule(id="t", type="style_rule", text="No gulls.", severity="block")
    yes = RuleLLM([("Does the scene below break this rule", json.dumps({"violates": True, "evidence": quote}))])
    assert rules_ai.test_rule(ctx(full, yes), r)["total_hits"] == 2
    liar = RuleLLM([("Does the scene below break this rule", json.dumps({"violates": True, "evidence": "words that are nowhere in it"}))])
    assert rules_ai.test_rule(ctx(full, liar), r)["total_hits"] == 0
    bad = RuleLLM([("Does the scene below break this rule", "not json")])
    assert all(x["error"] for x in rules_ai.test_rule(ctx(full, bad), r)["scenes"])


def test_there_is_nothing_to_test_before_anything_is_written(book):
    with pytest.raises(rules_ai.RuleTestError):
        rules_ai.test_rule(ctx(book, RuleLLM([])), rules.Rule(id="t", type="style_rule", text="x"))


def feedback_llm(**fields):
    base = {"type": "style_rule", "scope": "series", "target": "", "severity": "warn", "text": "Avoid purple adjectives.", "example": "crimson sky", "phrase": ""}
    return RuleLLM([("The author read a passage of a scene", json.dumps({**base, **fields}))])


def test_a_comment_becomes_a_proposed_rule_that_is_not_saved(full):
    p = rules_ai.propose_rule(ctx(full, feedback_llm()), S1, "The sky bled crimson over the quay.", "too purple")
    assert p["id"] == "avoid-purple-adjectives" and p["type"] == "style_rule" and p["scope"] == "series" and p["enabled"] is True
    rules.Rule(**p)  # it is a valid rule
    assert rules.load_rules(full) == []


def test_a_proposal_is_made_consistent_with_the_scene(full):
    p = rules_ai.propose_rule(ctx(full, feedback_llm(type="character_voice", scope="series", text="Anna is blunt.")), S1, "x y", "she is too soft")
    assert (p["type"], p["scope"], p["target"]) == ("character_voice", "character", "anna")
    p = rules_ai.propose_rule(ctx(full, feedback_llm(scope="scene", target="whatever")), S1, "x y", "just here")
    assert p["target"] == S1
    p = rules_ai.propose_rule(ctx(full, feedback_llm(type="banned_phrase", phrase="crimson sky")), S1, "x y", "never this")
    assert p["phrase"] == "crimson sky" and rules.Rule(**p)
    rules.upsert(full, rules.Rule(**p))
    assert rules_ai.propose_rule(ctx(full, feedback_llm(type="banned_phrase", phrase="crimson sky")), S1, "x y", "never this")["id"].endswith("-2")


def test_feedback_needs_a_passage_a_comment_and_a_scene(full):
    for args in ((S1, "", "c"), (S1, "p", " "), ("b1.ch09.s9", "p", "c")):
        with pytest.raises(rules_ai.RuleTestError):
            rules_ai.propose_rule(ctx(full, feedback_llm()), *args)
    with pytest.raises(Exception):
        rules_ai.propose_rule(ctx(full, feedback_llm(type="nonsense")), S1, "p", "c")
