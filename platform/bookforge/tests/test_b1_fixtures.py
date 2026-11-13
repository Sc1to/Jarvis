"""The same validators on b1's real output, once it is copied into tests/fixtures/b1/ (see the README there). Skipped until then."""

from pathlib import Path

import pytest
import yaml

from bookforge.validators import repeats as R, state as S, tension as T

B1 = Path(__file__).parent / "fixtures" / "b1"
pytestmark = pytest.mark.skipif(not (B1 / "chapters.yaml").exists(), reason="copy b1's real files into tests/fixtures/b1/ to run these")


def load(name, key):
    return (yaml.safe_load((B1 / name).read_text(encoding="utf-8")) or {}).get(key, [])


def test_b1_repeats_and_flat_tension_are_caught():
    chapters, scenes = load("chapters.yaml", "chapters"), load("scenes.yaml", "scenes")
    names = {e["id"] for e in load("constants.yaml", "entities")} | {e["name"].split()[0].lower() for e in load("constants.yaml", "entities")}
    found = {f.code for f in R.repeated_events(chapters, scenes, names)}
    assert "event_repeated" in found
    assert R.action_patterns(scenes, chapters, names)
    assert T.flat_stretches(chapters)


def test_b1_state_contradictions_are_caught():
    tracks, timeline, scenes = load("tracks.yaml", "tracks"), load("timeline.yaml", "scenes"), load("scenes.yaml", "scenes")
    assert S.track_regressions(tracks) or S.location_conflicts(scenes, timeline, tracks)
