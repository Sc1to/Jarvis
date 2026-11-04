"""Manual Bible Workshop edits: validators, confirm-before-save, and downstream-parser compatibility."""

import json
import os
import sys

import pytest
from fastapi import HTTPException
from git import Repo

WRITER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, WRITER_DIR)

BOOK = "book1"

ACT_TEXT = """### Chapter 1 — Arrival
**Act:** 1.1
**Entry:** Hamid at the harbour.
**Exit:** Hamid meets Tomás.

Summary.

### Chapter 2 — The Letter
**Act:** 1.2
**Entry:** Hamid meets Tomás.
**Exit:** Hamid reads the letter.

Summary.
"""

BRIEF = """## Location
Harbour, dawn.

## Mood
Tense.

## POV Character
Hamid

## Characters Present
- Hamid

## Scene Beats
""" + "\n".join(f"{i}. Beat {i}" for i in range(1, 13)) + """

## Key Dialogue Points
- none

## Sensory & Atmosphere Notes
- gulls

## Entry / Exit State
- Entry: Hamid at dock
- Exit: Hamid has the letter
"""


def plan(start=1, n=2, seed="None", setting="Harbour", pov="Hamid"):
    out = "## Chapter Developments\n1. x\n\n"
    for i in range(start, start + n):
        out += (f"### Scene {i} — Title {i}\n**Chapter:** 1 | **Setting:** {setting} | **POV:** {pov}\n"
                f"**Entry:** a{i}\n**Exit:** b{i}\n**Plants:** {seed}\n\n")
    return out


@pytest.fixture
def book(tmp_path, monkeypatch):
    import db
    monkeypatch.setattr(db, "DATA_ROOT", str(tmp_path))
    d = tmp_path / BOOK
    d.mkdir(parents=True)
    Repo.init(d)
    return d


def _v():
    from routes import bible_edit
    return bible_edit


# ── Pure validators ───────────────────────────────────────────────────────────

def test_act_counts_chapters_and_matches_downstream_parser():
    be = _v()
    from routes import phase1
    r = be.validate_act(ACT_TEXT, expected_start=1)
    assert r["ok"] and r["counts"] == {"chapters": 2}
    assert r["counts"]["chapters"] == len(phase1._parse_chapters(ACT_TEXT))


def test_act_rejects_zero_chapters_gaps_wrong_start_and_unparseable_headers():
    be = _v()
    assert not be.validate_act("just prose", expected_start=1)["ok"]
    assert not be.validate_act(ACT_TEXT.replace("Chapter 2", "Chapter 3"), expected_start=1)["ok"]
    assert not be.validate_act(ACT_TEXT, expected_start=5)["ok"]
    broken = ACT_TEXT.replace("### Chapter 2 — The Letter", "### Chapter 2: The Letter")
    r = be.validate_act(broken, expected_start=1)
    assert not r["ok"]  # header the chapter-list parser would silently drop


def test_chapter_plan_counts_scenes_and_checks_numbering():
    be = _v()
    kw = dict(chapter=1, expected_start=1, next_chapter_start=None, seed_ids=set(), entity_names={"Harbour", "Hamid"})
    r = be.validate_chapter_plan(plan(), **kw)
    assert r["ok"] and r["counts"]["scenes"] == 2 and not r["warnings"]
    assert not be.validate_chapter_plan(plan(start=3), **kw)["ok"]
    assert not be.validate_chapter_plan("no scenes", **kw)["ok"]
    r = be.validate_chapter_plan(plan(), **{**kw, "next_chapter_start": 9})
    assert not r["ok"] and "already locked" in r["errors"][0]


def test_chapter_plan_seed_ids_must_exist_and_entities_only_warn():
    be = _v()
    kw = dict(chapter=1, expected_start=1, next_chapter_start=None, entity_names={"Harbour", "Hamid"})
    assert be.validate_chapter_plan(plan(seed="SEED_001"), seed_ids={"SEED_001"}, **kw)["ok"]
    bad = be.validate_chapter_plan(plan(seed="SEED_01"), seed_ids={"SEED_001"}, **kw)
    assert not bad["ok"] and "SEED_01" in bad["errors"][0]
    warn = be.validate_chapter_plan(plan(setting="Atlantis"), seed_ids=set(), **kw)
    assert warn["ok"] and any("Atlantis" in w for w in warn["warnings"])


def test_scene_brief_sections():
    be = _v()
    r = be.validate_scene_brief(BRIEF)
    assert r["ok"] and r["counts"]["sections"] == 8 and r["counts"]["beats"] == 12
    no_beats = BRIEF.replace("## Scene Beats", "## Beats")
    assert not be.validate_scene_brief(no_beats)["ok"]
    no_exit = BRIEF.replace("- Exit: Hamid has the letter", "")
    assert not be.validate_scene_brief(no_exit)["ok"]
    few = be.validate_scene_brief(BRIEF.replace("11. Beat 11\n12. Beat 12", ""))
    assert few["ok"] and few["warnings"]  # beat count is advisory


