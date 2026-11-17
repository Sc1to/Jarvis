"""Every finding code the source can raise has a class; the foundation of 'no structural errors, a remedy for every content error'."""

import json
import re
from pathlib import Path

from bookforge import diagnostics
from bookforge.bible import normalize
from bookforge.remedies import registry as R
from bookforge.validators import findings as F

SRC = Path(__file__).resolve().parent.parent / "bookforge"
CODE_CALL = re.compile(r'(?:\b(?:hard|soft|make)|\))\(\s*(?:stage|"(?:ledger|acts|chapters|scenes|prose|state|research)")\s*,\s*f?"([a-z_{}]+)"')  # hard(stage, "code"), make(...), (hard if x else soft)(...)
TEMPLATES = {"{what}_retells_event": ["chapter_retells_event", "scene_retells_event", "act_retells_event"],
             "{what}_text_misses_event": ["chapter_text_misses_event", "scene_text_misses_event"],
             "{what}_text_thin_on_event": ["chapter_text_thin_on_event", "scene_text_thin_on_event"]}


def codes_in_source() -> set[str]:
    out: set[str] = set()
    for path in SRC.rglob("*.py"):
        for m in CODE_CALL.finditer(path.read_text(encoding="utf-8")):
            out.update(TEMPLATES.get(m.group(1), [m.group(1)]))
    for path in (SRC / "layers" / "ledger.py",):
        out.update(re.findall(r'soft_finding\(\s*"([a-z_]+)"', path.read_text(encoding="utf-8")))
    return out


def test_every_code_the_source_can_raise_has_a_class_and_every_class_is_for_a_code_that_exists():
    raised = codes_in_source()
    assert len(raised) > 80  # the scan found the checks
    unknown = sorted(raised - set(R.SPECS))
    assert not unknown, f"new finding code(s) without a class in bookforge/remedies/registry.py: {unknown}"
    stale = sorted(set(R.SPECS) - raised)
    assert not stale, f"registry codes the source no longer raises: {stale}"


def test_a_structural_code_says_how_it_becomes_impossible_and_the_classes_are_known():
    for s in R.SPECS.values():
        assert s.klass in (R.STRUCTURAL, R.WORDING, R.RATING, R.DECISION, R.ADVISORY, R.INFO) and s.stage
        if s.klass == R.STRUCTURAL:
            assert s.planned == "done" or s.planned.startswith("A1#") or s.note, f"{s.code}: structural without a plan row"
    assert R.klass("event_not_covered") == R.STRUCTURAL and R.klass("end_state_overreach") == R.WORDING and R.klass("nope") is None
    assert R.guaranteed("event_not_covered", "chapters") and not R.guaranteed("event_not_covered", "scenes") and R.guaranteed("scene_event_not_in_chapter", "scenes")
    assert R.guaranteed("once_only_repeated", "chapters") and R.guaranteed("once_only_repeated", "scenes") and not R.guaranteed("story_day_backwards", "scenes")


def test_a_guaranteed_structural_finding_is_saved_as_a_diagnostics_bundle_and_nothing_else_is(project):
    p = project
    bug = F.hard("chapters", "event_not_covered", "e10 is covered by no chapter", ["e10"])
    other = F.hard("chapters", "end_state_overreach", "over", ["b2.ch10", "e12"])
    later = F.hard("scenes", "story_day_backwards", "not yet by construction", ["b2.ch10.s1"])  # model-caused until the days are converted
    assert diagnostics.record(p, "chapters", "b2.act2", [other, later], {"x": 1}) is None
    assert diagnostics.record(p, "chapters", "b2.act2", [bug], {}, enabled=False) is None  # the reply was in the old shape: the model's slip, not the tool's
    name = diagnostics.record(p, "chapters", "b2.act2", [bug, other], {"reply": {"chapters": []}})
    body = json.loads((diagnostics.folder(p) / name).read_text())
    assert body["codes"] == ["event_not_covered"] and body["layer"] == "chapters" and body["context"] == {"reply": {"chapters": []}}
    listing = diagnostics.listing(p)
    assert listing["count"] == 1 and listing["latest"][0]["codes"] == ["event_not_covered"] and listing["folder"].endswith("diagnostics")


def test_old_bundles_are_cleared_beyond_the_newest_thirty(project):
    bug = F.hard("chapters", "event_not_covered", "x", ["e1"])
    for i in range(35):
        diagnostics.record(project, "chapters", f"act{i}", [bug], {})
    assert diagnostics.listing(project)["count"] == diagnostics.KEEP


def test_the_normalisation_entry_points_leave_a_reply_without_a_ledger_alone(project):
    raw = [{"id": "x", "events": ["e1"]}]
    assert normalize.normalize_acts(project, raw, None) == ([], []) and raw == [{"id": "x", "events": ["e1"]}]
    chapters, notes, problems = normalize.normalize_chapters(project, {}, [{"id": "c"}], None, None, 1)
    assert chapters == [{"id": "c"}] and notes == [] and problems == []
    assert normalize.drop_empty_tail([{"events_covered": ["e1"]}, {"events_covered": ["e1"]}]) == [{"events_covered": ["e1"]}]
    assert len(normalize.drop_empty_tail([{"events_covered": ["e1"]}, {"events_covered": ["e2"]}])) == 2
