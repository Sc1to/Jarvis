"""Model replies with unquoted colons in their text: repaired, or refused with the line named."""

import pytest
import yaml

from bookforge.bible.validate import load_reply_yaml, parse_acts, quote_plain_colons

BROKEN_ACTS = """acts:
  - id: b1.act1
    title: The ledger: found
    summary: Anna finds the ledger in the vestry: a book of names. She hides it, and then: she learns the cost.
    purpose: setup: who Anna is and what she risks
    turning_point: She crosses out the first name: and forgets a year.
    chapter_count: 8
"""


def test_unquoted_colons_are_repaired_and_the_text_is_kept_whole():
    data, error = load_reply_yaml(BROKEN_ACTS)
    assert error is None
    act = data["acts"][0]
    assert act["title"] == "The ledger: found"
    assert act["summary"].endswith("then: she learns the cost.")
    assert act["turning_point"] == "She crosses out the first name: and forgets a year."
    assert act["chapter_count"] == 8 and act["id"] == "b1.act1"


def test_valid_yaml_is_never_touched():
    good = 'acts:\n  - id: b1.act1\n    title: "A: B"\n    summary: plain text\n    chapter_count: 3\n'
    assert load_reply_yaml(good) == (yaml.safe_load(good), None)


def test_quotes_and_backslashes_inside_a_repaired_value_survive():
    data, error = load_reply_yaml('a:\n  - note: She said "wait": then left, path C:\\\\dir\n')
    assert error is None and data["a"][0]["note"] == 'She said "wait": then left, path C:\\\\dir'


def test_list_items_and_values_that_end_in_a_colon_are_repaired():
    data, error = load_reply_yaml("scenes:\n  - purpose: Anna decides what to do next:\n    beats:\n      - one\n")
    assert error is None and data["scenes"][0]["purpose"] == "Anna decides what to do next:"


def test_quoted_blocks_and_flow_values_are_left_alone():
    text = "a:\n  - x: 'one: two'\n    y: [a, b]\n    z: |\n      block: text\n"
    assert quote_plain_colons(text) == text


def test_an_unrepairable_reply_names_the_line_so_the_correction_can_work():
    data, error = load_reply_yaml("acts:\n  - id: b1.act1\n   title: bad indent\n    summary: x\n")
    assert data is None and "not valid YAML" in error and "at line" in error and "double quotes" in error


def test_a_whole_acts_reply_with_colons_now_parses(project):
    acts, problems = parse_acts(BROKEN_ACTS, project)
    assert not [p for p in problems if "YAML" in p]


def test_text_inside_a_block_scalar_is_never_rewritten():
    text = "a:\n  - note: broken: here\n    body: |\n      keep: this: as it is\n      and: this\n    after: also: fixed\n"
    data, error = load_reply_yaml(text)
    assert error is None
    item = data["a"][0]
    assert item["note"] == "broken: here" and item["after"] == "also: fixed"
    assert item["body"] == "keep: this: as it is\nand: this\n"


# ── valid YAML that is not the text the model meant ─────────────────────────

def test_a_beat_with_a_colon_is_read_as_the_sentence_it_is():
    from bookforge.bible.models import Scene
    data, error = load_reply_yaml("""scene:
  id: b1.ch11.s1
  purpose: Anna decides
  pov: anna
  setting: harbor
  characters: [anna]
  beats:
    - Anna reaches the vestry
    - Jonas confronts her: she lies about the ledger
    - She leaves
""")
    assert error is None
    assert data["scene"]["beats"][1] == {"Jonas confronts her": "she lies about the ledger"}  # what YAML makes of it
    scene = Scene.model_validate(data["scene"])
    assert scene.beats[1] == "Jonas confronts her: she lies about the ledger"


def test_numbers_and_dates_become_text_where_text_is_expected():
    from bookforge.bible.models import Act, TimelineEntry
    data, _ = load_reply_yaml("id: b1.act1\ntitle: 1883\nsummary: s\npurpose: p\nturning_point: t\nchapter_count: 3\n")
    assert Act.model_validate(data).title == "1883"
    data, _ = load_reply_yaml("id: b1.ch01.s1\nday: 1\ntime: dusk\ndate: 1883-04-12\ntravel: 3\n")
    entry = TimelineEntry.model_validate(data)
    assert entry.date == "1883-04-12" and entry.travel == "3"


def test_a_mapping_with_several_keys_or_a_nested_value_is_still_an_error():
    from pydantic import ValidationError
    from bookforge.bible.models import Scene
    base = {"id": "b1.ch01.s1", "purpose": "p", "pov": "anna", "setting": "harbor", "characters": ["anna"]}
    for bad in ({"a": "b", "c": "d"}, {"a": ["b", "c"]}, ["x"]):
        with pytest.raises(ValidationError):
            Scene.model_validate({**base, "beats": ["fine", bad]})


def test_plain_sentences_and_empty_values_are_untouched():
    from bookforge.bible.models import as_text
    assert as_text("plain: text here") == "plain: text here" and as_text(None) is None and as_text(True) is True
    assert as_text({"only key": None}) == "only key:"


def test_a_text_field_given_the_wrong_shape_says_what_it_got_and_how_to_fix_it():
    from pydantic import ValidationError
    from bookforge.bible.models import Scene, problems_from
    base = {"id": "b1.ch01.s1", "purpose": "p", "pov": "anna", "setting": "harbor", "characters": ["anna"]}
    with pytest.raises(ValidationError) as e:
        Scene.model_validate({**base, "beats": ["fine", {"a": "b", "c": "d"}]})
    [problem] = problems_from(e.value)
    assert problem == "beats.1: must be one piece of text but is a mapping (key: value); write it as a single sentence inside double quotes"
