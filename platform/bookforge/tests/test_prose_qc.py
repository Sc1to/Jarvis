import json

import pytest
import yaml
from typer.testing import CliRunner

from bookforge import cli, scenefiles, vcs
from bookforge.bible import store
from bookforge.layers import HANDLERS
from bookforge.layers.runner import run
from bookforge.llm import LLMError
from bookforge.project import Project
from bookforge.state import load_state
from conftest import RuleLLM
from prose_fakes import prose
from qc_fakes import CONFIRM, CONTINUITY, CRITIC, EXTRACT, INSERT, JUDGE, REVISE, continuity, critic, extractor, inserter, judge, reviser
from structure_fakes import SMALL_CONFIG, ready, rules
from test_prose import BANNED, SCENES, SUMMARY, good, prose_rules

QC_CONFIG = SMALL_CONFIG.replace("research:", "  prose: {words: [100, 600], drafts: 2}\nresearch:")
SID = "b1.ch01.s1"
QC_ROUNDS = 2  # qc.max_revision_rounds in the default config
COMMON = "She remembered the grey eyes of the man on the quay."


@pytest.fixture
def book(project):
    p = ready(project)
    assert run(p, RuleLLM(rules()), HANDLERS).stopped == "checkpoint"
    p.state.approve_checkpoint("structure")
    p.save_state()
    (p.root / "config.yaml").write_text(QC_CONFIG)
    vcs.commit(p.root, "test setup")
    return Project.open(p.root)


def qc_rules(**kw):
    """Scene replies from test_prose plus a clean reply for every quality-control call (override any via kw)."""
    over = kw.pop("overrides", None)
    base = {"judge": (JUDGE, judge("Zebra")), "continuity": (CONTINUITY, continuity()), "critic": (CRITIC, critic()),
            "revise": (REVISE, reviser({"a testament to": "proof of"})), "extract": (EXTRACT, extractor()), "insert": (INSERT, inserter())}
    for k, v in kw.items():
        base[k] = v
    return prose_rules(over) + list(base.values())


KINDS = (("draft", "Write the scene described below"), ("judge", JUDGE), ("continuity", CONTINUITY), ("critic", CRITIC),
         ("summary", "Summarise the scene below"), ("extract", EXTRACT), ("revise", REVISE), ("insert", INSERT), ("confirm", CONFIRM))


def kinds(llm):
    """The kind of each call, in order."""
    out = []
    for c in llm.calls:
        first = next(m["content"] for m in c["messages"] if m["role"] == "user")
        out.append(next(name for name, marker in KINDS if marker in first))
    return out


def first_scene(llm):
    """The calls made for the first scene: everything up to and including its extraction."""
    k = kinds(llm)
    return k[: k.index("extract") + 1]


def files_of(project, subject):
    sha = next(line.split("\0")[0] for line in git(project, "log", "--format=%H%x00%s").splitlines() if line.endswith("\0" + subject))
    return git(project, "show", "--name-only", "--format=", sha).split()


def go(project, llm, until="prose"):
    return run(project, llm, HANDLERS, until=until)


def calls(llm, marker):
    return llm.calls_matching(marker)


def review(project, sid=SID):
    return json.loads(scenefiles.review_path(project, sid).read_text())


def git(project, *args):
    import subprocess
    return subprocess.run(["git", "-C", str(project.root), *args], capture_output=True, text=True).stdout


# ── the whole sequence ──────────────────────────────────────────────────────

def test_a_scene_goes_through_every_layer_in_order(book):
    llm = RuleLLM(qc_rules())
    go(book, llm)
    seq = first_scene(llm)
    assert seq[:4] == ["draft", "draft", "judge", "judge"]
    n = seq.count("continuity")
    assert n >= 1 and seq[4:4 + n] == ["continuity"] * n and seq[4 + n:] == ["critic", "summary", "extract"]


