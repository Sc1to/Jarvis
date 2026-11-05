import pytest

from bookforge.bible import store
from bookforge.bible.lookup import constants_for, day_of, elapsed_days, obligations_at, scene_entities, state_at
from bookforge.bible.models import Constants, Entity, PlanEntry, Scene, TimelineEntry, Track
from bookforge.bible.positions import act_id, canonical, chapter_id, parse_act_id, parse_position, scene_id


# ── positions ───────────────────────────────────────────────────────────────

def test_ids_and_parsing():
    assert chapter_id("b1", 4) == "b1.ch04" and scene_id("b1", 4, 3) == "b1.ch04.s3" and act_id("b1", 2) == "b1.act2"
    p = parse_position("b1.ch4.s3")
    assert (p.book, p.chapter, p.scene, p.id, p.chapter_ref) == ("b1", 4, 3, "b1.ch04.s3", "b1.ch04")
    assert canonical("b1.ch4") == "b1.ch04" and canonical("b1.ch104.s2") == "b1.ch104.s2"
    assert parse_act_id("b1.act3") == ("b1", 3)


@pytest.mark.parametrize("bad", ["", "ch04", "b1.ch0", "b1.ch04.s0", "b1.act2", "B1.ch01", "b1.ch04.s", "b1.ch04.s3.x", "b1/ch04"])
def test_bad_positions_are_rejected(bad):
    with pytest.raises(ValueError):
        parse_position(bad)


def test_ordering_puts_a_chapter_before_its_scenes():
    keys = [parse_position(x).key for x in ("b1.ch03.s2", "b1.ch04", "b1.ch03", "b1.ch04.s1", "b1.ch03.s1")]
    assert sorted(keys) == [(3, 0), (3, 1), (3, 2), (4, 0), (4, 1)]


# ── lookups ─────────────────────────────────────────────────────────────────

def wound() -> Track:
    return Track(id="anna-wound", entity="anna", kind="physical", version=2, plan=[
        PlanEntry(**{"from": "b1.ch04.s3", "value": "deep cut, left shoulder; bleeding", "must_show": True}),
        PlanEntry(**{"from": "b1.ch05.s1", "value": "stiff and painful; can't lift left arm"}),
        PlanEntry(**{"from": "b1.ch10.s2", "value": "healed; scar remains", "must_show": True}),
    ])


def knows() -> Track:
    return Track(id="jonas-knows", entity="jonas", kind="knowledge", plan=[PlanEntry(**{"from": "b1.ch03", "value": "knows the secret"})])


def test_no_state_before_the_first_entry():
    assert state_at([wound()], "b1.ch04.s2") == []
    assert state_at([wound()], "b1.ch03") == []


def test_state_begins_at_its_scene_and_must_show_only_there():
    [s] = state_at([wound()], "b1.ch04.s3")
    assert (s.value, s.since, s.begins_here, s.must_show, s.previous, s.version) == (
        "deep cut, left shoulder; bleeding", "b1.ch04.s3", True, True, None, 2)
    [later] = state_at([wound()], "b1.ch04.s4")
    assert later.value == s.value and not later.begins_here and not later.must_show


def test_state_changes_at_the_next_entry_and_remembers_the_previous():
    [s] = state_at([wound()], "b1.ch05.s1")
    assert s.value.startswith("stiff") and s.begins_here and not s.must_show
    assert s.previous == "deep cut, left shoulder; bleeding"
    assert state_at([wound()], "b1.ch09.s9")[0].value.startswith("stiff")
    assert state_at([wound()], "b1.ch10.s2")[0].value.startswith("healed")


def test_a_chapter_entry_applies_from_the_start_of_the_chapter():
    assert state_at([knows()], "b1.ch03")[0].begins_here
    assert state_at([knows()], "b1.ch03.s1")[0].value == "knows the secret"
    assert state_at([knows()], "b1.ch02.s4") == []


