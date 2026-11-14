import json

import pytest

from bookforge import scenefiles
from bookforge.bible import store
from bookforge.briefing import BriefingError, build_briefing, estimate_tokens
from bookforge.deps import Deps, fingerprint, read_deps, tag, write_deps
from bookforge.layers import HANDLERS
from bookforge.layers.runner import run
from bookforge.project import Project
from conftest import RuleLLM
from prose_fakes import prose
from structure_fakes import ready, rules

HEADINGS = ["Series north star", "Book north star", "Style guide", "Phrases never to use",
            "Cast and rules of the world (fixed facts)", "Story state at this scene (facts the scene must not contradict)",
            "When this scene happens", "This scene", "This chapter"]


@pytest.fixture
def book(project):
    p = ready(project)
    assert run(p, RuleLLM(rules()), HANDLERS).stopped == "checkpoint"
    return Project.open(p.root)


def write_scene(project, scene_id, text, summary=None, chosen=None):
    d = scenefiles.scene_dir(project, scene_id)
    d.mkdir(parents=True, exist_ok=True)
    if chosen:
        (d / f"{chosen}.md").write_text(text)
        (d / "review.json").write_text(json.dumps({"chosen": chosen}))
    else:
        (d / "final.md").write_text(text)
    if summary:
        (d / "summary.md").write_text(summary)


def section(b, start):
    return next(s.body for s in b.sections if s.heading.startswith(start))


# ── content ─────────────────────────────────────────────────────────────────

def test_sections_come_in_the_documented_order_with_the_essentials(book):
    b = build_briefing(book, "b1.ch02.s2")
    heads = [s.heading for s in b.sections]
    assert heads[:2] == HEADINGS[:2] and heads.index("This scene") < heads.index("This chapter")
    assert "Series north star" in heads and "Book north star" in heads
    assert [h for h in HEADINGS if h in heads] == [h for h in heads if h in HEADINGS]  # same relative order
    assert b.tokens == sum(t for _, t in b.breakdown()) and b.tokens <= b.budget and b.trimmed == []
    assert b.text().startswith("## Series north star")


def test_the_scene_section_gives_beats_in_order_with_names(book):
    body = section(build_briefing(book, "b1.ch02.s2"), "This scene")
    assert "Viewpoint character: Anna Voss" in body and "Setting: The harbor town" in body
    assert "Present: Anna Voss, Jonas Reil" in body and "1. Something happens.\n2. Anna decides." in body


def test_only_the_entities_in_the_scene_are_described_but_all_rules(book):
    body = section(build_briefing(book, "b1.ch03.s1"), "Cast and rules")
    assert "The vestry (place, id vestry)" in body and "Anna Voss (character" in body
    assert "The ledger" not in body and "harbor town" not in body  # not in this scene
    assert "Rule: each name crossed out costs a year of memory" in body


def test_story_state_shows_changes_that_begin_here_and_what_came_before(book):
    state = section(build_briefing(book, "b1.ch04.s1"), "Story state")
    assert "Anna Voss (physical): healed; scar remains" in state
    assert "must be shown on the page" in state and "Before this: deep cut, left shoulder; bleeding" in state
    later = section(build_briefing(book, "b1.ch04.s2"), "Story state")
    assert "healed; scar remains" in later and "must be shown" not in later


def test_state_that_has_not_begun_is_not_shown(book):
    assert "healed" not in section(build_briefing(book, "b1.ch03.s1"), "Story state")
    assert "deep cut" in section(build_briefing(book, "b1.ch03.s1"), "Story state")


def test_timing_includes_the_gap_since_the_previous_scene(book):
    assert section(build_briefing(book, "b1.ch02.s1"), "When") == "Story day 2, dusk; 1 day(s) after the previous scene"
    assert section(build_briefing(book, "b1.ch01.s2"), "When").endswith("the same day as the previous scene")
    assert "after the previous scene" not in section(build_briefing(book, "b1.ch01.s1"), "When")
    assert "30 day(s) after" in section(build_briefing(book, "b1.ch04.s1"), "When")


def test_research_notes_are_the_cited_ones_only(book):
    from bookforge.research.notes import stores_for
    store_ = stores_for(book)["book"]
    store_.add_fact(claim="Warehouses used oil lamps.", url="https://a.example/w", title="t", fetched="2026-11-05",
                    quote="q", layer="scenes", question="Q?")
    store_.add_fact(claim="Uncited fact.", url="https://a.example/u", title="t", fetched="2026-11-05", quote="q", layer="scenes", question="Q2?")
    scenes = store.load_scenes(book)
    scenes[2].research = ["b1-0001"]
    store.save_scenes(book, scenes)
    b = build_briefing(Project.open(book.root), "b1.ch02.s1")
    notes = section(b, "Research notes")
    assert "[b1-0001] Warehouses used oil lamps. (source: a.example/w)" in notes and "Uncited" not in notes
    assert any(d.startswith("b1-0001@") for d in b.deps.research)
    assert not any(s.heading.startswith("Research notes") for s in build_briefing(book, "b1.ch01.s1").sections)