def _check_calls(llm):
    """(kind, role, temperature option) of each quality-control call."""
    return [(k, c["role"], c["options"].get("temperature")) for k, c in zip(kinds(llm), llm.calls) if k in ("judge", "continuity", "critic")]


def test_the_checks_run_on_the_writer_model_by_default(book):
    llm = RuleLLM(qc_rules())
    go(book, llm)
    checks = _check_calls(llm)
    assert {k for k, _, _ in checks} == {"judge", "continuity", "critic"}
    assert {role for _, role, _ in checks} == {"writer"}  # one model for the whole prose layer: nothing to swap
    assert {t for _, _, t in checks} == {0.2}  # judged at qc.temperature, not at a drafting temperature
    assert {c["role"] for k, c in zip(kinds(llm), llm.calls) if k == "draft"} == {"writer"}


def test_the_checks_can_use_the_critic_model(book):
    book.config.qc.model = "critic"
    llm = RuleLLM(qc_rules())
    go(book, llm)
    checks = _check_calls(llm)
    assert {role for _, role, _ in checks} == {"critic"} and {t for _, _, t in checks} == {None}  # the critic's own temperature applies


def test_the_review_records_every_layer(book):
    over = {SID: [good(SID, 1), good(SID, 2) + " Zebra finale."]}
    llm = RuleLLM(qc_rules(overrides=over))
    go(book, llm)
    r = review(book)
    assert r["judge"]["wins"] == {"draft-1": 0, "draft-2": 1} and r["chosen"] == "draft-2" and r["revised"] is False
    assert len(r["rounds"]) == 1 and r["rounds"][0]["critic_lowest"] == 4 and r["rounds"][0]["revisions"] == []
    assert r["continuity"]["flags"] == [] and r["continuity"]["questions"] >= 5  # a state that begins in the scene has no fixed-fact question
    assert r["critic"]["scores"]["stakes"] == 4 and len(r["critic"]["weakest"]) == 3
    assert r["unresolved"] == [] and r["extraction"]["observations"] == 1 and r["summary_source"] == "model"
    assert len(calls(llm, JUDGE)) >= 2 and len(calls(llm, CRITIC)) >= 1


def test_the_judge_only_runs_when_there_is_a_choice(book):
    one_bad = {SID: [good(SID, 1) + " " + BANNED, good(SID, 2)]}
    llm = RuleLLM(qc_rules(overrides=one_bad, revise=(REVISE, reviser({}))))
    go(book, llm)
    assert "judge" not in first_scene(llm)  # only one draft was free of blocking problems
    r = review(book)
    assert r["chosen"] == "draft-2" and r["judge"] is None


def test_extraction_writes_the_scene_file_and_the_tracks(book):
    go(book, RuleLLM(qc_rules()))
    ex = yaml.safe_load(scenefiles.extracted_path(book, SID).read_text())
    assert ex["scene"] == SID and ex["observations"][0]["track"] == "jonas-knows" and ex["gaps"] == []
    jonas = next(t for t in store.load_tracks(book) if t.id == "jonas-knows")
    assert jonas.observed and jonas.observed[0]["at"] == SID and jonas.observed[0]["matches_plan"] is True
    files = files_of(book, f"{SID}: drafted, checked, accepted")
    assert "bible/tracks.yaml" in files and "books/b1/scenes/ch01/s1/extracted.yaml" in files and "books/b1/scenes/ch01/s1/final.md" in files


def test_a_gap_between_plan_and_prose_is_reported_but_does_not_block(book):
    llm = RuleLLM(qc_rules(extract=(EXTRACT, extractor(gap="jonas-knows"))))
    go(book, llm)
    assert load_state(book.state_path).items[SID].status == "accepted"
    assert "gap(s) between plan and prose" in load_state(book.state_path).items[SID].note
    assert review(book)["extraction"]["gaps"][0]["track"] == "jonas-knows"


# ── revision ────────────────────────────────────────────────────────────────

