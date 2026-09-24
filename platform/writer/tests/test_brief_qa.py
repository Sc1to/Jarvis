"""Tests for the scene-brief QA gate (run-scene endpoint + _run_brief_qa helper)."""

import asyncio
import json
import os
import sys

import pytest

WRITER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, WRITER_DIR)

BOOK = "book1"
BRIEF_TEXT = "## Location\n\nSomewhere.\n\n## Scene Beats\n\n1. Something happens."
QA_ISSUE = {"type": "conflict", "description": "Peter's resentment reads invented.", "severity": "warning"}


def _configure_settings(monkeypatch, db, *, qa_configured=True):
    settings = {
        "agent_bible_agent_provider": "p", "agent_bible_agent_model": "m",
    }
    if qa_configured:
        settings["agent_qa_agent_provider"] = "p"
        settings["agent_qa_agent_model"] = "m"
    monkeypatch.setattr(db, "get_setting", lambda k: settings.get(k))


def test_run_brief_qa_parses_agent_response(tmp_path, monkeypatch):
    import db
    from routes import phase1

    monkeypatch.setattr(db, "DATA_ROOT", str(tmp_path))
    _configure_settings(monkeypatch, db)

    async def fake_bg_call(provider, model, messages, system, user, json_mode=False):
        assert system == phase1.BRIEF_QA_SYSTEM
        assert json_mode is True
        return json.dumps({"pass": False, "issues": [QA_ISSUE], "notes": "Trim the beats."})

    monkeypatch.setattr(phase1, "_bg_call", fake_bg_call)

    result = asyncio.run(phase1._run_brief_qa(BRIEF_TEXT, "local"))
    assert result == {"pass": False, "issues": [QA_ISSUE], "notes": "Trim the beats."}


def test_run_brief_qa_skips_when_qa_agent_not_configured(tmp_path, monkeypatch):
    import db
    from routes import phase1

    monkeypatch.setattr(db, "DATA_ROOT", str(tmp_path))
    _configure_settings(monkeypatch, db, qa_configured=False)

    called = False

    async def fake_bg_call(*a, **k):
        nonlocal called
        called = True
        return "{}"

    monkeypatch.setattr(phase1, "_bg_call", fake_bg_call)

    result = asyncio.run(phase1._run_brief_qa(BRIEF_TEXT, "local"))
    assert called is False
    assert result["pass"] is True
    assert result["issues"] == []


def test_run_brief_qa_degrades_gracefully_on_agent_failure(tmp_path, monkeypatch):
    import db
    from routes import phase1

    monkeypatch.setattr(db, "DATA_ROOT", str(tmp_path))
    _configure_settings(monkeypatch, db)

    async def failing_bg_call(*a, **k):
        raise ValueError("model unavailable")

    monkeypatch.setattr(phase1, "_bg_call", failing_bg_call)

    result = asyncio.run(phase1._run_brief_qa(BRIEF_TEXT, "local"))
    assert result["pass"] is True
    assert result["issues"][0]["type"] == "system"
    assert result["issues"][0]["severity"] == "warning"
    assert result["notes"] == "Brief QA skipped"


def test_run_scene_writes_brief_and_qa_sidecar(tmp_path, monkeypatch):
    """End-to-end through the run-scene endpoint: brief is saved, QA gate runs
    against it, and the result is both persisted to disk and put on the job."""
    import db
    import jobs as job_store
    from routes import phase1

    monkeypatch.setattr(db, "DATA_ROOT", str(tmp_path))
    _configure_settings(monkeypatch, db)

    book_dir = tmp_path / BOOK
    book_dir.mkdir()

    async def fake_provider_tokens(provider, model, messages, system, user_id, json_mode=False):
        if system == phase1.SCENE_WRITER_SYSTEM:
            for chunk in [BRIEF_TEXT[:10], BRIEF_TEXT[10:]]:
                yield chunk
        elif system == phase1.BRIEF_QA_SYSTEM:
            yield json.dumps({"pass": True, "issues": [], "notes": "Looks structural."})
        else:
            raise AssertionError(f"Unexpected system prompt: {system!r}")

    monkeypatch.setattr(phase1.llm, "provider_tokens", fake_provider_tokens)

    async def run():
        resp = await phase1.run_scene(
            BOOK, 1, phase1.RunSceneBody(scene=1), user="local",
        )
        job_id = resp["job_id"]
        for _ in range(200):
            job = job_store.get(job_id)
            if job["status"] != "running":
                break
            await asyncio.sleep(0)
        else:
            pytest.fail("background job never finished")
        return job

    job = asyncio.run(run())

    assert job["status"] == "done"
    assert (book_dir / "tier4" / "chapter_01_scene_01.md").read_text() == BRIEF_TEXT

    qa_path = book_dir / "tier4" / "chapter_01_scene_01_qa.json"
    assert json.loads(qa_path.read_text()) == {"pass": True, "issues": [], "notes": "Looks structural."}
    assert job["meta"]["brief_qa"] == {"pass": True, "issues": [], "notes": "Looks structural."}


def test_brief_qa_registered_in_writer_defaults():
    import main
    from routes.phase1 import BRIEF_QA_SYSTEM

    assert main._WRITER_DEFAULTS["brief_qa"] == BRIEF_QA_SYSTEM
