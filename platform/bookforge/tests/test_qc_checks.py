import json

import pytest

from bookforge.bible import store
from bookforge.errors import LayerError
from bookforge.layers.runner import StepContext
from bookforge.llm import LLMError
from bookforge.project import Project
from bookforge.qc.continuity import build_questions, check_continuity
from bookforge.qc.critic import CRITERIA, critic_flags, rubric_line, run_critic
from bookforge.qc.decide import Question, ask_questions
from bookforge.qc.judge import choose_draft, judge_pair
from bookforge.qc.mechanical import check_scene
from conftest import RuleLLM
from prose_fakes import prose
from qc_fakes import CONTINUITY, CRITIC, JUDGE, continuity, critic, judge
from structure_fakes import ready, rules
from bookforge.layers import HANDLERS
from bookforge.layers.runner import run

TEXT = prose(0, 16)


@pytest.fixture
def book(project):
    p = ready(project)
    assert run(p, RuleLLM(rules()), HANDLERS).stopped == "checkpoint"
    return Project.open(p.root)


def ctx_for(project, llm):
    return StepContext(project, "prose", llm)


def scene_of(project, sid):
    return next(s for s in store.load_scenes(project) if s.id == sid)


# ── yes/no questions ────────────────────────────────────────────────────────

def qs(n=3):
    return [Question(f"q{i}", "contradiction", f"Fact {i}") for i in range(1, n + 1)]


def reply_for(answers):
    return json.dumps({"answers": answers})


def test_answers_are_read_with_confidence_and_verified_evidence(book):
    text = "Anna put her left hand on the rail and did not look back at him."
    llm = RuleLLM([(CONTINUITY, reply_for([
        {"id": "q1", "relation": "contradicts", "confidence": 0.8, "evidence": "left hand on the rail"},
        {"id": "q2", "relation": "contradicts", "confidence": 0.9, "evidence": "words that are not in the text"},
        {"id": "q3", "relation": "silent", "confidence": 0.7}]))])
    a = ask_questions(ctx_for(book, llm), "t", "scene", text, qs(), batch_size=8)
    assert [(x.yes, x.confidence, x.verified) for x in a] == [(True, 0.8, True), (True, 0.9, False), (False, 0.7, False)]


def test_questions_go_in_batches(book):
    def reply(messages):
        import re
        ids = re.findall(r"^(q\d+) \[", messages[1]["content"], re.MULTILINE)
        return reply_for([{"id": i, "relation": "silent", "confidence": 0.9} for i in ids])

    llm = RuleLLM([(CONTINUITY, reply)])
    answers = ask_questions(ctx_for(book, llm), "t", "scene", TEXT, qs(5), batch_size=2)
    assert len(llm.calls) == 3 and [a.id for a in answers] == [f"q{i}" for i in range(1, 6)]


def test_incomplete_answers_are_sent_back_and_then_fail(book):
    partial = reply_for([{"id": "q1", "relation": "silent", "confidence": 0.9}])
    llm = RuleLLM([(CONTINUITY, partial)])
    with pytest.raises(LayerError, match="no answer for q2"):
        ask_questions(ctx_for(book, llm), "t", "scene", TEXT, qs(2), 8)
    assert len(llm.calls) == 1 + book.config.qc.max_revision_rounds
    bad = RuleLLM([(CONTINUITY, reply_for([{"id": "q1", "relation": "maybe", "confidence": 2}, {"id": "q2", "relation": "silent", "confidence": 0.5}]))])
    with pytest.raises(LayerError, match="'relation' must be one of: contradicts, agrees, silent"):
        ask_questions(ctx_for(book, bad), "t", "scene", TEXT, qs(2), 8)


# ── continuity ──────────────────────────────────────────────────────────────

def test_questions_cover_states_obligations_the_cast_and_rules(book):
    questions, facts = build_questions(book, scene_of(book, "b1.ch04.s1"), store.load_scenes(book))
    kinds = [(q.kind, q.text) for q in questions]
    assert ("contradiction", "Anna Voss (physical): healed; scar remains") not in kinds  # it begins in this scene: the scene may start before it
    assert ("shown", "Anna Voss: healed; scar remains") in kinds  # a must_show change that begins in this scene
    assert ("contradiction", "Anna Voss: grey eyes") in kinds and ("contradiction", "World rule: each name crossed out costs a year of memory") in kinds
    assert not any("Jonas" in t and "knows" in t and k == "shown" for k, t in kinds)
    assert len({q.id for q in questions}) == len(questions)