def test_a_banned_phrase_is_revised_in_its_paragraph_and_the_scene_is_accepted(book):
    bad = good(SID, 1) + " " + BANNED
    log = []
    llm = RuleLLM(qc_rules(overrides={SID: [bad, bad]}, revise=(REVISE, reviser({"a testament to": "proof of"}, log))))
    go(book, llm)
    final = scenefiles.final_path(book, SID).read_text()
    assert "testament" not in final and "proof of her own stubbornness, proof of everything." in final
    r = review(book)
    assert r["revised"] is True and r["rounds"][0]["revisions"][0]["mode"] == "rewrite" and r["rounds"][0]["mechanical_blocking"]
    assert r["rounds"][1]["mechanical_blocking"] == [] and len(r["rounds"]) == 2
    assert len(log) == 1 and "banned phrase: 'a testament to'" in log[0]["prompt"]
    assert scenefiles.draft_path(book, SID, 1).read_text().count("testament") == 2  # the drafts are kept as written
    assert scenefiles.summary_path(book, SID).exists() and load_state(book.state_path).items[SID].status == "accepted"


def test_only_the_paragraph_with_the_problem_changes(book):
    bad = good(SID, 1) + " " + BANNED
    go(book, RuleLLM(qc_rules(overrides={SID: [bad, bad]})))
    before = [p for p in bad.split("\n\n")]
    after = scenefiles.final_path(book, SID).read_text().strip().split("\n\n")
    assert len(before) == len(after) and before[:-1] == after[:-1] and before[-1] != after[-1]


def test_a_contradiction_is_revised_and_checked_again(book):
    drafts = [good(SID, 1) + " " + COMMON, good(SID, 2) + " " + COMMON]
    seen = {"n": 0}
    first = continuity({"grey eyes": ("yes", 0.9, COMMON)})
    clean = continuity()

    def reply(messages):
        seen["n"] += 1
        return first(messages) if seen["n"] == 1 else clean(messages)

    llm = RuleLLM(qc_rules(overrides={SID: drafts}, continuity=(CONTINUITY, reply),
                           revise=(REVISE, reviser({"grey eyes": "tired eyes"}))))
    go(book, llm)
    assert "tired eyes" in scenefiles.final_path(book, SID).read_text() and "grey eyes" not in scenefiles.final_path(book, SID).read_text()
    r = review(book)
    assert [len(x["continuity_flags"]) for x in r["rounds"]] == [1, 0] and r["unresolved"] == []


def test_a_missing_must_show_change_gets_a_passage_inserted_and_is_flagged_if_the_check_still_says_no(book):
    go(book, RuleLLM(prose_rules() + [(JUDGE, judge("Zebra")), (CONTINUITY, continuity()), (CRITIC, critic()),
                                       (EXTRACT, extractor()), (REVISE, reviser({}))]), until="prose")
    p = Project.open(book.root)
    p.state.approve_checkpoint("voice")
    p.save_state()
    sid = "b1.ch02.s2"  # where the wound begins and has to be shown
    log = []
    llm = RuleLLM(qc_rules(continuity=(CONTINUITY, continuity({"Anna Voss: deep cut": ("no", 0.9, "")})), insert=(INSERT, inserter(log=log))))
    summary = go(Project.open(book.root), llm)
    assert summary.stopped == "failed" and sid in summary.detail
    r = review(book, sid)
    assert any("does not show this on the page" in b for b in r["blocking"])  # the check kept saying no
    assert [m["mode"] for rd in r["rounds"] for m in rd["revisions"]] == ["insert", "insert"]  # but a passage was inserted each round
    assert "Anna Voss: deep cut" in log[0] and "50 to 150 words" in log[0]
    assert not scenefiles.final_path(book, sid).exists() and load_state(book.state_path).items[sid].status == "flagged"
    assert load_state(book.state_path).items["b1.ch03.s1"].status == "accepted"  # the rest went on