def test_style_guide_samples_and_banned_phrases(book):
    (book.root / "style/guide.md").write_text("Plain words. Short chapters. Never explain a joke.")
    (book.root / "style/samples/a.md").write_text("Sample A text about a gull.")
    (book.root / "style/samples/b.md").write_text("Sample B text about a bell.")
    (book.root / "style/samples/c.md").write_text("Sample C should not appear.")
    b = build_briefing(Project.open(book.root), "b1.ch01.s1")
    assert section(b, "Style guide") == "Plain words. Short chapters. Never explain a joke."
    samples = section(b, "Sample passages")
    assert "Sample A" in samples and "Sample B" in samples and "Sample C" not in samples
    banned = section(b, "Phrases never to use")
    assert "- a testament to" in banned and "re:" not in banned and r"\bdelve[sd]? (into|deeper)\b" in banned


def test_a_missing_style_guide_is_said_plainly(book):
    assert "no style guide yet" in section(build_briefing(book, "b1.ch01.s1"), "Style guide")


# ── the story so far and the previous scene ─────────────────────────────────

def test_recent_chapters_are_summarised_per_scene_and_older_ones_in_a_line(book):
    write_scene(book, "b1.ch01.s1", prose(0), summary="Anna meets Jonas on the quay.")
    so_far = section(build_briefing(book, "b1.ch04.s1"), "The story so far")
    assert "- b1.ch01 Chapter 1:" in so_far and "Anna meets Jonas on the quay." in so_far  # one-liner, uses the written summary
    assert "changes things" not in so_far and "b1.ch02" not in so_far and "b1.ch03" not in so_far  # a plan is not history
    assert "b1.ch04" not in so_far


def test_planned_end_states_stand_in_for_unwritten_scenes_but_purposes_never_do(book):
    from bookforge.bible import store
    scenes = store.load_scenes(book)
    scenes[0] = scenes[0].model_copy(update={"end_state": "Anna holds the ledger."})
    store.save_scenes(book, scenes)
    so_far = section(build_briefing(book, "b1.ch04.s1"), "The story so far")
    assert "(planned) Anna holds the ledger." in so_far and "changes things" not in so_far


def test_scenes_earlier_in_the_chapter_are_summarised_in_full(book):
    write_scene(book, "b1.ch02.s1", prose(0), summary="Anna finds the wound is deep.")
    so_far = section(build_briefing(book, "b1.ch02.s2"), "The story so far")
    assert "Earlier in this chapter (b1.ch02):\n  - b1.ch02.s1: Anna finds the wound is deep." in so_far
    assert "no story" not in so_far and not any(s.heading == "The story so far" for s in build_briefing(book, "b1.ch01.s1").sections)


def test_the_previous_scene_is_given_verbatim_from_its_end(book):
    text = prose(0, 24)
    write_scene(book, "b1.ch02.s1", text)
    b = build_briefing(book, "b1.ch02.s2")
    heading, body = next((s.heading, s.body) for s in b.sections if s.heading.startswith("How the previous scene ended"))
    assert "b1.ch02.s1" in heading and "do not restate" in heading
    assert body.split()[-5:] == text.split()[-5:] and len(body.split()) <= 1500


def test_the_tail_is_limited_and_starts_at_a_sentence(book):
    text = prose(0, 28)
    write_scene(book, "b1.ch02.s1", text)
    (book.root / "config.yaml").write_text((book.root / "config.yaml").read_text() + "briefing:\n  previous_scene_words: 60\n")
    body = next(s.body for s in build_briefing(Project.open(book.root), "b1.ch02.s2").sections if s.heading.startswith("How the previous scene ended"))
    assert 20 < len(body.split()) <= 60 and body[0].isupper() or body[0] in "\"“"


def test_across_a_chapter_boundary_the_last_scene_of_the_previous_chapter_is_used(book):
    write_scene(book, "b1.ch01.s2", "The last words of chapter one were these.")
    body = next(s.body for s in build_briefing(book, "b1.ch02.s1").sections if s.heading.startswith("How the previous scene ended"))
    assert body == "The last words of chapter one were these."


def test_a_flagged_previous_scene_falls_back_to_its_chosen_draft(book):
    write_scene(book, "b1.ch02.s1", "Draft two is the chosen one.", chosen="draft-2")
    body = next(s.body for s in build_briefing(book, "b1.ch02.s2").sections if s.heading.startswith("How the previous scene ended"))
    assert body == "Draft two is the chosen one."
    assert scenefiles.best_text(book, "b1.ch01.s1") is None


# ── dependencies ────────────────────────────────────────────────────────────

def test_deps_record_everything_the_scene_was_built_from(book):
    write_scene(book, "b1.ch02.s1", prose(0), summary="Something happened.")
    d = build_briefing(book, "b1.ch02.s2").deps
    assert d.scene.startswith("b1.ch02.s2@") and d.parent.startswith("b1.ch02@")
    assert [x.split("@")[0] for x in d.north_stars] == ["series", "b1"]
    assert {x.split("@")[0] for x in d.style} >= {"guide", "banned"}
    assert {"entity:anna", "entity:harbor", "track:anna-wound", "rule:ledger-cost"} <= {x.split("@")[0] for x in d.bible}
    assert [x.split("@")[0] for x in d.timeline] == ["b1.ch02.s2", "b1.ch02.s1"]
    assert d.previous[0].startswith("b1.ch02.s1@") and any(x.startswith("summary:b1.ch02.s1@") for x in d.summaries)
    assert all(len(x.split("@")[1]) == 8 for x in d.to_dict()["bible"])


