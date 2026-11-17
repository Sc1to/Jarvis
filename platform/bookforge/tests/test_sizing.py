"""The book's length is told to the planner and checked against the plan; nothing is padded."""

from types import SimpleNamespace

from ledger_structure_fakes import events
from structure_fakes import ready

from bookforge import sizing
from bookforge.bible.models import Scene
from bookforge.validators import ledger as ledger_checks


def chapters_of(*ev_lists):
    return [SimpleNamespace(id=f"b1.ch{i:02d}", events_covered=e, events_continued=[]) for i, e in enumerate(ev_lists, 1)]


def with_target(project, target, words=None):
    cfg = project.config.model_copy(deep=True)
    cfg.book.target_words = target
    cfg.layers["prose"].words = words
    return SimpleNamespace(config=cfg)


def test_budget_follows_event_weight(project):
    p = ready(project)
    ev = [e.model_dump() for e in events()]
    ev[0]["weight"], ev[1]["weight"] = 1, 3
    budget = sizing.chapter_budget(with_target(p, 8000), chapters_of(["e1"], ["e2"]), ev)
    assert budget == {"b1.ch01": 2000, "b1.ch02": 6000}


def test_no_budget_without_a_target_or_with_fixed_scene_length(project):
    p = ready(project)
    ev = [e.model_dump() for e in events()]
    assert sizing.chapter_budget(with_target(p, 0), chapters_of(["e1"]), ev) == {}
    assert sizing.chapter_budget(with_target(p, 80000, words=(1500, 3000)), chapters_of(["e1"]), ev) == {}


def test_guidance_turns_the_budget_into_scenes_and_beats():
    text = sizing.length_guidance(3600)
    assert "about 2 scenes of about 1800 words" in text and "never by inventing events" in text
    assert "one or two scenes" in sizing.length_guidance(None)


def scene(n, beats):
    return Scene(id=f"b1.ch{n:02d}.s1", chapter=f"b1.ch{n:02d}", purpose="p", pov="a", setting="s", characters=["a"], beats=["x"] * beats, end_state="e", events=[])


def test_a_plan_far_short_of_the_target_is_a_soft_warning_never_a_stop(project):
    base = ready(project)
    found = ledger_checks.plan_vs_target(with_target(base, 80000), [scene(i, 4) for i in range(1, 25)])
    assert [f.code for f in found] == ["plan_short_of_target"] and found[0].severity != "hard" and "short of" in found[0].message


def test_a_plan_near_the_target_or_with_no_target_raises_nothing(project):
    base = ready(project)
    near = [scene(i, 6) for i in range(1, 30)]
    lo, hi = sizing.planned_words(base, near)
    assert ledger_checks.plan_vs_target(with_target(base, round((lo + hi) / 2)), near) == []
    assert ledger_checks.plan_vs_target(with_target(base, 0), near) == []
