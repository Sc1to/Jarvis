"""The shipped beat pairs: the same scene with plain and with specific beats; run by name only."""

from bookforge import bench
from bookforge.project import Project

KINDS = ("invest", "dialogue", "domestic", "action")


def test_each_scene_type_has_a_plain_and_a_specific_version(project):
    names = [f"{k}-{v}" for k in KINDS for v in ("plain", "specific")]
    found = {b.id: b for b in bench.load_benchmarks(project, names)}
    assert set(found) == set(names)
    for k in KINDS:
        plain, specific = found[f"{k}-plain"], found[f"{k}-specific"]
        assert plain.purpose == specific.purpose and plain.words == specific.words and plain.pov == specific.pov  # only the specificity differs
        assert sum(len(b.split()) for b in specific.beats) > 2 * sum(len(b.split()) for b in plain.beats)
        assert specific.situation and specific.learns and not plain.situation
        assert "Where things stand when it opens" in specific.briefing(project) and "Where things stand" not in plain.briefing(project)


def test_the_default_run_does_not_include_the_pairs(project):
    assert not any(b.id.endswith(("-plain", "-specific")) for b in bench.load_benchmarks(project))
