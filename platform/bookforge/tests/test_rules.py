"""Milestone 14.13a: the rules panel: storage, scope, and enforcement by each checker."""

import json

import pytest
import yaml

from bookforge import rules, scenefiles, stale
from bookforge.bible import store
from bookforge.briefing import build_briefing
from bookforge.layers.prose import check_context
from bookforge.project import Project
from bookforge.qc.mechanical import check_scene
from conftest import RuleLLM
from qc_fakes import CONTINUITY, CRITIC, continuity, critic, between, user
from test_prose_qc import SID, book, go, qc_rules, review  # noqa: F401  (book is a fixture)
from test_report_assemble_bench import full  # noqa: F401  (fixture)

S1 = "b1.ch01.s1"


def rule(**kw):
    base = {"id": "no-purple", "type": "style_rule", "text": "No purple prose.", "severity": "warn"}
    return rules.Rule(**{**base, **kw})


def scene(project, sid=S1):
    return next(s for s in store.load_scenes(project) if s.id == sid)


# ── the record ──────────────────────────────────────────────────────────────

def test_a_rule_is_validated():
    with pytest.raises(ValueError):
        rule(type="banned_phrase")  # no phrase
    with pytest.raises(ValueError):
        rule(type="banned_phrase", phrase="re:(unclosed")
    with pytest.raises(ValueError):
        rule(scope="character")  # no target
    with pytest.raises(ValueError):
        rule(type="character_voice", scope="series")
    with pytest.raises(ValueError):
        rule(id="Bad Id")
    assert rule(type="banned_phrase", phrase="re:\\bsuddenly\\b").phrase


def test_rules_are_stored_in_the_workbench_and_replaced_by_id(book):
    assert rules.load_rules(book) == []
    rules.upsert(book, rule())
    rules.upsert(book, rule(text="Plain words only."))
    rules.upsert(book, rule(id="other"))
    loaded = rules.load_rules(book)
    assert [r.id for r in loaded] == ["no-purple", "other"] and loaded[0].text == "Plain words only."
    assert (book.root / "workbench" / "rules.yaml").exists()
    rules.delete(book, "other")
    assert [r.id for r in rules.load_rules(book)] == ["no-purple"]
    with pytest.raises(rules.RuleError):
        rules.delete(book, "nope")


def test_a_broken_rules_file_is_named(book):
    (book.root / "workbench").mkdir(exist_ok=True)
    (book.root / "workbench" / "rules.yaml").write_text("rules:\n- id: x\n  type: style_rule\n")
    with pytest.raises(rules.RuleError) as e:
        rules.load_rules(book)
    assert "rules.yaml" in str(e.value)


def test_scope_decides_which_scenes_a_rule_applies_to(book):
    s_anna, s_other = scene(book, S1), scene(book, "b1.ch03.s1")
    anna = rule(id="a", scope="character", target="anna")
    nobody = rule(id="n", scope="character", target="nobody")
    here = rule(id="h", scope="scene", target=S1)
    other_book = rule(id="o", scope="book", target="b2")
    disabled = rule(id="d", enabled=False)
    for r, expected in ((rule(), True), (anna, True), (nobody, False), (here, True), (other_book, False), (disabled, False), (rule(id="b", scope="book", target="b1"), True)):
        assert rules.applies(r, book, s_anna) is expected, r.id
    assert rules.applies(here, book, s_other) is False


# ── banned phrases: the mechanical checker ───────────────────────────────────

def phrase_ctx(book, **kw):
    rules.upsert(book, rule(id="p1", type="banned_phrase", phrase="harbour bell", **kw))
    return check_context(Project.open(book.root), scene(book), store.load_scenes(book))


TEXT = "She heard the harbour bell ring. " * 30


def test_a_blocking_phrase_rule_blocks_and_names_its_rule(book):
    report = check_scene(TEXT, phrase_ctx(book, severity="block"))
    hit = next(i for i in report.issues if i.code == "rule_phrase")
    assert hit.severity == "block" and hit.rule == "p1" and "rule p1" in hit.message and hit.start is not None
    assert hit in report.blocking


def test_a_warning_phrase_rule_warns_and_a_note_is_only_recorded(book):
    warn = check_scene(TEXT, phrase_ctx(book, severity="warn"))
    assert [i.severity for i in warn.issues if i.code == "rule_phrase"] == ["warn"] * 30 and not [i for i in warn.blocking if i.code == "rule_phrase"]
    note = check_scene(TEXT, phrase_ctx(book, severity="note"))
    assert {i.severity for i in note.issues if i.code == "rule_phrase"} == {"note"}
    assert note.score == check_scene(TEXT.replace("harbour bell", "church clock"), phrase_ctx(book, severity="note")).score  # a note costs nothing