def test_tier2_counts_acts():
    be = _v()
    r = be.validate_tier(2, "### Act 1 — A\ntext\n### Act 2 — B\ntext\n### Act 3 — C\n")
    assert r["ok"] and r["counts"]["acts"] == 3
    assert not be.validate_tier(2, "no acts here")["ok"]
    assert be.validate_tier(1, "word " * 80)["ok"]


# ── Endpoints: confirm-before-save, state guards ─────────────────────────────

def _seed_book(book):
    (book / "tier3").mkdir()
    (book / "tier3" / "status.json").write_text(json.dumps({"acts": [
        {"act": 1, "title": "One", "approved": False, "chapters": []}]}))
    (book / "tier4").mkdir()
    (book / "tier4" / "status.json").write_text(json.dumps({"chapters": [
        {"number": 1, "title": "Arrival", "approved": False},
        {"number": 2, "title": "Locked", "approved": False, "scenes": [
            {"number": 3, "title": "x", "approved": False}]},
    ]}))


def test_save_requires_confirmation_and_validates(book):
    be = _v()
    _seed_book(book)
    body = dict(kind="act", act=1, content=ACT_TEXT.replace("\n", "\r\n"))
    with pytest.raises(HTTPException) as e:
        be.save_edit(BOOK, be.SaveBody(**body))
    assert e.value.status_code == 400
    assert not (book / "tier3" / "act_1.md").exists()

    preview = be.validate_edit(BOOK, be.EditTarget(**body))
    assert preview["counts"]["chapters"] == 2
    assert not (book / "tier3" / "act_1.md").exists()  # dry run writes nothing

    res = be.save_edit(BOOK, be.SaveBody(**body, confirmed=True))
    assert res["ok"]
    assert (book / "tier3" / "act_1.md").read_text() == ACT_TEXT  # CRLF normalised, wording untouched

    with pytest.raises(HTTPException) as e:
        be.save_edit(BOOK, be.SaveBody(kind="act", act=1, content="### Chapter 1 - ok\n### Chapter 5 - gap\n", confirmed=True))
    assert e.value.status_code == 422
    assert (book / "tier3" / "act_1.md").read_text() == ACT_TEXT  # failed save leaves file intact


def test_saved_chapter_plan_locks_with_matching_scene_count(book):
    be = _v()
    from routes import phase1
    _seed_book(book)
    text = plan(start=1, n=2)
    res = be.save_edit(BOOK, be.SaveBody(kind="chapter", chapter=1, content=text, confirmed=True))
    assert res["report"]["counts"]["scenes"] == 2
    assert phase1.approve_tier4_chapter(BOOK, phase1.ApproveChapterBody(chapter=1, content=res["content"]))["scenes"] == 2
    status = json.load(open(book / "tier4" / "status.json"))
    assert [s["number"] for s in status["chapters"][0]["scenes"]] == [1, 2]


def test_locked_chapter_and_approved_tier_cannot_be_edited(book):
    be = _v()
    _seed_book(book)
    with pytest.raises(HTTPException) as e:
        be.save_edit(BOOK, be.SaveBody(kind="chapter", chapter=2, content=plan(start=3), confirmed=True))
    assert e.value.status_code == 409
    (book / "tiers.json").write_text(json.dumps([{"content": "x", "approved": True}] + [{"content": None, "approved": False}] * 3))
    with pytest.raises(HTTPException) as e:
        be.save_edit(BOOK, be.SaveBody(kind="tier", tier=1, content="word " * 80, confirmed=True))
    assert e.value.status_code == 409


def test_error_text_and_empty_refused(book):
    be = _v()
    _seed_book(book)
    for bad in ("", "⚠ Connection error — is the server running?"):
        with pytest.raises(HTTPException) as e:
            be.validate_edit(BOOK, be.EditTarget(kind="act", act=1, content=bad))
        assert e.value.status_code == 422


def test_scene_save_clears_stale_qa(book):
    be = _v()
    from routes import phase1
    _seed_book(book)
    qa = phase1._tier4_scene_qa_path(BOOK, 2, 3)
    open(qa, "w").write("{}")
    be.save_edit(BOOK, be.SaveBody(kind="scene", chapter=2, scene=3, content=BRIEF, confirmed=True))
    assert os.path.exists(phase1._tier4_scene_path(BOOK, 2, 3))
    assert not os.path.exists(qa)
