"""Each book has its own bible: a new book starts empty (or with a copy of an earlier book's cast and last states), an older series is split."""

import shutil
import subprocess

import pytest
import yaml
from test_prose_qc import book  # noqa: F401  (fixture)
from test_report_assemble_bench import full  # noqa: F401  (fixture)

from bookforge import books as book_mgmt
from bookforge.bible import store
from bookforge.bible.lookup import state_at
from bookforge.bible.models import PlanEntry, Track
from bookforge.bible_split import split_bible
from bookforge.errors import BookforgeError
from bookforge.project import Project


def add_death(p):
    """The finished b1 gets a status track on which Jonas ends dead."""
    tracks = store.load_tracks(p)
    tracks.append(Track(id="jonas-status", entity="jonas", kind="status", plan=[PlanEntry(**{"from": "b1.ch02", "value": "wounded"}), PlanEntry(**{"from": "b1.ch04", "value": "dead, executed by the guild"})]))
    store.save_tracks(p, tracks)
    return p


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True).stdout


def test_a_new_series_has_a_bible_per_book_and_none_at_its_root(project):
    assert (project.book_dir / "bible" / "constants.yaml").is_file() and not (project.root / "bible").exists()
    assert store.constants_path(project) == project.book_dir / "bible" / "constants.yaml" and not store.shared_bible(project)


def test_an_older_series_keeps_working_on_its_shared_bible_until_it_is_split(full):
    root = full.root
    shutil.copytree(root / "books/b1/bible", root / "bible")
    shutil.rmtree(root / "books/b1/bible")
    old = Project.open(root, "b1")
    assert store.shared_bible(old) and store.constants_path(old) == root / "bible" / "constants.yaml" and store.load_constants(old).entities


def legacy_two_books(full):
    root = full.root
    shutil.copytree(root / "books/b1/bible", root / "bible")
    shutil.rmtree(root / "books/b1/bible")
    from bookforge.state import new_state, save_state
    (root / "books/b2").mkdir()
    save_state(root / "books/b2/state.json", new_state("b2"))
    tracks = yaml.safe_load((root / "bible/tracks.yaml").read_text())
    tracks["tracks"][0]["plan"].append({"from": "b2.ch01", "value": "book two state", "must_show": False})
    tracks["tracks"].append({"id": "b2-only", "entity": "anna", "kind": "other", "version": 1, "observed": [], "plan": [{"from": "b2.ch01", "value": "only book two", "must_show": False}]})
    (root / "bible/tracks.yaml").write_text(yaml.safe_dump(tracks))
    timeline = yaml.safe_load((root / "bible/timeline.yaml").read_text())
    timeline["scenes"].append({"id": "b2.ch01.s1", "day": 1, "time": "dawn"})
    (root / "bible/timeline.yaml").write_text(yaml.safe_dump(timeline))
    return root


def test_splitting_gives_each_book_its_own_copy_filtered_by_book_and_commits_first(full):
    root = legacy_two_books(full)
    summary = split_bible(root)
    assert not (root / "bible").exists() and set(summary) == {"b1", "b2"}
    b1 = Project.open(root, "b1")
    b2 = Project.open(root, "b2")
    assert not store.shared_bible(b1) and [e.id for e in store.load_constants(b1).entities] == [e.id for e in store.load_constants(b2).entities]
    assert all(not e.from_.startswith("b2.") for t in store.load_tracks(b1) for e in t.plan) and "b2-only" not in {t.id for t in store.load_tracks(b1)}
    assert {t.id for t in store.load_tracks(b2)} == {"anna-wound", "b2-only"} or "b2-only" in {t.id for t in store.load_tracks(b2)}
    assert all(e.from_.startswith("b2.") for t in store.load_tracks(b2) for e in t.plan)
    assert [t.id for t in store.load_timeline(b2)] == ["b2.ch01.s1"] and all(t.id.startswith("b1.") for t in store.load_timeline(b1))
    log = git(root, "log", "--format=%s")
    assert "before giving each book its own bible" in log and "each book now has its own bible" in log
    with pytest.raises(BookforgeError, match="already has a bible per book"):
        split_bible(root)


def test_the_cast_of_an_earlier_book_can_be_previewed_with_who_ended_dead(full):
    p = add_death(full)
    preview = book_mgmt.carry_over_preview(p.root, "b1")
    by_id = {e["id"]: e for e in preview["entities"]}
    assert by_id["jonas"]["dead"] and not by_id["jonas"]["suggested"] and by_id["jonas"]["states"][-1]["value"].startswith("dead")
    assert by_id["anna"]["suggested"] and by_id["harbor"]["suggested"] and preview["rules"] >= 1
    assert book_mgmt.looks_dead("the guild executed him") and not book_mgmt.looks_dead("deadline looms") and not book_mgmt.looks_dead("healed; scar remains")


def test_a_new_book_copies_the_cast_it_is_given_and_starts_in_their_last_states(full):
    p = add_death(full)
    b2 = book_mgmt.add_book(p.root, "Book two", "The sequel.", copy_from="b1")
    ids = {e.id for e in store.load_constants(b2).entities}
    assert "anna" in ids and "jonas" not in ids  # the one who ended dead is not suggested
    assert store.load_constants(b2).rules  # the rules of the world come along
    tracks = {t.id: t for t in store.load_tracks(b2)}
    assert tracks["anna-wound"].starts_as == "healed; scar remains" and tracks["anna-wound"].plan == [] and "jonas-status" not in tracks
    # nothing is shared: the first book is untouched and the new one can change a character freely
    assert [e.id for e in store.load_constants(Project.open(p.root, "b1")).entities].count("jonas") == 1
    again = book_mgmt.add_book(p.root, "Book three", "Another.", copy_from="b1", copy_entities=["anna", "jonas"])
    assert {"anna", "jonas"} <= {e.id for e in store.load_constants(again).entities} and {t.id for t in store.load_tracks(again)} >= {"jonas-status"}
    ledger = yaml.safe_load((p.root / "ledger.yaml").read_text())
    assert "b1" in ledger["end_of_book_states"] and "executed" in ledger["end_of_book_states"]["b1"] and "How b1 ended" in ledger["end_of_book_states"]["b1"]
    with pytest.raises(BookforgeError, match="no entity"):
        book_mgmt.add_book(p.root, "Bad", "x", copy_from="b1", copy_entities=["nobody"])
    with pytest.raises(BookforgeError, match="no book 'b9'"):
        book_mgmt.add_book(p.root, "Bad", "x", copy_from="b9")


def test_a_state_carried_in_holds_until_the_first_entry_of_the_new_book():
    t = Track(id="mara-status", entity="mara", kind="status", starts_as="dead", plan=[])
    assert [s.value for s in state_at([t], "b2.ch01.s1")] == ["dead"] and state_at([t], "b2.ch01.s1")[0].since == "start of the book"
    t2 = Track(id="mara-status", entity="mara", kind="status", starts_as="dead", plan=[PlanEntry(**{"from": "b2.ch05", "value": "alive again, a clone"})])
    assert state_at([t2], "b2.ch04.s1")[0].value == "dead" and state_at([t2], "b2.ch05.s1")[0].value == "alive again, a clone"
    with pytest.raises(Exception, match="at least one plan entry"):
        Track(id="x", entity="mara", kind="status", plan=[])  # nothing to hold and nothing carried in: invalid


def test_the_planner_sees_the_carried_in_state(full):
    from bookforge.layers.structure import tracks_digest
    t = Track(id="mara-status", entity="mara", kind="status", starts_as="dead", plan=[])
    assert "starts as (carried in from an earlier book): dead" in tracks_digest([t])
