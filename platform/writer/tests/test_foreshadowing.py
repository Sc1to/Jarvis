"""Foreshadowing seed catalog: module tests, Writer/QA context wiring, chapter-approval status flip."""

import asyncio
import json
import os
import sys

import pytest
from git import Repo

WRITER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, WRITER_DIR)

BOOK = "book1"


@pytest.fixture
def book(tmp_path, monkeypatch):
    import db
    monkeypatch.setattr(db, "DATA_ROOT", str(tmp_path))
    book_dir = tmp_path / BOOK
    book_dir.mkdir(parents=True)
    Repo.init(book_dir)
    return book_dir


# ── Module: read/write/normalise/queries ────────────────────────────────────────

def test_normalise_drops_malformed_seeds_and_fills_defaults(book):
    import foreshadowing
    data = foreshadowing.write(BOOK, {"seeds": [
        {"id": "SEED_001", "description": "A watch.", "plant_act_range": {"from": 1, "to": 2}, "payoff_act": 3},
        {"id": "", "description": "no id"},
        {"id": "SEED_002", "description": "bad range"},
    ]})
    assert [s["id"] for s in data["seeds"]] == ["SEED_001"]
    assert data["seeds"][0]["status"] == "unplanted"
    assert data["seeds"][0]["planted_at"] is None
    assert data["seeds"][0]["resolved_at"] is None


def test_seeds_open_for_planting_and_resolution(book):
    import foreshadowing
    foreshadowing.write(BOOK, {"seeds": [
        {"id": "SEED_001", "description": "a", "plant_act_range": {"from": 1, "to": 2}, "payoff_act": 3, "status": "unplanted"},
        {"id": "SEED_002", "description": "b", "plant_act_range": {"from": 2, "to": 3}, "payoff_act": 4, "status": "unplanted"},
        {"id": "SEED_003", "description": "c", "plant_act_range": {"from": 1, "to": 1}, "payoff_act": 2, "status": "planted"},
        {"id": "SEED_004", "description": "d", "plant_act_range": {"from": 1, "to": 1}, "payoff_act": 2, "status": "resolved"},
    ]})
    assert [s["id"] for s in foreshadowing.seeds_open_for_planting(BOOK, 1)] == ["SEED_001"]
    assert {s["id"] for s in foreshadowing.seeds_open_for_planting(BOOK, 2)} == {"SEED_001", "SEED_002"}
    assert [s["id"] for s in foreshadowing.seeds_open_for_resolution(BOOK, 2)] == ["SEED_003"]
    assert foreshadowing.seeds_open_for_resolution(BOOK, 4) == []  # SEED_004 already resolved


def test_mark_planted_and_resolved(book):
    import foreshadowing
    foreshadowing.write(BOOK, {"seeds": [
        {"id": "SEED_001", "description": "a", "plant_act_range": {"from": 1, "to": 2}, "payoff_act": 3},
    ]})
    foreshadowing.mark_planted(BOOK, ["SEED_001"], chapter=5, act=2)
    seed = foreshadowing.seed_by_id(BOOK, "SEED_001")
    assert seed["status"] == "planted"
    assert seed["planted_at"] == {"chapter": 5, "act": 2}

    foreshadowing.mark_resolved(BOOK, ["SEED_001"], chapter=14, act=3)
    seed = foreshadowing.seed_by_id(BOOK, "SEED_001")
    assert seed["status"] == "resolved"
    assert seed["resolved_at"] == {"chapter": 14, "act": 3}


def test_mark_planted_ignores_already_planted(book):
    import foreshadowing
    foreshadowing.write(BOOK, {"seeds": [
        {"id": "SEED_001", "description": "a", "plant_act_range": {"from": 1, "to": 2}, "payoff_act": 3,
         "status": "planted", "planted_at": {"chapter": 1, "act": 1}},
    ]})
    foreshadowing.mark_planted(BOOK, ["SEED_001"], chapter=9, act=2)
    seed = foreshadowing.seed_by_id(BOOK, "SEED_001")
    assert seed["planted_at"] == {"chapter": 1, "act": 1}  # unchanged — already planted


# ── Prompt regression guards ─────────────────────────────────────────────────────