def test_the_question_count_is_capped(book):
    book.config.qc.continuity_max_questions = 3
    questions, _ = build_questions(book, scene_of(book, "b1.ch04.s1"), store.load_scenes(book))
    assert len(questions) == 3


def test_a_clean_scene_has_no_flags(book):
    rep = check_continuity(ctx_for(book, RuleLLM([(CONTINUITY, continuity())])), scene_of(book, "b1.ch04.s1"), store.load_scenes(book), TEXT)
    assert rep.flags == [] and rep.unsure == [] and rep.questions > 5 and rep.error is None


def test_a_verified_contradiction_is_a_fixable_flag(book):
    evidence = " ".join(TEXT.split()[:6])
    llm = RuleLLM([(CONTINUITY, continuity({"grey eyes": ("yes", 0.9, evidence)}))])
    rep = check_continuity(ctx_for(book, llm), scene_of(book, "b1.ch04.s1"), store.load_scenes(book), TEXT)
    [flag] = rep.flags
    assert flag.kind == "contradiction" and flag.fixable and flag.evidence == evidence and flag.p == 0.9
    assert "grey eyes" in flag.message()


def test_a_contradiction_without_quotable_evidence_is_only_unsure(book):
    llm = RuleLLM([(CONTINUITY, continuity({"grey eyes": ("yes", 0.9, "invented words")}))])
    rep = check_continuity(ctx_for(book, llm), scene_of(book, "b1.ch04.s1"), store.load_scenes(book), TEXT)
    assert rep.flags == [] and len(rep.unsure) == 1 and rep.unsure[0]["answer"] == "yes"


def test_a_hesitant_no_is_unsure_and_a_confident_no_is_not(book):
    llm = RuleLLM([(CONTINUITY, continuity({"grey eyes": ("no", 0.6, "")}))])  # P(contradiction) = 0.4 > 0.3
    rep = check_continuity(ctx_for(book, llm), scene_of(book, "b1.ch04.s1"), store.load_scenes(book), TEXT)
    assert rep.flags == [] and [u["question"] for u in rep.unsure] == ["Anna Voss: grey eyes"]
    llm2 = RuleLLM([(CONTINUITY, continuity({"grey eyes": ("no", 0.8, "")}))])  # 0.2: fine
    assert check_continuity(ctx_for(book, llm2), scene_of(book, "b1.ch04.s1"), store.load_scenes(book), TEXT).unsure == []


def test_the_threshold_comes_from_the_config(book):
    book.config.qc.continuity_flag_threshold = 0.5
    llm = RuleLLM([(CONTINUITY, continuity({"grey eyes": ("no", 0.6, "")}))])
    assert check_continuity(ctx_for(book, llm), scene_of(book, "b1.ch04.s1"), store.load_scenes(book), TEXT).unsure == []


def test_a_change_that_is_not_shown_is_an_obligation_a_passage_can_repair(book):
    llm = RuleLLM([(CONTINUITY, continuity({"Anna Voss: healed; scar remains": ("no", 0.9, "")}))])
    rep = check_continuity(ctx_for(book, llm), scene_of(book, "b1.ch04.s1"), store.load_scenes(book), TEXT)
    [flag] = rep.flags
    assert flag.kind == "obligation" and flag.fixable and "does not show this on the page" in flag.message()
    shown_unsure = RuleLLM([(CONTINUITY, continuity({"Anna Voss: healed; scar remains": ("yes", 0.6, "")}))])  # P(not shown) = 0.4
    assert check_continuity(ctx_for(book, shown_unsure), scene_of(book, "b1.ch04.s1"), store.load_scenes(book), TEXT).flags[0].kind == "obligation"


def test_a_failed_check_is_reported_and_does_not_raise(book):
    def offline(_):
        raise LLMError("critic offline")

    rep = check_continuity(ctx_for(book, RuleLLM([(CONTINUITY, offline)])), scene_of(book, "b1.ch04.s1"), store.load_scenes(book), TEXT)
    assert "critic offline" in rep.error and rep.flags == []


# ── the critic ──────────────────────────────────────────────────────────────

