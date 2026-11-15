"""Nothing a redo, a failed check or a new ledger replaces is lost: earlier versions are kept and restorable."""

import pytest
from conftest import RuleLLM
from ledger_structure_fakes import install_ledger, rules
from structure_fakes import ready
from test_ledger_layer import GOOD, dump, prepared, run_ledger

from bookforge.llm import FakeLLMClient

from bookforge import ops, versions
from bookforge.bible import store
from bookforge.errors import BookforgeError
from bookforge.layers import HANDLERS
from bookforge.layers.runner import run


def planned(project):
    p = ready(project)
    install_ledger(p)
    run(p, RuleLLM(rules()), HANDLERS, until="scenes")
    return p


def test_keep_lists_newest_first_and_restore_puts_the_files_back_after_keeping_the_current_ones(project):
    p = planned(project)
    original = store.acts_path(p).read_text(encoding="utf-8")
    name = versions.keep(p, [store.acts_path(p)], "by-hand")
    assert name.endswith("-by-hand") and versions.list_versions(p)[0]["files"] == ["books/b1/acts.yaml"] and versions.keep(p, [p.root / "nope.yaml"], "x") is None
    store.acts_path(p).write_text("acts: []\n", encoding="utf-8")
    done = versions.restore(p, name)
    assert done == ["books/b1/acts.yaml"] and store.acts_path(p).read_text(encoding="utf-8") == original
    assert any(v["reason"] == "before-restore" for v in versions.list_versions(p))  # what was there is kept too
    with pytest.raises(BookforgeError):
        versions.restore(p, "no-such-version")
    with pytest.raises(BookforgeError):
        versions.restore(p, "../../etc")


def test_old_snapshots_beyond_the_limit_are_pruned(project, monkeypatch):
    p = planned(project)
    monkeypatch.setattr(versions, "KEEP", 3)
    names = []
    for i in range(5):
        (p.book_dir / "acts.yaml").write_text(f"acts: [{i}]\n", encoding="utf-8")
        names.append(versions.keep(p, [store.acts_path(p)], f"r{i}"))
    kept = [v["name"] for v in versions.list_versions(p)]
    assert len(kept) == 3 and names[-1] in kept and names[0] not in kept


def test_redoing_a_layer_with_its_followers_keeps_a_copy_of_every_file_it_resets(project):
    p = planned(project)
    ops.redo_layer(p, "acts", "a note", cascade=True)
    [snap] = [v for v in versions.list_versions(p) if v["reason"] == "before-redo-acts"]
    assert {"books/b1/acts.yaml", "books/b1/chapters.yaml", "books/b1/scenes.yaml"} <= set(snap["files"])
    assert store.acts_path(p).exists() and store.chapters_path(p).exists()  # the redo itself deletes nothing
    store.acts_path(p).write_text("acts: []\n", encoding="utf-8")
    versions.restore(p, snap["name"], "books/b1/acts.yaml")
    assert len(store.load_acts(p)) == 2  # one file restored on its own


def test_a_failed_whole_book_check_keeps_the_chapters_it_removes(project):
    from bookforge.errors import LayerError
    from bookforge.layers.structure import _book_chapter_checks
    p = planned(project)
    flat = [c.model_copy(update={"tension": 9}) for c in store.load_chapters(p)] * 2
    flat = [c.model_copy(update={"id": f"b1.ch{i:02d}"}) for i, c in enumerate(flat, 1)]
    with pytest.raises(LayerError):
        _book_chapter_checks(p, flat, store.load_ledger(p))
    assert not store.chapters_path(p).exists()  # a failed run saves nothing...
    assert any(v["reason"] == "chapters-failed-checks" and "books/b1/chapters.yaml" in v["files"] for v in versions.list_versions(p))  # ...but what was there is not lost