def test_tier4_prompt_requires_developments_and_constrains_forward_context():
    from routes.phase1 import TIER_INSTRUCTIONS
    prompt = TIER_INSTRUCTIONS[3]
    assert "## Chapter Developments" in prompt
    assert "never construct a scene because a future chapter needs a clue" in prompt
    assert "continuity only" in prompt
    assert "**Plants:**" in prompt and "**Resolves:**" in prompt


def test_foreshadowing_seeds_prompt_requires_plant_only_wording():
    from routes.phase1 import FORESHADOWING_SEEDS_SYSTEM
    assert "WITHOUT plot context" in FORESHADOWING_SEEDS_SYSTEM


# ── Tier 4 approval parsing (Plants:/Resolves:) ──────────────────────────────────

def test_parse_tier4_scenes_extracts_seed_assignments():
    from routes.phase1 import _parse_tier4_scenes
    content = (
        "## Chapter Developments\n1. Something happens.\n\n"
        "### Scene 1 — Arrival\n"
        "**Chapter:** 1 | **Setting:** Docks | **POV:** Mary\n"
        "**Entry:** She arrives.\n**Exit:** She has the key.\n"
        "**Plants:** SEED_001, SEED_002\n\n"
        "Mary arrives at the docks.\n\n"
        "### Scene 2 — Talk\n"
        "**Chapter:** 1 | **Setting:** Docks | **POV:** Mary\n"
        "**Entry:** She has the key.\n**Exit:** She knows the plan.\n"
        "**Resolves:** SEED_001\n\n"
        "They talk."
    )
    scenes = _parse_tier4_scenes(content)
    assert scenes[0]["plants"] == ["SEED_001", "SEED_002"]
    assert scenes[0]["resolves"] == []
    assert scenes[1]["plants"] == []
    assert scenes[1]["resolves"] == ["SEED_001"]


def test_parse_tier4_scenes_no_seed_lines_is_empty():
    from routes.phase1 import _parse_tier4_scenes
    content = "### Scene 1 — Arrival\n**Chapter:** 1\n**Entry:** x\n**Exit:** y\n\nSummary."
    scenes = _parse_tier4_scenes(content)
    assert scenes[0]["plants"] == [] and scenes[0]["resolves"] == []


# ── Writer / QA context wiring ────────────────────────────────────────────────────

def test_writer_and_qa_receive_assigned_seeds(book, monkeypatch):
    import db
    import foreshadowing
    from routes import phase3

    (book / "tier4").mkdir()
    (book / "tier4" / "chapter_01.md").write_text("### Scene 1 — Arrival\nMary arrives.")

    foreshadowing.write(BOOK, {"seeds": [
        {"id": "SEED_001", "description": "Establish the silver watch.",
         "plant_act_range": {"from": 1, "to": 1}, "payoff_act": 2},
    ]})

    settings = {
        "agent_writer_agent_provider": "p", "agent_writer_agent_model": "m",
        "agent_qa_agent_provider": "p", "agent_qa_agent_model": "m",
        "agent_bible_agent_provider": "p", "agent_bible_agent_model": "m",
    }
    monkeypatch.setattr(db, "get_setting", lambda k: settings.get(k))
    monkeypatch.setattr(db, "append_job_log", lambda *a: None)

    captured = {}

    async def fake_call(provider, model, messages, system, user_id="local", json_mode=False):
        if system == phase3.SCENE_PLANNER_SYSTEM:
            return json.dumps([{"scene": 1, "brief": "b", "entry_state": "", "exit_state": "e",
                                 "plants": ["SEED_001"], "resolves": []}])
        if system == phase3.QA_SYSTEM:
            captured["qa_user"] = messages[0]["content"]
            return json.dumps({"pass": True, "issues": [], "notes": "ok"})
        captured["writer_prompt"] = messages[0]["content"]
        return "Some prose."

    monkeypatch.setattr(phase3, "_call", fake_call)

    events = []

    async def emit(ev):
        events.append(ev)

    asyncio.run(phase3._write_chapter_core(BOOK, 1, "local", emit, lambda m: None, auto=False))

    assert "## Foreshadowing for this scene" in captured["writer_prompt"]
    assert "Establish the silver watch." in captured["writer_prompt"]
    assert "plant, without drawing attention to it" in captured["writer_prompt"].lower()

    assert "## Foreshadowing assigned to this scene" in captured["qa_user"]
    assert "Establish the silver watch." in captured["qa_user"]


# ── Chapter-approval status flip (deterministic) ──────────────────────────────────