def test_the_critic_returns_scores_and_three_real_quotes(book):
    rep = run_critic(ctx_for(book, RuleLLM([(CRITIC, critic({"pacing": 2}))])), scene_of(book, "b1.ch01.s1"), TEXT)
    assert set(rep.scores) == set(CRITERIA) and rep.scores["pacing"] == 2 and rep.lowest == 2
    assert len(rep.weakest) == 3 and all(w.quote in " ".join(TEXT.split()) for w in rep.weakest)
    assert rep.needs_work(3) and not rep.needs_work(2) and rep.error is None
    assert rep.to_dict()["lowest"] == 2


@pytest.mark.parametrize("mutate,needle", [
    (lambda d: d["scores"].pop("pacing"), "scores.pacing"),
    (lambda d: d["scores"].update(stakes=6), "scores.stakes"),
    (lambda d: d["scores"].update(stakes=3.5), "scores.stakes"),
    (lambda d: d["weakest"].pop(), "exactly three"),
    (lambda d: d["weakest"][0].update(quote="this quote was invented by the critic entirely"), "not in the scene"),
    (lambda d: d["weakest"][0].update(quote="too short"), "at least 6 words"),
    (lambda d: d["weakest"][0].update(criterion="plot"), "criterion must be one of"),
])
def test_bad_critiques_are_sent_back_and_then_dropped_without_blocking(book, mutate, needle):
    good = json.loads(critic()([{"role": "user", "content": f"<scene>\n{TEXT}\n</scene>"}]))
    mutate(good)
    llm = RuleLLM([(CRITIC, json.dumps(good))])
    rep = run_critic(ctx_for(book, llm), scene_of(book, "b1.ch01.s1"), TEXT)
    assert rep.error and needle in rep.error and rep.scores == {} and not rep.needs_work(3)
    assert len(llm.calls) == 1 + book.config.qc.max_revision_rounds


def test_a_bad_critique_can_be_corrected(book):
    first = json.dumps({"scores": {}, "weakest": []})
    good = critic()

    def reply(messages):
        return first if len(messages) == 2 else good(messages)

    rep = run_critic(ctx_for(book, RuleLLM([(CRITIC, reply)])), scene_of(book, "b1.ch01.s1"), TEXT)
    assert rep.error is None and rep.scores["stakes"] == 4


def test_the_critic_is_not_given_the_bible(book):
    llm = RuleLLM([(CRITIC, critic())])
    run_critic(ctx_for(book, llm), scene_of(book, "b1.ch01.s1"), TEXT)
    prompt = llm.calls[0]["messages"][1]["content"]
    assert "## Rubric" in prompt and "Beats, in order" in prompt and "grey eyes" not in prompt and "always foggy" not in prompt


def test_flags_carry_the_rubric_line_and_the_rubric_can_be_reworded(book):
    rep = run_critic(ctx_for(book, RuleLLM([(CRITIC, critic({"pacing": 1}))])), scene_of(book, "b1.ch01.s1"), TEXT)
    flags = critic_flags(book, rep)
    pacing = next(f for f in flags if f.criterion == "pacing")
    assert pacing.source == "critic" and pacing.quote and "whether the scene moves at the right speed" in pacing.message
    override = book.root / "workbench" / "prompts"
    override.mkdir(parents=True)
    (override / "critic_rubric.md").write_text("- pacing: MY OWN WORDING for pacing\n")
    assert rubric_line(book, "pacing") == "MY OWN WORDING for pacing" and rubric_line(book, "stakes") == ""


# ── the judge ───────────────────────────────────────────────────────────────

A, B = TEXT + " Alpha ending.", TEXT + " Beta ending."


def test_a_pair_is_decided_when_both_orders_agree(book):
    winner, rec = judge_pair(ctx_for(book, RuleLLM([(JUDGE, judge("Beta"))])), scene_of(book, "b1.ch01.s1"), "draft-1", A, "draft-2", B)
    assert winner == "draft-2" and rec["run1"] == rec["run2"] == "draft-2"


def test_a_pair_is_a_tie_when_the_order_decides(book):
    always_a = RuleLLM([(JUDGE, json.dumps({"winner": "A", "reason": "r"}))])  # prefers whichever is shown first
    winner, rec = judge_pair(ctx_for(book, always_a), scene_of(book, "b1.ch01.s1"), "draft-1", A, "draft-2", B)
    assert winner is None and rec["run1"] == "draft-1" and rec["run2"] == "draft-2" and len(always_a.calls) == 2


def test_the_drafts_are_shown_in_both_orders(book):
    llm = RuleLLM([(JUDGE, judge("Beta"))])
    judge_pair(ctx_for(book, llm), scene_of(book, "b1.ch01.s1"), "draft-1", A, "draft-2", B)
    first, second = (c["messages"][1]["content"] for c in llm.calls)
    assert first.index("Alpha") < first.index("Beta") and second.index("Beta") < second.index("Alpha")


