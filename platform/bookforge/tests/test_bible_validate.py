import pytest

from bookforge.bible.models import Act, Chapter, Constants, Track
from bookforge.bible.validate import parse_acts, parse_cast, parse_chapters, parse_scenes
from structure_fakes import acts, cast, chapter, chapters_act1, chapters_act2, dump, scene, scenes_reply, small


@pytest.fixture
def p(project):
    return small(project)


@pytest.fixture
def constants():
    return Constants.model_validate(cast())


def has(problems, *needles):
    text = " | ".join(problems)
    return all(n in text for n in needles)


# ── acts ────────────────────────────────────────────────────────────────────

def test_valid_acts(p):
    parsed, problems = parse_acts(dump(acts()), p)
    assert problems == [] and [a.id for a in parsed] == ["b1.act1", "b1.act2"]


def test_extra_keys_are_ignored(p):
    data = acts()
    data["acts"][0]["mood"] = "grim"
    parsed, problems = parse_acts(dump(data), p)
    assert problems == [] and not hasattr(parsed[0], "mood")


@pytest.mark.parametrize("text,needles", [
    ("acts: [unclosed", ("valid YAML",)),
    ("- a\n- b\n", ("top level must be a mapping",)),
    ("acts: nope\n", ("'acts' must be a list",)),
])
def test_acts_that_cannot_be_read(p, text, needles):
    parsed, problems = parse_acts(text, p)
    assert parsed is None and has(problems, *needles)


def test_wrong_number_of_acts(p):
    assert has(parse_acts(dump(acts((2, 1, 1))), p)[1], "expected 2 to 2 acts, got 3")
    assert has(parse_acts(dump({"acts": acts()["acts"][:1]}), p)[1], "expected 2 to 2 acts, got 1")


def test_wrong_act_id(p):
    data = acts()
    data["acts"][1]["id"] = "b1.act5"
    assert has(parse_acts(dump(data), p)[1], "acts[1].id is 'b1.act5', expected 'b1.act2'")


def test_chapter_counts_must_add_up_to_the_configured_range(p):
    assert has(parse_acts(dump(acts((1, 1))), p)[1], "add up to 2", "between 4 and 4")
    assert has(parse_acts(dump(acts((4, 4))), p)[1], "add up to 8")


def test_missing_fields_are_named(p):
    data = acts()
    del data["acts"][0]["turning_point"]
    assert has(parse_acts(dump(data), p)[1], "acts[0].turning_point")


# ── cast ────────────────────────────────────────────────────────────────────

def test_valid_cast():
    new, problems = parse_cast(dump(cast()), Constants())
    assert problems == [] and len(new.entities) == 5 and new.rules[0].id == "ledger-cost"


def test_cast_needs_a_character_and_a_place():
    only_chars = {"entities": [e for e in cast()["entities"] if e["kind"] == "character"]}
    assert has(parse_cast(dump(only_chars), Constants())[1], "at least one place")
    only_places = {"entities": [e for e in cast()["entities"] if e["kind"] == "place"]}
    assert has(parse_cast(dump(only_places), Constants())[1], "at least one character")


def test_existing_entities_must_not_be_repeated(constants):
    assert has(parse_cast(dump(cast()), constants)[1], "'anna' already exists")
    extra = {"entities": [{"id": "mira", "kind": "character", "name": "Mira", "facts": ["old"]}]}
    new, problems = parse_cast(dump(extra), constants)  # the existing cast already has a place
    assert problems == [] and [e.id for e in new.entities] == ["mira"]


@pytest.mark.parametrize("change", [
    {"id": "Anna Voss"}, {"id": "9lives"}, {"kind": "monster"}, {"facts": []}, {"name": ""},
])
def test_bad_entities_are_named(change):
    data = cast()
    data["entities"][0].update(change)
    assert not parse_cast(dump(data), Constants())[1] == []


def test_duplicate_ids_inside_one_reply():
    data = cast()
    data["entities"].append(dict(data["entities"][0]))
    assert has(parse_cast(dump(data), Constants())[1], "already exists")


# ── chapters of one act ─────────────────────────────────────────────────────

def ctx_args(p, constants, act_no=1, tracks=()):
    act_list = [Act.model_validate(a) for a in acts()["acts"]]
    return dict(project=p, act=act_list[act_no - 1], first_number=1 if act_no == 1 else 3, constants=constants,
                tracks_so_far=list(tracks), fact_ids={"s-0001"})


