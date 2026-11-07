"""Pausing and resuming a run: where the next Run continues, scene order, and the checks an interrupted scene keeps."""

from bookforge import cancel, ops, scenefiles
from bookforge.bible import store
from bookforge.layers import HANDLERS
from bookforge.layers.prose import order_for_run
from bookforge.layers.runner import run
from bookforge.state import Item
from conftest import RuleLLM
from qc_fakes import CRITIC, critic
from test_prose_qc import SID, book, first_scene, go, kinds, qc_rules  # noqa: F401  (book is a fixture)


def _scenes(project):
    return store.load_scenes(project)


def _set(project, sid, status):
    project.state.items[sid] = Item(status=status)
    project.save_state()


def _ids(project, **kw):
    first = store.load_chapters(project)[0].id
    return [s.id for s in order_for_run(project, _scenes(project), True, first)]


def test_flagged_scenes_are_retried_after_the_scenes_still_to_do(book):
    ids = [s.id for s in _scenes(book)]
    _set(book, ids[0], "flagged")
    assert _ids(book)[-1] == ids[0] and _ids(book)[0] == ids[1]


def test_an_interrupted_scene_comes_first(book):
    ids = [s.id for s in _scenes(book)]
    _set(book, ids[0], "flagged")
    _set(book, ids[-1], "drafted")
    assert _ids(book)[0] == ids[-1] and _ids(book)[-1] == ids[0]


def test_inline_keeps_plain_book_order(book):
    ids = [s.id for s in _scenes(book)]
    _set(book, ids[0], "flagged")
    book.config.layers["prose"].retry_flagged = "inline"
    assert _ids(book) == ids


def test_the_resume_point_names_the_scene_and_why(book):
    ids = [s.id for s in _scenes(book)]
    point = ops.resume_point(book)
    assert point["layer"] == "prose" and point["scene"] == ids[0] and point["reason"] == "next"
    _set(book, ids[0], "accepted")
    _set(book, ids[1], "drafted")
    point = ops.resume_point(book)
    assert point["scene"] == ids[1] and point["reason"] == "interrupted" and point["accepted"] == 1
    assert ids[1] in ops.resume_text(point) and "interrupted" in ops.resume_text(point)
    for sid in ids:
        _set(book, sid, "flagged")
    assert ops.resume_point(book)["reason"] == "flagged"


def test_a_paused_scene_keeps_its_drafts_and_passed_checks(book):
    def pause(messages):
        raise cancel.Cancelled()

    first = RuleLLM([(CRITIC, pause)] + qc_rules())
    assert go(book, first).stopped == "cancelled"
    assert scenefiles.progress_path(book, SID).exists()
    assert book.state.items[SID].status == "drafted"

    again = RuleLLM(qc_rules())
    go(book, again)
    seq = first_scene(again)
    assert "draft" not in seq and "judge" not in seq and "continuity" not in seq  # drafts, choice and clean continuity were kept
    assert seq == ["critic", "summary", "extract"]
    assert not scenefiles.progress_path(book, SID).exists()  # removed once the scene is settled
    assert book.state.items[SID].status == "accepted"