def test_the_judge_chooses_the_draft_with_most_wins_and_breaks_ties_by_score(book):
    from bookforge.qc.mechanical import CheckContext
    reports = {n: check_scene(t, CheckContext(scene_words=(50, 900))) for n, t in {"draft-1": A, "draft-2": B}.items()}
    res = choose_draft(ctx_for(book, RuleLLM([(JUDGE, judge("Beta"))])), scene_of(book, "b1.ch01.s1"), {"draft-1": A, "draft-2": B}, reports)
    assert res.winner == "draft-2" and res.wins == {"draft-1": 0, "draft-2": 1} and res.error is None
    tie = choose_draft(ctx_for(book, RuleLLM([(JUDGE, json.dumps({"winner": "A", "reason": "r"}))])), scene_of(book, "b1.ch01.s1"),
                       {"draft-1": A, "draft-2": B}, reports)
    assert tie.winner == "draft-1"  # equal wins and scores: the first draft


def test_three_drafts_are_judged_pairwise(book):
    drafts = {"draft-1": TEXT + " One.", "draft-2": TEXT + " Two.", "draft-3": TEXT + " Three."}
    from bookforge.qc.mechanical import CheckContext
    reports = {n: check_scene(t, CheckContext(scene_words=(50, 900))) for n, t in drafts.items()}
    llm = RuleLLM([(JUDGE, judge("Three"))])
    res = choose_draft(ctx_for(book, llm), scene_of(book, "b1.ch01.s1"), drafts, reports)
    assert res.winner == "draft-3" and res.wins["draft-3"] == 2 and len(llm.calls) == 6  # 3 pairs, each both ways


def test_a_judge_that_fails_falls_back_to_the_mechanical_score(book):
    def offline(_):
        raise LLMError("offline")

    from bookforge.qc.mechanical import CheckContext
    drafts = {"draft-1": A + " a testament to nothing", "draft-2": B}
    reports = {n: check_scene(t, CheckContext(scene_words=(50, 900), banned=["a testament to"])) for n, t in drafts.items()}
    res = choose_draft(ctx_for(book, RuleLLM([(JUDGE, offline)])), scene_of(book, "b1.ch01.s1"), drafts, reports)
    assert res.winner == "draft-2" and "offline" in res.error


def test_a_scene_is_acceptable_exactly_when_nothing_is_left_unresolved():
    from bookforge.qc.scene import SceneQC
    assert SceneQC("text", "draft-1").accepted
    assert not SceneQC("text", "draft-1", reasons=["the critic scored pacing 2 (minimum 3)"]).accepted


# ── an approved decision clashing with a scene is recorded, not flagged ─────

def test_a_clash_with_an_approved_decision_is_unsure_and_never_a_flag(book):
    from bookforge import ops
    from bookforge.research.notes import stores_for
    n = stores_for(book)["book"].add_need(layer="synopsis", question="How do locks work?", stance="invent", rule="Locks fail if forced.", status="proposed")
    ops.decide_need(book, n.id, approve=True)
    evidence = " ".join(TEXT.split()[:6])
    llm = RuleLLM([(CONTINUITY, continuity({"Author's decision": ("yes", 0.95, evidence)}))])
    rep = check_continuity(ctx_for(book, llm), scene_of(book, "b1.ch04.s1"), store.load_scenes(book), TEXT)
    assert rep.flags == []
    assert [u["question"] for u in rep.unsure] == [f"Author's decision about this world ({n.id}): Locks fail if forced."]


# ── an answer that AGREES with the fact is never a flag (found on the first prose run) ──

def _text_with(*sentences):
    return " ".join(sentences) + " " + TEXT


def test_quoting_words_that_confirm_a_fact_is_agreement_not_a_flag(book):
    # The real log: "born on a Dominion transport vessel" answered 'yes' with the quote "the transit vessel that had been his birthplace",
    # and "abandoned mining tunnels on Erebus-7" with the fact itself as the quote. Every one flagged the scene at confidence 1.0.
    text = _text_with("Eli navigated the cramped quarters of the transit vessel that had been his birthplace.",
                      "The Lower Sectors were abandoned mining tunnels on Erebus-7.")
    quotes = {"Anna Voss: grey eyes": ("agrees", 1.0, "the transit vessel that had been his birthplace"),
              "World rule": ("agrees", 1.0, "abandoned mining tunnels on Erebus-7")}
    llm = RuleLLM([(CONTINUITY, continuity(quotes))])
    rep = check_continuity(ctx_for(book, llm), scene_of(book, "b1.ch04.s1"), store.load_scenes(book), text)
    assert rep.flags == [] and rep.unsure == [] and rep.error is None