def test_approve_chapter_flips_seed_status_and_commits_file(book, monkeypatch):
    import db
    import foreshadowing
    from routes import phase3

    (book / "tier3").mkdir()
    (book / "tier3" / "status.json").write_text(json.dumps({
        "acts": [{"act": 1, "title": "Act 1", "approved": True, "chapters": [{"number": 1, "title": "Ch 1"}]}]
    }))
    (book / "tier4").mkdir()
    (book / "tier4" / "status.json").write_text(json.dumps({
        "chapters": [{"number": 1, "title": "Ch 1", "scenes": [
            {"number": 1, "title": "Arrival", "approved": True, "plants": ["SEED_001"], "resolves": []},
        ]}]
    }))
    foreshadowing.write(BOOK, {"seeds": [
        {"id": "SEED_001", "description": "Establish the watch.",
         "plant_act_range": {"from": 1, "to": 1}, "payoff_act": 2},
    ]})
    (book / "chapter_01.md").write_text("# Chapter 1\n\n## Scene 1\n\nMary arrives.")
    (book / "chapter_01_meta.json").write_text(json.dumps({
        "chapter": 1, "status": "written", "scenes": [{"scene": 1, "qa_issues": []}],
    }))
    Repo(book).index.add(["tier3/status.json", "tier4/status.json", foreshadowing.FILE_NAME,
                          "chapter_01.md", "chapter_01_meta.json"])
    Repo(book).index.commit("init")

    monkeypatch.setattr(db, "get_setting", lambda k: {
        "agent_bible_updater_provider": "p", "agent_bible_updater_model": "m",
    }.get(k))

    async def fake_call(provider, model, messages, system, user_id="local", json_mode=False):
        return "{}"

    monkeypatch.setattr(phase3, "_call", fake_call)

    asyncio.run(phase3._approve_chapter_bg(BOOK, 1, "local", lambda m: None))

    seed = foreshadowing.seed_by_id(BOOK, "SEED_001")
    assert seed["status"] == "planted"
    assert seed["planted_at"] == {"chapter": 1, "act": 1}

    commit = Repo(book).head.commit
    assert foreshadowing.FILE_NAME in commit.stats.files


def test_approve_chapter_skips_seed_flagged_by_qa(book, monkeypatch):
    """A scene QA flagged with an unresolved foreshadowing error doesn't get its
    assigned seed marked planted just because the chapter itself was approved."""
    import db
    import foreshadowing
    from routes import phase3

    (book / "tier3").mkdir()
    (book / "tier3" / "status.json").write_text(json.dumps({
        "acts": [{"act": 1, "title": "Act 1", "approved": True, "chapters": [{"number": 1, "title": "Ch 1"}]}]
    }))
    (book / "tier4").mkdir()
    (book / "tier4" / "status.json").write_text(json.dumps({
        "chapters": [{"number": 1, "title": "Ch 1", "scenes": [
            {"number": 1, "title": "Arrival", "approved": True, "plants": ["SEED_001"], "resolves": []},
        ]}]
    }))
    foreshadowing.write(BOOK, {"seeds": [
        {"id": "SEED_001", "description": "Establish the watch.",
         "plant_act_range": {"from": 1, "to": 1}, "payoff_act": 2},
    ]})
    (book / "chapter_01.md").write_text("# Chapter 1\n\n## Scene 1\n\nMary arrives.")
    (book / "chapter_01_meta.json").write_text(json.dumps({
        "chapter": 1, "status": "written",
        "scenes": [{"scene": 1, "qa_issues": [{"type": "foreshadowing", "severity": "error", "description": "not planted"}]}],
    }))
    Repo(book).index.add(["tier3/status.json", "tier4/status.json", foreshadowing.FILE_NAME,
                          "chapter_01.md", "chapter_01_meta.json"])
    Repo(book).index.commit("init")

    monkeypatch.setattr(db, "get_setting", lambda k: {
        "agent_bible_updater_provider": "p", "agent_bible_updater_model": "m",
    }.get(k))

    async def fake_call(provider, model, messages, system, user_id="local", json_mode=False):
        return "{}"

    monkeypatch.setattr(phase3, "_call", fake_call)

    asyncio.run(phase3._approve_chapter_bg(BOOK, 1, "local", lambda m: None))

    seed = foreshadowing.seed_by_id(BOOK, "SEED_001")
    assert seed["status"] == "unplanted"