def test_fingerprints_are_stable_and_follow_content():
    assert fingerprint("abc") == fingerprint("abc") != fingerprint("abd")
    assert fingerprint({"a": 1, "b": 2}) == fingerprint({"b": 2, "a": 1})
    assert tag("x", "abc") == f"x@{fingerprint('abc')}"


def test_deps_change_only_for_what_actually_changed(book):
    before = build_briefing(book, "b1.ch04.s1").deps
    assert build_briefing(book, "b1.ch04.s1").deps == before

    (book.root / "style/guide.md").write_text("A new rule of style.")
    after = build_briefing(Project.open(book.root), "b1.ch04.s1").deps
    assert after.style != before.style and after.bible == before.bible and after.scene == before.scene

    scenes = store.load_scenes(book)
    scenes[6].beats = ["Changed beat one.", "Changed beat two."]
    store.save_scenes(book, scenes)
    edited = build_briefing(Project.open(book.root), "b1.ch04.s1").deps
    assert edited.scene != before.scene and edited.parent == before.parent


def test_editing_a_later_track_entry_does_not_touch_an_earlier_scene(book):
    tracks = store.load_tracks(book)
    wound = next(t for t in tracks if t.id == "anna-wound")
    early_before = build_briefing(book, "b1.ch02.s2").deps.bible
    late_before = build_briefing(book, "b1.ch04.s1").deps.bible
    wound.plan[-1].value = "healed completely, no scar"  # the ch04 entry
    store.save_tracks(book, tracks)
    reopened = Project.open(book.root)
    assert build_briefing(reopened, "b1.ch02.s2").deps.bible == early_before  # the wound had not healed yet at ch02
    assert build_briefing(reopened, "b1.ch04.s1").deps.bible != late_before  # the scene where it heals is stale


def test_deps_round_trip_through_deps_yaml(book, tmp_path):
    d = build_briefing(book, "b1.ch02.s2").deps
    path = tmp_path / "x" / "deps.yaml"
    write_deps(path, d)
    assert read_deps(path) == d
    assert path.read_text().startswith("scene: b1.ch02.s2@")
    assert read_deps(tmp_path / "missing.yaml") is None
    path.write_text("- not a mapping")
    assert read_deps(path) is None


# ── the budget ──────────────────────────────────────────────────────────────

def test_an_over_budget_pack_is_cut_in_the_documented_order(book):
    for n in range(1, 4):
        for s in (1, 2):
            write_scene(book, f"b1.ch0{n}.s{s}", prose(n), summary="A summary " + "that goes on and on " * 20)
    (book.root / "style/guide.md").write_text("Style. " * 800)
    full = build_briefing(book, "b1.ch04.s2")
    tight = build_briefing(book, "b1.ch04.s2", max_tokens=full.tokens - 400)
    assert tight.tokens <= full.tokens - 400
    assert tight.trimmed[0] == "older chapter summaries shortened" and len(tight.trimmed) >= 1
    for essential in ("This scene", "Story state at this scene (facts the scene must not contradict)", "Series north star", "Book north star"):
        assert any(s.heading == essential for s in tight.sections)
    assert section(tight, "This scene") == section(full, "This scene")


def test_the_style_guide_is_the_last_thing_to_be_cut(book):
    write_scene(book, "b1.ch04.s1", prose(0, 28))
    (book.root / "style/guide.md").write_text("Style. " * 2000)
    (book.root / "style/samples/a.md").write_text("Sample. " * 800)
    from bookforge.briefing import _Data, _assemble, _ladder
    data = _Data(book, "b1.ch04.s2")
    rungs = _ladder(book)
    just_before_the_last = sum(s.tokens for s in _assemble(data, rungs[-2][0])[0])
    tight = build_briefing(book, "b1.ch04.s2", max_tokens=just_before_the_last - 1)
    assert tight.trimmed[-1] == "style guide shortened" and tight.trimmed[-2] == rungs[-2][1]
    assert len(section(tight, "Style guide")) <= 2500


def test_a_budget_that_cannot_be_met_is_an_error_naming_the_big_parts(book):
    with pytest.raises(BriefingError, match="over the budget of 100.*Largest parts"):
        build_briefing(book, "b1.ch04.s1", max_tokens=100)


def test_unknown_scenes_are_reported(book):
    with pytest.raises(BriefingError, match="no scene b1.ch09.s1"):
        build_briefing(book, "b1.ch09.s1")


def test_token_estimate_is_proportional_to_length():
    assert estimate_tokens("") == 0 and estimate_tokens("x" * 35) == 10 and estimate_tokens("x" * 36) == 11