def test_a_phrase_rule_that_applies_to_another_scene_is_not_checked(book):
    rules.upsert(book, rule(id="p2", type="banned_phrase", phrase="harbour bell", severity="block", scope="scene", target="b1.ch03.s1"))
    ctx = check_context(Project.open(book.root), scene(book), store.load_scenes(book))
    assert not [i for i in check_scene(TEXT, ctx).issues if i.code == "rule_phrase"]


def test_a_blocking_phrase_rule_is_revised_out_of_a_written_scene(book):
    rules.upsert(book, rule(id="no-bell", type="banned_phrase", phrase="harbour bell", severity="block"))
    from test_prose_qc import good
    bad = {S1: [good(S1, 1) + "\n\nThe harbour bell rang twice.", good(S1, 2) + "\n\nThe harbour bell rang twice."]}
    llm = RuleLLM(qc_rules(overrides=bad, revise=("Revise one passage of a scene", lambda m: between(user(m), "passage").replace("harbour bell", "church clock"))))
    go(Project.open(book.root), llm)
    final = scenefiles.final_path(book, S1).read_text()
    assert "harbour bell" not in final and "The church clock rang twice." in final
    r = review(book)
    assert any(i["rule"] == "no-bell" for rd in r["mechanical"].values() for i in rd["issues"])


# ── the briefing and the critic ─────────────────────────────────────────────

def test_style_and_voice_rules_go_into_the_briefing_and_the_scene_deps(book):
    rules.upsert(book, rule(example="The sky bled crimson."))
    rules.upsert(book, rule(id="anna-voice", type="character_voice", scope="character", target="anna", text="Anna never swears.", severity="block"))
    rules.upsert(book, rule(id="p", type="banned_phrase", phrase="grey eyes", severity="warn"))
    rules.upsert(book, rule(id="elsewhere", scope="scene", target="b1.ch04.s2", text="Only for chapter four."))
    b = build_briefing(Project.open(book.root), S1)
    text = b.text()
    assert "## The author's rules for this scene" in text and "SHOULD: No purple prose. Example: The sky bled crimson." in text
    assert "MUST (Anna Voss): Anna never swears." in text and "Only for chapter four" not in text
    assert "- grey eyes" in text.split("Phrases never to use")[1]
    assert any(t.startswith("rules@") for t in b.deps.style)


def test_changing_a_rule_makes_the_scenes_it_touches_stale_and_a_book_without_rules_is_unaffected(full):
    assert stale.scan(full).empty  # the rules panel adds nothing to a book that has no rules
    rules.upsert(full, rule(scope="scene", target=S1))
    found = stale.scan(full).scenes
    assert [s.scene for s in found] == [S1] and any(r.key == "style" for r in found[0].reasons)
    assert not found[0].needs_continuity  # a style rule is not a continuity matter
    rules.upsert(full, rule(id="hc", type="hard_constraint", text="Nobody ever lies.", scope="scene", target="b1.ch01.s2"))
    s2 = next(s for s in stale.scan(full).scenes if s.scene == "b1.ch01.s2")
    assert s2.needs_continuity and any(r.key == "bible" for r in s2.reasons)


def test_the_critic_is_given_the_rules_that_apply(book):
    rules.upsert(book, rule(id="must", severity="block", text="No adverbs of manner."))
    seen = []

    def spy(messages):
        seen.append(user(messages))
        return critic()(messages)

    go(Project.open(book.root), RuleLLM(qc_rules(critic=(CRITIC, spy))))
    assert "MUST: No adverbs of manner." in seen[0] and "caps the criterion" in seen[0]


def test_without_rules_the_critic_is_told_there_are_none(book):
    seen = []

    def spy(messages):
        seen.append(user(messages))
        return critic()(messages)

    go(Project.open(book.root), RuleLLM(qc_rules(critic=(CRITIC, spy))))
    assert "## The author's own rules for this scene\n\n(none)" in seen[0]


# ── hard constraints: the continuity check ──────────────────────────────────

def hc_llm(severity, answer=("yes", 0.95, "Nobody spoke.")):
    rules_ = [("Author's rule hc", answer)]
    return qc_rules(continuity=(CONTINUITY, continuity({"Author's rule hc": answer})))