def test_valid_chapters_and_tracks(p, constants):
    bundle, problems = parse_chapters(dump(chapters_act1()), **ctx_args(p, constants))
    assert problems == []
    assert [c.id for c in bundle.chapters] == ["b1.ch01", "b1.ch02"] and {c.act for c in bundle.chapters} == {"b1.act1"}
    wound = next(t for t in bundle.tracks if t.id == "anna-wound")
    assert wound.version == 1 and wound.observed == [] and wound.plan[0].from_ == "b1.ch02" and wound.plan[0].must_show


def test_chapter_ids_are_normalised_and_acts_assigned(p, constants):
    data = chapters_act1()
    data["chapters"][0]["id"] = "b1.ch1"
    data["chapters"][0]["act"] = "somewhere-else"
    bundle, problems = parse_chapters(dump(data), **ctx_args(p, constants))
    assert problems == [] and bundle.chapters[0].id == "b1.ch01" and bundle.chapters[0].act == "b1.act1"


def test_extending_a_track_without_naming_its_owner(p, constants):
    first, _ = parse_chapters(dump(chapters_act1()), **ctx_args(p, constants))
    bundle, problems = parse_chapters(dump(chapters_act2()), **ctx_args(p, constants, 2, first.tracks))
    assert problems == [] and next(t for t in bundle.tracks if t.id == "anna-wound").entity == "anna"


@pytest.mark.parametrize("mutate,needles", [
    (lambda d: d["chapters"].pop(), ("needs exactly 2 chapters, got 1",)),
    (lambda d: d["chapters"][1].update(id="b1.ch07"), ("chapters[1].id is 'b1.ch07', expected 'b1.ch02'",)),
    (lambda d: d["chapters"][0].update(pov="nobody"), ("'nobody' is not in the cast",)),
    (lambda d: d["chapters"][0].update(pov="harbor"), ("'harbor' is a place, expected a character",)),
    (lambda d: d["chapters"][0].update(setting="anna"), ("'anna' is a character, expected a place",)),
    (lambda d: d["chapters"][0].update(tension=11), ("chapters[0].tension",)),
    (lambda d: d["chapters"][0].update(research=["s-9999"]), ("unknown research fact id(s) s-9999",)),
    (lambda d: d["chapters"][0].pop("summary"), ("chapters[0].summary",)),
    (lambda d: d["tracks"][0].update(entity="ghost"), ("'ghost' is not in the cast",)),
    (lambda d: d["tracks"][0]["plan"][0].update({"from": "b1.ch03"}), ("'b1.ch03' is not one of: b1.ch01, b1.ch02",)),
    (lambda d: d["tracks"][0]["plan"][0].update({"from": "nonsense"}), ("not a position",)),
    (lambda d: d["tracks"][0]["plan"].append(dict(d["tracks"][0]["plan"][0])), ("used twice in track 'anna-wound'",)),
    (lambda d: d["tracks"].append(dict(d["tracks"][0])), ("track 'anna-wound' appears twice",)),
    (lambda d: d["tracks"][0].update(plan=[]), ("tracks[0].plan",)),
])
def test_chapter_problems_are_specific(p, constants, mutate, needles):
    data = chapters_act1()
    mutate(data)
    bundle, problems = parse_chapters(dump(data), **ctx_args(p, constants))
    assert bundle is None and has(problems, *needles)


def test_a_track_cannot_change_owner_when_extended(p, constants):
    first, _ = parse_chapters(dump(chapters_act1()), **ctx_args(p, constants))
    data = chapters_act2()
    data["tracks"][0]["entity"] = "jonas"
    assert has(parse_chapters(dump(data), **ctx_args(p, constants, 2, first.tracks))[1], "belongs to 'anna', not 'jonas'")


def test_nonsense_replies_give_one_clear_problem(p, constants):
    for text in ("I could not do that.", "chapters: [unclosed", ""):
        bundle, problems = parse_chapters(text, **ctx_args(p, constants))
        assert bundle is None and problems


# ── scenes of one chapter ───────────────────────────────────────────────────

def scene_args(p, constants, ch=2, prev_day=None, tracks=None):
    base = tracks if tracks is not None else parse_chapters(
        dump(chapters_act1()), **ctx_args(p, constants))[0].tracks
    chapters = {c["id"]: Chapter.model_validate({**c, "act": "b1.act1"}) for c in
                (chapter(1), chapter(2), chapter(3, setting="vestry"), chapter(4))}
    return dict(project=p, chapter=chapters[f"b1.ch{ch:02d}"], prev_day=prev_day, constants=constants,
                tracks_so_far=base, fact_ids={"s-0001"})