def test_an_inserted_passage_that_shows_the_change_makes_the_scene_pass(book):
    go(book, RuleLLM(prose_rules() + [(JUDGE, judge("Zebra")), (CONTINUITY, continuity()), (CRITIC, critic()),
                                       (EXTRACT, extractor()), (REVISE, reviser({}))]), until="prose")
    p = Project.open(book.root)
    p.state.approve_checkpoint("voice")
    p.save_state()
    sid = "b1.ch02.s2"
    inserted = []

    def answers(messages):
        shown = "She felt the cut open" in messages[-1]["content"]  # the scene now contains the inserted passage
        return continuity({} if shown else {"Anna Voss: deep cut": ("no", 0.9, "")})(messages)

    llm = RuleLLM(qc_rules(continuity=(CONTINUITY, answers), insert=(INSERT, inserter(after=2, log=inserted))))
    summary = go(Project.open(book.root), llm)
    assert summary.stopped != "failed", summary.detail
    assert load_state(book.state_path).items[sid].status == "accepted" and len(inserted) == 1
    assert "She felt the cut open on her shoulder" in scenefiles.final_path(book, sid).read_text()


# ── the critic ──────────────────────────────────────────────────────────────

def test_low_scores_revise_the_weakest_lines_and_the_critic_runs_again(book):
    log = []
    llm = RuleLLM(qc_rules(critic=(CRITIC, critic([{"show_dont_tell": 2}, {"show_dont_tell": 4}])), revise=(REVISE, reviser({" the ": " THE "}, log))))
    go(book, llm)
    r = review(book)
    assert [x["critic_lowest"] for x in r["rounds"]] == [2, 4] and r["unresolved"] == []
    assert first_scene(llm).count("critic") == 2 and first_scene(llm).count("revise") >= 1
    assert log and all("criterion" in l["prompt"] for l in log)
    assert "whether feelings and facts are conveyed through action" in " ".join(l["prompt"] for l in log)  # the rubric line travels with the flag
    assert load_state(book.state_path).items[SID].status == "accepted"


def test_the_critic_is_not_asked_again_when_its_first_scores_passed(book):
    llm = RuleLLM(qc_rules())
    go(book, llm)
    assert len(r_rounds(book)) == 1
    assert len(calls(llm, CRITIC)) == 2  # once per scene of chapter 1, never twice for the same text


def r_rounds(book):
    return review(book)["rounds"]


def test_scores_that_stay_low_flag_the_scene_after_two_rounds(book):
    llm = RuleLLM(qc_rules(critic=(CRITIC, critic({"pacing": 2})), revise=(REVISE, reviser({" the ": " THE "}))))
    summary = go(book, llm)
    r = review(book)
    assert [x["critic_lowest"] for x in r["rounds"]] == [2, 2, 2] and len([x for x in r["rounds"] if x["revisions"]]) == 2
    assert any("the critic scored pacing 2 (minimum 3)" in b for b in r["blocking"])
    assert load_state(book.state_path).items[SID].status == "flagged" and summary.stopped == "checkpoint"
    assert scenefiles.revised_path(book, SID).exists() and scenefiles.best_text(book, SID) == scenefiles.revised_path(book, SID).read_text()
    assert " THE " in scenefiles.revised_path(book, SID).read_text()
    assert not scenefiles.final_path(book, SID).exists()


def test_the_critic_waits_for_the_cheap_checks(book):
    bad = good(SID, 1) + " " + BANNED
    llm = RuleLLM(qc_rules(overrides={SID: [bad, bad]}, revise=(REVISE, reviser({"unrelated": "x"}))))  # never fixes it
    go(book, llm)
    r = review(book)
    assert all(x["critic_lowest"] is None for x in r["rounds"]) and r["continuity"] is None
    assert any("banned phrase" in b for b in r["blocking"]) and "revision_error" in r["rounds"][0]
    assert load_state(book.state_path).items[SID].status == "flagged"