def test_a_hard_constraint_is_asked_as_a_question_with_its_rule_id(book):
    rules.upsert(book, rule(id="hc", type="hard_constraint", text="Nobody ever lies.", severity="block"))
    seen = []

    def spy(messages):
        seen.append(user(messages))
        return continuity()(messages)

    go(Project.open(book.root), RuleLLM(qc_rules(continuity=(CONTINUITY, spy))))
    assert any("Author's rule hc: Nobody ever lies." in q for q in seen)


def test_a_blocking_constraint_that_is_broken_is_flagged_and_counted(book):
    rules.upsert(book, rule(id="hc", type="hard_constraint", text="Nobody ever lies.", severity="block"))
    # the scene text really contains "Nobody spoke."; the reviser leaves it alone, so the scene stays flagged
    go(Project.open(book.root), RuleLLM(qc_rules(continuity=(CONTINUITY, continuity({"Author's rule hc": ("yes", 0.95, "Nobody spoke.")})),
                                                  revise=("Revise one passage of a scene", lambda m: between(user(m), "passage")))))
    r = review(book)
    assert any(f.get("rule") == "hc" for f in r["continuity"]["flags"])
    assert next(s for s in rules.stats(Project.open(book.root)) if s["id"] == "hc")["fired"] >= 1


def test_a_warning_constraint_is_recorded_but_never_revised(book):
    rules.upsert(book, rule(id="hc", type="hard_constraint", text="Nobody ever lies.", severity="warn"))
    go(Project.open(book.root), RuleLLM(qc_rules(continuity=(CONTINUITY, continuity({"Author's rule hc": ("yes", 0.95, "Nobody spoke.")})))))
    r = review(book)
    assert r["continuity"]["flags"] == [] and r["continuity"]["unsure"][0]["rule"] == "hc"
    from bookforge.state import load_state
    assert load_state(book.state_path).items[S1].status == "accepted"


# ── hit counts and health ───────────────────────────────────────────────────

def test_stats_count_where_a_rule_fired_and_show_the_latest_hits(book):
    rules.upsert(book, rule(id="bell", type="banned_phrase", phrase="harbour bell", severity="warn"))
    rules.upsert(book, rule(id="voice", severity="note"))
    from test_prose_qc import good
    go(Project.open(book.root), RuleLLM(qc_rules(overrides={S1: [good(S1, 1) + "\n\nThe harbour bell rang.", good(S1, 2) + "\n\nThe harbour bell rang."]})))
    st = {s["id"]: s for s in rules.stats(Project.open(book.root))}
    assert st["bell"]["applicable"] == 8 and st["bell"]["written"] == 2 and st["bell"]["measured"] is True
    assert st["bell"]["fired"] >= 1 and st["bell"]["hits"][0]["scene"] == S1 and "harbour bell" in st["bell"]["hits"][0]["what"]
    assert st["voice"]["measured"] is False and st["voice"]["fired"] == 0


def test_health_flags_rules_that_never_fire_fire_constantly_or_contradict(full):
    rules.upsert(full, rule(id="never", type="banned_phrase", phrase="zzyzx", severity="warn"))
    rules.upsert(full, rule(id="always", type="banned_phrase", phrase="the", severity="warn"))
    rules.upsert(full, rule(id="dup", type="banned_phrase", phrase="ZZYZX", severity="warn"))
    rules.upsert(full, rule(id="ex", example="He said zzyzx twice."))
    (full.root / "style" / "samples" / "s.md").write_text("She waved at the harbour.")
    rules.upsert(full, rule(id="harbour", type="banned_phrase", phrase="harbour", severity="warn"))
    # a review per scene is what the counts are read from
    for s in store.load_scenes(full):
        from bookforge.qc.mechanical import check_scene as chk
        text = scenefiles.final_path(full, s.id).read_text()
        ctx = check_context(full, s, store.load_scenes(full))
        path = scenefiles.review_path(full, s.id)
        data = json.loads(path.read_text())
        data["final_mechanical"] = chk(text, ctx).to_dict()
        path.write_text(json.dumps(data))
    problems = {(p["rule"], p["problem"]) for p in rules.health(full)}
    assert ("never", "never_fires") in problems and ("always", "fires_constantly") in problems
    assert ("harbour", "contradicts") in problems and ("never", "contradicts") in problems and ("dup", "duplicate") in problems
