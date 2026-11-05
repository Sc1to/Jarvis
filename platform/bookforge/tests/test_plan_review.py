import json

import pytest

from bookforge import review_notes
from bookforge.layers import HANDLERS
from bookforge.layers.runner import run
from bookforge.llm import LLMError
from bookforge.project import Project
from conftest import RuleLLM
from qc_fakes import PLAN_REVIEW, plan_review
from structure_fakes import SMALL_CONFIG, acts, dump, ready, rules, scenes_reply, chapters_act2

REVIEW_ON = SMALL_CONFIG.replace("review_structure: false", "review_structure: true")


@pytest.fixture
def base(project):
    p = ready(project)
    (p.root / "config.yaml").write_text(REVIEW_ON)
    return Project.open(p.root)


def llm_with(problems=None, **replace):
    r = [x for x in rules() if x[0] not in replace]
    return RuleLLM([(PLAN_REVIEW, plan_review(problems))] + r + list(replace.items()))


def reviews(llm):
    return [c for c in llm.calls if PLAN_REVIEW in next(m["content"] for m in c["messages"] if m["role"] == "user")]


def go(project, llm, until=None):
    return run(project, llm, HANDLERS, until=until)


def prompt_of(call):
    return next(m["content"] for m in call["messages"] if m["role"] == "user")


# ── what is reviewed, and against what ──────────────────────────────────────

def test_every_planned_piece_is_reviewed_once_against_its_parent(base):
    llm = llm_with()
    assert go(base, llm).stopped == "checkpoint"
    # acts (1), the chapters of two acts (2), the scenes of four chapters (4)
    assert len(reviews(llm)) == 7 and all(c["role"] == "critic" for c in reviews(llm))
    whats = [prompt_of(c).split("\n")[0] for c in reviews(llm)]
    assert whats[0] == "Review the proposed acts of the book as a demanding editor."
    assert whats[1:3] == [f"Review the proposed chapters of b1.act{i} as a demanding editor." for i in (1, 2)]
    assert whats[3] == "Review the proposed scenes of b1.ch01 as a demanding editor." and len(whats) == 7


def test_the_reviewer_gets_the_parent_the_north_stars_and_the_tracks(base):
    llm = llm_with()
    go(base, llm)
    acts_review, act1, act2 = (prompt_of(c) for c in reviews(llm)[:3])
    assert "A long synopsis." in acts_review  # the parent of the acts is the synopsis
    assert "id: b1.act1" in act1 and "Chapter 1" in act1 and "## Book north star" in act1 and "What it is not" in act1
    assert "anna-wound" in act2  # the tracks created by the first act are part of the state the second act must respect
    ch2 = prompt_of(next(c for c in reviews(llm) if "scenes of b1.ch02" in prompt_of(c)))
    assert "id: b1.ch02" in ch2 and "planned: from b1.ch02: deep cut, left shoulder; bleeding [must_show]" in ch2


# ── problems and corrections ────────────────────────────────────────────────

def test_a_problem_in_the_acts_is_sent_back_and_the_corrected_acts_are_kept(base):
    state = {"n": 0}

    def reviewer(messages):
        state["n"] += 1
        return plan_review({"acts of the book": [("b1.act2", "the turning point does not follow from act one")]} if state["n"] == 1 else None)(messages)

    changed = acts()
    changed["acts"][1]["turning_point"] = "A turning point that now follows from act one."

    def acts_reply(messages):
        return dump(acts()) if len(messages) == 2 else dump(changed)

    llm = RuleLLM([(PLAN_REVIEW, reviewer), ("Divide the book into ACTS", acts_reply)] + [r for r in rules() if "ACTS" not in r[0]])
    go(base, llm, until="acts")
    correction = [c for c in llm.calls if len(c["messages"]) == 4][0]["messages"][-1]["content"]
    assert "b1.act2: the turning point does not follow from act one" in correction
    assert "now follows from act one" in (base.root / "books/b1/acts.yaml").read_text()
    assert review_notes.read(base) == []  # resolved, so nothing is left for the author