def test_a_scene_that_does_not_touch_a_fact_is_silent_and_never_flags(book):
    llm = RuleLLM([(CONTINUITY, continuity({"grey eyes": ("silent", 1.0, TEXT.split(".")[0])}))])
    rep = check_continuity(ctx_for(book, llm), scene_of(book, "b1.ch04.s1"), store.load_scenes(book), TEXT)
    assert rep.flags == []


def test_only_a_contradiction_with_a_real_quote_flags_the_scene(book):
    evidence = " ".join(TEXT.split()[:6])
    llm = RuleLLM([(CONTINUITY, continuity({"grey eyes": ("contradicts", 0.9, evidence)}))])
    rep = check_continuity(ctx_for(book, llm), scene_of(book, "b1.ch04.s1"), store.load_scenes(book), TEXT)
    [flag] = rep.flags
    assert flag.kind == "contradiction" and flag.fixable and flag.evidence == evidence and "grey eyes" in flag.question


def _confirm_reply(conflict, log=None):
    def reply(messages):
        if log is not None:
            log.append(messages[-1]["content"])
        return json.dumps({"fact_says": "late 20s", "text_says": "twenty-eight years", "conflict": conflict, "confidence": 0.9})
    return reply


def _flagged(book, confirm, **cfg):
    evidence = " ".join(TEXT.split()[:6])
    llm = RuleLLM([(CONTINUITY, continuity({"grey eyes": ("contradicts", 0.9, evidence)})), ("A reader flagged", confirm)])
    book.config.qc.confirm_contradictions = cfg.get("on", True)
    return llm, check_continuity(ctx_for(book, llm), scene_of(book, "b1.ch04.s1"), store.load_scenes(book), TEXT)


def test_a_contradiction_the_second_check_does_not_confirm_is_only_unsure(book):
    log = []
    llm, rep = _flagged(book, _confirm_reply(False, log))
    assert rep.flags == []
    [u] = rep.unsure
    assert u["confirmed"] is False and u["fact_says"] == "late 20s" and u["text_says"] == "twenty-eight years"
    assert len(log) == 1 and "grey eyes" in log[0] and TEXT.split(".")[0] in log[0]


def test_a_confirmed_contradiction_stays_a_flag_with_the_compared_values(book):
    llm, rep = _flagged(book, _confirm_reply(True))
    [flag] = rep.flags
    assert flag.fact_says == "late 20s" and flag.text_says == "twenty-eight years"


def test_a_failed_second_check_keeps_the_flag(book):
    llm, rep = _flagged(book, "not json at all")
    assert len(rep.flags) == 1


def test_the_second_check_can_be_switched_off(book):
    llm, rep = _flagged(book, _confirm_reply(False), on=False)
    assert len(rep.flags) == 1 and not any("A reader flagged" in c["messages"][-1]["content"] for c in llm.calls)


def test_no_flag_means_no_second_call(book):
    llm = RuleLLM([(CONTINUITY, continuity())])
    check_continuity(ctx_for(book, llm), scene_of(book, "b1.ch04.s1"), store.load_scenes(book), TEXT)
    assert len(llm.calls) == 1


def test_a_shown_question_cannot_be_answered_with_a_contradiction_relation(book):
    from bookforge.qc.decide import Question
    q = [Question("q1", "shown", "Anna: healed")]
    bad = RuleLLM([(CONTINUITY, reply_for([{"id": "q1", "relation": "contradicts", "confidence": 0.9}]))])
    with pytest.raises(LayerError, match="'relation' must be one of: shown, not_shown"):
        ask_questions(ctx_for(book, bad), "t", "scene", TEXT, q, 8)


def test_the_continuity_prompt_names_the_three_relations_and_says_confirming_words_agree():
    from bookforge import prompts
    text = (prompts.PROMPT_DIR / "continuity.md").read_text()
    for needle in ('"contradicts"', '"agrees"', '"silent"', '"shown"', '"not_shown"', "never \"contradicts\"", "tendencies"):
        assert needle in text, needle