def test_a_critic_that_cannot_answer_does_not_block_and_is_not_retried(book):
    llm = RuleLLM(qc_rules(critic=(CRITIC, "this is not json")))
    go(book, llm)
    assert load_state(book.state_path).items[SID].status == "accepted"
    assert review(book)["critic"]["error"] and len(review(book)["rounds"]) == 1
    asks_per_scene = 1 + QC_ROUNDS  # one request and its correction rounds, then no more for that scene
    assert kinds(llm).count("critic") == 2 * asks_per_scene  # two scenes in chapter 1


def test_a_continuity_check_that_cannot_answer_does_not_block(book):
    llm = RuleLLM(qc_rules(continuity=(CONTINUITY, "nope")))
    go(book, llm)
    assert load_state(book.state_path).items[SID].status == "accepted" and review(book)["continuity"]["error"]


def test_a_judge_that_is_offline_falls_back_to_the_mechanical_score(book):
    def offline(_):
        raise LLMError("critic offline")

    llm = RuleLLM(qc_rules(judge=(JUDGE, offline)))
    go(book, llm)
    r = review(book)
    assert "critic offline" in r["judge"]["error"] and r["chosen"] in ("draft-1", "draft-2")
    assert load_state(book.state_path).items[SID].status == "accepted"


def test_an_offline_model_during_revision_stops_the_layer_instead_of_flagging_the_scene(book):
    def offline(_):
        raise LLMError("writer offline")

    bad = good(SID, 1) + " " + BANNED
    summary = go(book, RuleLLM(qc_rules(overrides={SID: [bad, bad]}, revise=(REVISE, offline))))
    assert summary.stopped == "failed" and "writer offline" in summary.detail
    assert load_state(book.state_path).items[SID].status == "drafted"


def test_zero_revision_rounds_flags_at_once(book):
    (book.root / "config.yaml").write_text(QC_CONFIG.replace("qc:\n", "qc:\n  max_revision_rounds: 0\n"))
    bad = good(SID, 1) + " " + BANNED
    llm = RuleLLM(qc_rules(overrides={SID: [bad, bad]}))
    go(Project.open(book.root), llm)
    assert calls(llm, REVISE) == [] and load_state(book.state_path).items[SID].status == "flagged"


def test_an_adopted_scene_skips_the_model_checks_but_is_still_extracted(book):
    d = scenefiles.scene_dir(book, SID)
    d.mkdir(parents=True)
    (d / "final.md").write_text(prose(3, 22))
    llm = RuleLLM(qc_rules())
    go(book, llm)
    assert not any("Write scene b1.ch01.s1" in c["messages"][1]["content"] for c in llm.calls)
    seq = first_scene(llm)
    assert seq == ["summary", "extract"]  # no drafts, judge, continuity or critic for the author's own text
    r = review(book)
    assert r["source"] == "adopted" and r["extraction"]["observations"] == 1 and "judge" not in r
    assert (d / "final.md").read_text() == prose(3, 22)


# ── the CLI ─────────────────────────────────────────────────────────────────

def test_the_review_command_summarises_a_scene(book):
    go(book, RuleLLM(qc_rules(critic=(CRITIC, critic({"pacing": 2})), extract=(EXTRACT, extractor(gap="jonas-knows")),
                              revise=(REVISE, reviser({" the ": " THE "})))))
    out = CliRunner().invoke(cli.app, ["review", str(book.root), SID])
    assert out.exit_code == 0, out.output
    for needle in (f"{SID}: flagged", "chosen: draft-", "mechanical draft-1: score", "judge: wins", "round 0:", "critic: stakes 4",
                   "NEEDS YOU: the critic scored pacing 2 (minimum 3)"):
        assert needle in out.output, needle
    assert "no review yet" in CliRunner().invoke(cli.app, ["review", str(book.root), "b1.ch03.s1"]).output
