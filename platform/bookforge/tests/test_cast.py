"""The cast editor: add, edit, delete and rename entities, always checked against the rest of the book and all or nothing."""

import shutil
import subprocess

import pytest
from test_prose_qc import book  # noqa: F401  (fixture)
from test_report_assemble_bench import full  # noqa: F401  (fixture)

from bookforge import cast, rules
from bookforge.bible import store
from bookforge.bible.validate import validate_bible


def snapshot(p):
    return {n: (f.read_bytes() if f.exists() else None) for n, f in (("constants", store.constants_path(p)), ("tracks", store.tracks_path(p)),
                                                                    ("chapters", store.chapters_path(p)), ("scenes", store.scenes_path(p)))}


def git_log(p):
    return subprocess.run(["git", "-C", str(p.root), "log", "--format=%s"], capture_output=True, text=True).stdout


def test_the_overview_counts_where_each_entity_is_used(full):
    over = cast.overview(full)
    by_id = {e["id"]: e for e in over["entities"]}
    assert by_id["anna"]["used"] >= 5 and by_id["vestry"]["used"] >= 1 and not over["shared_bible"]
    kinds = {u["as"] for u in cast.usage(full, "anna")}
    assert {"viewpoint character", "owner"} <= kinds


def test_an_entity_is_added_with_its_facts_and_checked(full):
    added = cast.add(full, "mira-hale", "character", "Mira Hale", ["tall, grey-haired", "keeps the lighthouse"])
    assert added.name == "Mira Hale" and "mira-hale" in {e.id for e in store.load_constants(full).entities}
    assert "you added Mira Hale to the cast" in git_log(full)
    for args, match in ((("anna", "character", "Anna again", ["x"]), "already in the cast"), (("Bad Id", "character", "x", ["x"]), "not a usable id"),
                        (("new-one", "character", "x", []), "at least one fact"), (("new-two", "monster", "x", ["x"]), "kind")):
        before = snapshot(full)
        with pytest.raises(cast.CastError, match=match):
            cast.add(full, *args)
        assert snapshot(full) == before


def test_name_and_facts_can_be_edited_but_not_a_kind_the_book_depends_on(full):
    cast.update(full, "anna", name="Anna Voss-Reil", facts=["grey eyes", "left-handed", "was a clerk"])
    anna = next(e for e in store.load_constants(full).entities if e.id == "anna")
    assert anna.name == "Anna Voss-Reil" and anna.facts[-1] == "was a clerk"
    before = snapshot(full)
    with pytest.raises(cast.CastError, match="inconsistent.*is a place, expected a character"):
        cast.update(full, "anna", kind="place")  # she is the viewpoint of chapters and scenes
    assert snapshot(full) == before
    with pytest.raises(cast.CastError, match="no entity 'nobody'"):
        cast.update(full, "nobody", name="x")


def test_an_entity_nothing_uses_can_be_deleted_and_one_in_use_is_refused_with_where(full):
    cast.add(full, "extra-guard", "character", "A Guard", ["bored"])
    cast.delete(full, "extra-guard")
    assert "extra-guard" not in {e.id for e in store.load_constants(full).entities} and "you removed A Guard from the cast" in git_log(full)
    before = snapshot(full)
    with pytest.raises(cast.CastError) as e:
        cast.delete(full, "anna")
    assert "is still used in" in str(e.value) and "chapter b1.ch01" in str(e.value) and "13 place(s)" in str(e.value)
    assert snapshot(full) == before


def test_a_rename_changes_every_reference_and_leaves_the_book_consistent(full):
    rules.upsert(full, rules.Rule(id="anna-voice", type="character_voice", text="clipped, dry", scope="character", target="anna", severity="warn"))
    used = len(cast.usage(full, "anna"))
    changed = cast.rename(full, "anna", "anna-voss")
    assert changed == used and cast.usage(full, "anna") == []
    assert "anna-voss" in {e.id for e in store.load_constants(full).entities} and "anna" not in {e.id for e in store.load_constants(full).entities}
    assert all(c.pov != "anna" for c in store.load_chapters(full)) and any(c.pov == "anna-voss" for c in store.load_chapters(full))
    assert all("anna" not in s.characters and s.pov != "anna" for s in store.load_scenes(full))
    assert {t.entity for t in store.load_tracks(full)} >= {"anna-voss"} and "anna" not in {t.entity for t in store.load_tracks(full)}
    assert rules.load_rules(full)[0].target == "anna-voss" and validate_bible(full, False) == []
    assert "you renamed anna to anna-voss" in git_log(full)


def test_a_refused_rename_changes_nothing(full):
    before = snapshot(full)
    for new, match in (("jonas", "already in the cast"), ("Not Valid", "not a usable id")):
        with pytest.raises(cast.CastError, match=match):
            cast.rename(full, "anna", new)
    with pytest.raises(cast.CastError, match="no entity 'nobody'"):
        cast.rename(full, "nobody", "someone")
    assert snapshot(full) == before


def test_a_shared_bible_cannot_rename_but_counts_use_across_books(full):
    root = full.root
    shutil.copytree(root / "books/b1/bible", root / "bible")
    shutil.rmtree(root / "books/b1/bible")
    from bookforge.project import Project
    old = Project.open(root, "b1")
    assert cast.overview(old)["shared_bible"] is True and cast.usage(old, "anna")
    with pytest.raises(cast.CastError, match="split-bible"):
        cast.rename(old, "anna", "anna-voss")