def test_a_new_ledger_resets_the_acts_chapters_and_scenes_planned_from_the_old_one_and_keeps_copies(project_with_ledger):
    p = prepared(project_with_ledger)
    p.config.ledger.min_chapters = 4
    run_ledger(p, [GOOD])
    for layer in ("acts", "chapters", "scenes"):  # planned from this ledger
        p.state.set_layer_status(layer, "accepted")
    (p.book_dir / "acts.yaml").write_text("acts:\n  - id: b1.act1\n", encoding="utf-8")
    p.state.set_layer_status("ledger", "pending", "redo")
    p.save_state()
    summary = run(p, FakeLLMClient({"critic": ['{"findings": []}', dump(GOOD)]}), HANDLERS, until="ledger")  # a redo asks the audit again
    assert summary.ran == ["ledger"] and [p.state.layers[l].status for l in ("acts", "chapters", "scenes")] == ["pending"] * 3
    assert p.state.layers["acts"].note == "redo"  # to be planned again, not adopted
    assert "will be planned again from this one" in summary.notes["ledger"]
    assert any(v["reason"] == "before-reset-by-new-ledger" and "books/b1/acts.yaml" in v["files"] for v in versions.list_versions(p))


def test_written_prose_is_never_reset_by_a_new_ledger(project_with_ledger):
    p = prepared(project_with_ledger)
    p.config.ledger.min_chapters = 4
    run_ledger(p, [GOOD])
    p.state.set_layer_status("acts", "accepted")
    final = p.book_dir / "scenes" / "ch01" / "s1" / "final.md"
    final.parent.mkdir(parents=True, exist_ok=True)
    final.write_text("Prose that took a night to write.\n", encoding="utf-8")
    p.state.set_layer_status("ledger", "pending", "redo")
    p.save_state()
    run(p, FakeLLMClient({"critic": ['{"findings": []}', dump(GOOD)]}), HANDLERS, until="ledger")
    assert p.state.layers["acts"].status == "accepted" and final.exists()


def test_acts_planned_for_an_earlier_ledger_are_one_inbox_item_not_five_and_planning_them_again_clears_it(project):
    import json
    from bookforge import inbox
    from bookforge.bible.models import StoryEvent
    p = planned(project)
    assert inbox.stale_acts(p) is None
    ledger = store.load_ledger(p)
    base = dict(once_only=True, after=[], kind="event", weight=2, source="synopsis")
    ledger.events += [StoryEvent(id="e5", text="Anna hides the ledger in the vestry", **base), StoryEvent(id="e6", text="Jonas finds the hiding place", ending=True, **{**base, "after": ["e5"]})]
    store.save_ledger(p, ledger)
    assert inbox.stale_acts(p) == {"missing": ["e5", "e6"], "unknown": []}
    findings = [dict(stage="acts", code=c, severity="hard", message=m, items=i, evidence=[], accepted=False) for c, m, i in [
        ("event_in_no_act", "e5 belongs to no act", ["e5"]), ("event_in_no_act", "e6 belongs to no act", ["e6"]),
        ("resolution_not_in_last_act", "the last act must contain the resolution", ["b1.act2", "e6"]), ("acts_differ_from_capacity", "the acts plan 4 chapters but the estimate is 6", ["b1.act1"]),
        ("sizing_reason_mismatch", "act 2 says weight 16", ["b1.act2"]), ("pov_not_in_text", "a chapter finding of another stage", ["b1.ch02"])]]
    (p.book_dir / "validation").mkdir(parents=True, exist_ok=True)
    (p.book_dir / "validation" / "acts.json").write_text(json.dumps({"stage": "acts", "summary": {}, "findings": findings[:5]}), encoding="utf-8")
    (p.book_dir / "validation" / "chapters.json").write_text(json.dumps({"stage": "chapters", "summary": {}, "findings": [dict(findings[5], stage="chapters")]}), encoding="utf-8")
    items = inbox.collect(p, include_done=False)
    stale = [i for i in items if i["type"] == "acts_stale"]
    assert len(stale) == 1 and stale[0]["blocking"] and stale[0]["actions"] == ["redo_acts"] and "e5, e6" in stale[0]["title"] and "all 5 checks" in stale[0]["why"]
    assert [i["type"] for i in items if i["stage"] == "acts"] == ["acts_stale"] and any(i["type"] == "pov_not_in_text" for i in items)  # other stages' findings stay
    ops.redo_layer(p, "acts", "e5 belongs to act 2", cascade=True)
    assert [p.state.layers[l].status for l in ("acts", "chapters", "scenes")] == ["pending"] * 3
    assert inbox.stale_acts(p) is None and inbox.summary(p)["blocking"] == 0 and inbox.summary(p)["needs_run"] and not any(i["type"] == "acts_stale" for i in inbox.collect(p, include_done=False))  # being planned again: the item is gone