def test_entity_filter_and_obligations():
    tracks = [wound(), knows()]
    assert [s.track_id for s in state_at(tracks, "b1.ch10.s2", ["anna"])] == ["anna-wound"]
    assert {s.track_id for s in state_at(tracks, "b1.ch10.s2")} == {"anna-wound", "jonas-knows"}
    assert state_at(tracks, "b1.ch10.s2", []) == []
    assert [s.track_id for s in obligations_at(tracks, "b1.ch04.s3")] == ["anna-wound"]
    assert obligations_at(tracks, "b1.ch05.s1") == []


def test_other_books_are_ignored():
    other = Track(id="x", entity="anna", plan=[PlanEntry(**{"from": "b2.ch01", "value": "elsewhere"})])
    assert state_at([other], "b1.ch09") == []


def test_scene_entities_and_constants_and_time():
    scenes = [Scene(id="b1.ch01.s1", purpose="p", pov="anna", setting="harbor", characters=["anna", "jonas"], beats=["a", "b"])]
    assert scene_entities(scenes, "b1.ch01.s1") == {"anna", "jonas", "harbor"}
    assert scene_entities(scenes, "b1.ch09.s1") == set()
    constants = Constants(entities=[Entity(id="anna", kind="character", name="A", facts=["f"]), Entity(id="x", kind="place", name="X", facts=["f"])])
    assert [e.id for e in constants_for(constants, {"anna"})] == ["anna"]
    tl = [TimelineEntry(id="b1.ch01.s1", day=3, time="dawn"), TimelineEntry(id="b1.ch05.s1", day=11, time="noon")]
    assert day_of(tl, "b1.ch01.s1") == 3 and day_of(tl, "b1.ch09.s1") is None
    assert elapsed_days(tl, "b1.ch01.s1", "b1.ch05.s1") == 8 and elapsed_days(tl, "b1.ch05.s1", "b1.ch01.s1") == -8
    assert elapsed_days(tl, "b1.ch01.s1", "nope") is None


# ── store ───────────────────────────────────────────────────────────────────

def test_tracks_round_trip_with_from_key(project):
    store.save_tracks(project, [wound()])
    text = (project.root / "bible/tracks.yaml").read_text()
    assert "from: b1.ch04.s3" in text and "from_" not in text
    assert store.load_tracks(project)[0].plan[2].value == "healed; scar remains"


def test_empty_template_files_load_as_empty(project):
    assert store.load_tracks(project) == [] and store.load_timeline(project) == []
    assert store.load_constants(project) == Constants()
    assert store.load_acts(project) == [] and store.load_chapters(project) == [] and store.load_scenes(project) == []


def test_broken_files_are_reported_not_crashed_on(project):
    (project.root / "bible/tracks.yaml").write_text("tracks: [unclosed")
    with pytest.raises(store.BibleError, match="not valid YAML"):
        store.load_tracks(project)
    (project.root / "bible/tracks.yaml").write_text("tracks:\n  - id: Bad Id\n")
    with pytest.raises(store.BibleError, match="not valid"):
        store.load_tracks(project)
    (project.root / "bible/tracks.yaml").write_text("just: a mapping\n")
    with pytest.raises(store.BibleError, match="expected a 'tracks:' list"):
        store.load_tracks(project)


def test_upsert_adds_tracks_and_merges_entries_by_position():
    a = wound()
    extra = Track(id="anna-wound", entity="anna", plan=[PlanEntry(**{"from": "b1.ch07", "value": "twinges"}),
                                                       PlanEntry(**{"from": "b1.ch05.s1", "value": "REWORDED"})])
    new = knows()
    merged = store.upsert_plan([a], [extra, new])
    assert [t.id for t in merged] == ["anna-wound", "jonas-knows"]
    plan = merged[0].plan
    assert [e.from_ for e in plan] == ["b1.ch04.s3", "b1.ch05.s1", "b1.ch07", "b1.ch10.s2"]
    assert plan[1].value == "REWORDED"
    again = store.upsert_plan(merged, [extra])
    assert [e.from_ for e in again[0].plan] == [e.from_ for e in plan]  # idempotent


def test_upsert_refuses_to_change_a_tracks_owner():
    with pytest.raises(store.BibleError, match="belongs to 'anna'"):
        store.upsert_plan([wound()], [Track(id="anna-wound", entity="jonas", plan=[PlanEntry(**{"from": "b1.ch11", "value": "x"})])])