def test_problems_that_remain_become_review_notes_and_do_not_fail_the_layer(base):
    llm = llm_with({"acts of the book": [("b1.act1", "the opening is too slow")]})
    summary = go(base, llm, until="acts")
    assert summary.ran == ["acts"] and "1 review note(s) for you" in summary.notes["acts"]
    [rec] = review_notes.read(base, "acts")
    assert rec["item"] == "acts" and rec["problems"] == ["b1.act1: the opening is too slow"]
    assert len(reviews(llm)) == 1 + base.config.qc.max_revision_rounds  # the review is repeated after each correction
    import subprocess
    tracked = subprocess.run(["git", "-C", str(base.root), "ls-files"], capture_output=True, text=True).stdout
    assert "books/b1/reports/review-notes.jsonl" in tracked


def test_chapter_and_scene_pieces_are_reviewed_and_corrected_independently(base):
    llm = llm_with({"chapters of b1.act2": [("b1.ch03", "the chapter does not use the vestry the act promised")],
                    "scenes of b1.ch04": [("b1.ch04.s1", "the healing is rushed")]})
    summary = go(base, llm)
    assert summary.stopped == "checkpoint"
    notes = review_notes.read(base)
    assert {(n["layer"], n["item"]) for n in notes} == {("chapters", "chapters/act2"), ("scenes", "scenes/ch04")}
    by_layer = {n["layer"]: n["problems"] for n in notes}
    assert by_layer["chapters"] == ["b1.ch03: the chapter does not use the vestry the act promised"]
    assert by_layer["scenes"] == ["b1.ch04.s1: the healing is rushed"]
    assert "review note(s) for you" in summary.notes["chapters"] and "review note(s) for you" in summary.notes["scenes"]


def test_reviews_are_not_repeated_for_pieces_that_were_saved_before_a_failure(base):
    def offline(_):
        raise LLMError("colibri went away")

    first = llm_with(**{"Plan exactly 2 chapters, b1.ch03 to b1.ch04": offline})
    assert go(base, first).stopped == "failed"
    done = len(reviews(first))
    again = llm_with()
    go(Project.open(base.root), again)
    # the acts and act 1's chapters were reviewed and saved by the first run; only the rest is reviewed now
    assert done == 2 and len(reviews(again)) == 5


# ── when it is skipped or fails ─────────────────────────────────────────────

def test_review_can_be_switched_off(base):
    (base.root / "config.yaml").write_text(SMALL_CONFIG)
    llm = llm_with()
    go(Project.open(base.root), llm)
    assert reviews(llm) == []


def test_a_reviewer_that_fails_never_blocks(base):
    def offline(_):
        raise LLMError("critic offline")

    llm = RuleLLM([(PLAN_REVIEW, offline)] + rules())
    assert go(base, llm).stopped == "checkpoint"
    assert review_notes.read(base) == []


def test_a_reviewer_that_returns_nonsense_is_ignored(base):
    llm = RuleLLM([(PLAN_REVIEW, "I think it looks fine!")] + rules())
    assert go(base, llm, until="acts").ran == ["acts"] and review_notes.read(base) == []


@pytest.mark.parametrize("reply,needle", [
    ({"ok": "yes", "problems": []}, '"ok" must be true or false'),
    ({"ok": False, "problems": "none"}, '"problems" must be a list'),
    ({"ok": False, "problems": []}, "no problems are listed"),
    ({"ok": False, "problems": [{"item": "b1.ch01"}]}, "needs an 'item' and an 'issue'"),
])
def test_a_malformed_review_is_sent_back_for_correction(base, reply, needle):
    llm = RuleLLM([(PLAN_REVIEW, json.dumps(reply)), ("Divide the book into ACTS", dump(acts()))])
    go(base, llm, until="acts")
    corrections = [c["messages"][-1]["content"] for c in llm.calls if len(c["messages"]) == 4 and "Review the proposed" in c["messages"][1]["content"]]
    assert corrections and needle in corrections[0]


def test_the_review_waits_for_a_structurally_valid_reply(base):
    def acts_reply(messages):
        return dump(acts((9, 9))) if len(messages) == 2 else dump(acts())

    llm = RuleLLM([(PLAN_REVIEW, plan_review()), ("Divide the book into ACTS", acts_reply)])
    go(base, llm, until="acts")
    order = ["review" if PLAN_REVIEW in c["messages"][1]["content"] else "acts" for c in llm.calls]
    assert order == ["acts", "acts", "review"]  # the invalid first reply was corrected before anyone reviewed it