def test_valid_scenes_split_into_scenes_timeline_and_refined_tracks(p, constants):
    bundle, problems = parse_scenes(dump(scenes_reply(2)), **scene_args(p, constants))
    assert problems == []
    assert [s.id for s in bundle.scenes] == ["b1.ch02.s1", "b1.ch02.s2"] and bundle.scenes[0].chapter == "b1.ch02"
    assert [(t.id, t.day, t.time) for t in bundle.timeline] == [("b1.ch02.s1", 2, "dusk"), ("b1.ch02.s2", 3, "dusk")]
    wound = next(t for t in bundle.tracks_after if t.id == "anna-wound")
    assert [e.from_ for e in wound.plan] == ["b1.ch02.s2"] and wound.version == 2  # refined: version bumped


def test_untouched_tracks_keep_their_version_and_entries(p, constants):
    bundle, _ = parse_scenes(dump(scenes_reply(2)), **scene_args(p, constants))
    jonas = next(t for t in bundle.tracks_after if t.id == "jonas-knows")
    assert jonas.version == 1 and jonas.plan[0].from_ == "b1.ch01"


def test_restating_a_track_unchanged_does_not_bump_its_version(p, constants):
    data = scenes_reply(2)
    data["tracks"][0]["plan"][0]["from"] = "b1.ch02.s1"
    first, _ = parse_scenes(dump(data), **scene_args(p, constants))
    again, problems = parse_scenes(dump(data), **scene_args(p, constants, tracks=first.tracks_after))
    assert problems == [] and next(t for t in again.tracks_after if t.id == "anna-wound").version == 2


def test_the_pov_character_is_added_to_characters(p, constants):
    data = scenes_reply(2)
    data["scenes"][0]["characters"] = ["jonas"]
    bundle, problems = parse_scenes(dump(data), **scene_args(p, constants))
    assert problems == [] and bundle.scenes[0].characters == ["anna", "jonas"]


@pytest.mark.parametrize("mutate,needles", [
    (lambda d: d["scenes"].pop(), ("needs 2 to 3 scenes, got 1",)),
    (lambda d: d["scenes"].extend([scene(2, 3, 3), scene(2, 4, 3)]), ("needs 2 to 3 scenes, got 4",)),
    (lambda d: d["scenes"][1].update(id="b1.ch02.s9"), ("scenes[1].id is 'b1.ch02.s9', expected 'b1.ch02.s2'",)),
    (lambda d: d["scenes"][0].update(characters=["anna", "nobody"]), ("'nobody' is not in the cast",)),
    (lambda d: d["scenes"][0].update(setting="jonas"), ("'jonas' is a character, expected a place",)),
    (lambda d: d["scenes"][0].update(beats=["only one"]), ("scenes[0].beats",)),
    (lambda d: d["scenes"][0].pop("day"), ("day",)),
    (lambda d: d["scenes"][0].pop("time"), ("time",)),
    (lambda d: d["scenes"][0].update(day=0), ("day",)),
    (lambda d: d["scenes"][0].update(research=["b1-0042"]), ("unknown research fact id(s) b1-0042",)),
    (lambda d: d["scenes"][1].update(day=1), ("day 1 is before day 2 of the previous scene", "flashback: true")),
    (lambda d: d["tracks"][0]["plan"][0].update({"from": "b1.ch02"}), ("is not one of: b1.ch02.s1, b1.ch02.s2",)),
    (lambda d: d["tracks"][0]["plan"][0].update({"from": "b1.ch03.s1"}), ("is not one of: b1.ch02.s1, b1.ch02.s2",)),
    (lambda d: d.pop("tracks"), ("track 'anna-wound' already has planned states in b1.ch02", "restate it at scene level")),
    (lambda d: d["tracks"][0]["plan"][0].update(must_show=False), ("lost a must_show state",)),
])
def test_scene_problems_are_specific(p, constants, mutate, needles):
    data = scenes_reply(2)
    mutate(data)
    bundle, problems = parse_scenes(dump(data), **scene_args(p, constants))
    assert bundle is None and has(problems, *needles)


def test_a_track_may_not_lose_states_in_the_chapter(p, constants):
    # A track that was already refined to two scene-level states in ch02 (for example by an earlier run).
    base = [Track.model_validate({"id": "anna-wound", "entity": "anna", "plan": [
        {"from": "b1.ch02.s1", "value": "scratched"},
        {"from": "b1.ch02.s2", "value": "deep cut, left shoulder; bleeding", "must_show": True}]})]
    problems = parse_scenes(dump(scenes_reply(2)), **scene_args(p, constants, tracks=base))[1]
    assert has(problems, "had 2 state(s) in b1.ch02 but you gave 1")


