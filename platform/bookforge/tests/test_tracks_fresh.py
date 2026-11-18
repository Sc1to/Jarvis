"""A chapters plan starts from earlier layers and books, never from its own previous output: no state outlives the chapter it was written for."""

from conftest import RuleLLM
from ledger_structure_fakes import install_ledger, rules
from structure_fakes import ready

from bookforge.bible import store
from bookforge.bible.models import PlanEntry, Track
from bookforge.layers import HANDLERS
from bookforge.layers.runner import run


def entry(frm, value="v"):
    return PlanEntry(**{"from": frm, "value": value})


def test_without_book_plan_keeps_other_books_and_drops_empty_tracks():
    tracks = [Track(id="old-only", entity="anna", kind="status", plan=[entry("b1.ch25"), entry("b1.ch33")]),
              Track(id="shared", entity="anna", kind="status", plan=[entry("b1.ch02"), entry("b0.ch30")])]
    out = store.tracks_without_book_plan(tracks, "b1")
    assert [t.id for t in out] == ["shared"] and [e.from_ for e in out[0].plan] == ["b0.ch30"]
    assert [e.from_ for e in tracks[1].plan] == ["b1.ch02", "b0.ch30"]  # the input is not changed


def test_orphan_entries_are_pruned():
    tracks = [Track(id="t", entity="anna", kind="status", plan=[entry("b1.ch01"), entry("b1.ch25.s2"), entry("b0.ch30")])]
    out, n = store.prune_orphan_entries(tracks, {"b1.ch01", "b1.ch02"}, "b1")
    assert n == 1 and [e.from_ for e in out[0].plan] == ["b1.ch01", "b0.ch30"]


def test_a_chapters_plan_over_a_longer_old_plan_leaves_no_ghost_states(project):
    p = ready(project)
    install_ledger(p)
    store.save_tracks(p, [Track(id="ghost-track", entity="anna", kind="status", plan=[entry("b1.ch25"), entry("b1.ch33")]),
                          Track(id="anna-wound", entity="anna", kind="physical", plan=[entry("b1.ch04", "an old state"), entry("b1.ch26", "a very old one")]),
                          Track(id="inherited", entity="anna", kind="status", plan=[entry("b0.ch09", "from the book before")])])
    summary = run(p, RuleLLM(rules()), HANDLERS, until="chapters")
    assert summary.ran == ["acts", "chapters"], summary.detail
    ids = {c.id for c in store.load_chapters(p)}
    tracks = {t.id: t for t in store.load_tracks(p)}
    assert "ghost-track" not in tracks
    assert all(e.from_.rsplit(".", 1)[0] in ids or e.from_ in ids or e.from_.startswith("b0.") for t in tracks.values() for e in t.plan)
    assert [e.from_ for e in tracks["inherited"].plan] == ["b0.ch09"]
    assert all(e.value != "a very old one" for e in tracks["anna-wound"].plan)