def test_flashbacks_may_go_back_in_time_without_moving_the_clock(p, constants):
    data = scenes_reply(2)
    data["scenes"][0].update(day=1, flashback=True)  # allowed: starts before the previous chapter ended
    data["scenes"][1].update(day=5)
    bundle, problems = parse_scenes(dump(data), **scene_args(p, constants, prev_day=4))
    assert problems == []


def test_days_must_not_run_backwards_across_chapters(p, constants):
    assert has(parse_scenes(dump(scenes_reply(2)), **scene_args(p, constants, prev_day=9))[1], "day 2 is before day 9")


def test_new_tracks_may_be_created_by_the_scenes(p, constants):
    data = scenes_reply(2)
    data["tracks"].append({"id": "ledger-hidden", "entity": "ledger", "kind": "status",
                           "plan": [{"from": "b1.ch02.s1", "value": "hidden in the vestry"}]})
    bundle, problems = parse_scenes(dump(data), **scene_args(p, constants))
    assert problems == [] and bundle.tracks_after[-1].id == "ledger-hidden" and bundle.tracks_after[-1].version == 1


def test_scene_ids_are_normalised(p, constants):
    data = scenes_reply(2)
    data["scenes"][0]["id"] = "b1.ch2.s1"
    bundle, problems = parse_scenes(dump(data), **scene_args(p, constants))
    assert problems == [] and bundle.scenes[0].id == "b1.ch02.s1" and bundle.timeline[0].id == "b1.ch02.s1"


# ── a setting may be a place, or an object people are inside (a ship) ───────

def test_an_object_such_as_a_ship_may_be_a_setting_but_a_character_may_not():
    from bookforge.bible.models import Constants, Entity
    from bookforge.bible.validate import SETTING_ALSO, _check_entity
    cast = Constants(entities=[Entity(id="anna", kind="character", name="Anna", facts=["f"]), Entity(id="harbor", kind="place", name="Harbor", facts=["f"]),
                               Entity(id="the-kestrel", kind="object", name="The Kestrel", facts=["f"]), Entity(id="guild", kind="group", name="Guild", facts=["f"])])
    from bookforge.bible.validate import entity_map
    entities = entity_map(cast)
    ok: list[str] = []
    for place in ("harbor", "the-kestrel"):
        _check_entity(entities, place, "place", "chapters[0].setting", ok, SETTING_ALSO)
    assert ok == []
    bad: list[str] = []
    _check_entity(entities, "anna", "place", "chapters[1].setting", bad, SETTING_ALSO)
    _check_entity(entities, "guild", "place", "chapters[2].setting", bad, SETTING_ALSO)
    assert "'anna' is a character, expected a place (use one of: harbor, the-kestrel)" in bad[0]
    assert "'guild' is a group, expected a place" in bad[1]


def test_a_wrong_kind_that_has_no_alternative_says_the_cast_lacks_one():
    from bookforge.bible.models import Constants, Entity
    from bookforge.bible.validate import _check_entity, entity_map
    entities = entity_map(Constants(entities=[Entity(id="anna", kind="character", name="Anna", facts=["f"])]))
    problems: list[str] = []
    _check_entity(entities, "anna", "place", "x.setting", problems)
    assert "the cast has no place yet" in problems[0]


def test_the_cast_prompt_says_a_ship_is_a_place():
    from bookforge import prompts
    assert "a ship, train, carriage, house or room that people are inside is a place" in (prompts.PROMPT_DIR / "cast.md").read_text()


# ── every act must create or extend a state track ───────────────────────────

def test_an_act_with_no_state_tracks_is_sent_back_with_a_clear_reason(p, constants):
    for data in ({**chapters_act1(), "tracks": []}, {k: v for k, v in chapters_act1().items() if k != "tracks"}):
        bundle, problems = parse_chapters(dump(data), **ctx_args(p, constants))
        assert bundle is None
        assert any("b1.act1 defines no state tracks" in x and "at least one track" in x for x in problems)


def test_an_act_that_only_extends_an_existing_track_is_fine(p, constants):
    first, _ = parse_chapters(dump(chapters_act1()), **ctx_args(p, constants))
    bundle, problems = parse_chapters(dump(chapters_act2()), **ctx_args(p, constants, 2, first.tracks))
    assert problems == [] and bundle.tracks
