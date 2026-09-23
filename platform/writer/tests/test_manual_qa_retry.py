"""Manual chapter writes only retry QA-failed scenes when qa_retry_manual is enabled."""

import asyncio
import json
import os
import sys

import pytest
from git import Repo

WRITER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, WRITER_DIR)

BOOK = "book1"
QA_FAIL = {"pass": False, "notes": "Exit state missed", "issues": [
    {"type": "continuity", "description": "Door is open, should be locked", "severity": "error"},
]}


def _run_manual_write(tmp_path, monkeypatch, retry_setting):
    import db
    from routes import phase3

    monkeypatch.setattr(db, "DATA_ROOT", str(tmp_path))
    settings = {
        "agent_writer_agent_provider": "p", "agent_writer_agent_model": "m",
        "agent_qa_agent_provider": "p", "agent_qa_agent_model": "m",
        "agent_bible_agent_provider": "p", "agent_bible_agent_model": "m",
        "qa_retry_manual": retry_setting,
    }
    monkeypatch.setattr(db, "get_setting", lambda k: settings.get(k))
    monkeypatch.setattr(db, "append_job_log", lambda *a: None)

    calls = {"writer": 0, "qa": 0}

    async def fake_call(provider, model, messages, system, user_id="local", json_mode=False):
        if system == phase3.SCENE_PLANNER_SYSTEM:
            return json.dumps([{"scene": 1, "brief": "b", "entry_state": "", "exit_state": "locked"}])
        if system == phase3.QA_SYSTEM:
            calls["qa"] += 1
            return json.dumps(QA_FAIL)
        calls["writer"] += 1
        return f"Draft {calls['writer']}."

    monkeypatch.setattr(phase3, "_call", fake_call)

    book_dir = tmp_path / BOOK
    (book_dir / "tier4").mkdir(parents=True)
    (book_dir / "tier4" / "chapter_01.md").write_text("### Scene 1 — b")
    Repo.init(book_dir)

    queue: asyncio.Queue = asyncio.Queue()
    asyncio.run(phase3._write_chapter_task(BOOK, 1, "local", "job", queue))
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    meta = json.loads((book_dir / "chapter_01_meta.json").read_text())
    return calls, events, meta["scenes"][0]


def test_manual_write_holds_failed_scene_for_review(tmp_path, monkeypatch):
    calls, events, scene = _run_manual_write(tmp_path, monkeypatch, None)
    assert calls == {"writer": 1, "qa": 1}
    assert {"type": "qa_held", "scene": 1} in events
    assert scene["attempts"] == 1
    assert scene["qa_pass"] is False
    assert scene["qa_issues"] == QA_FAIL["issues"]


def test_manual_write_retries_when_enabled(tmp_path, monkeypatch):
    calls, events, scene = _run_manual_write(tmp_path, monkeypatch, "true")
    assert calls == {"writer": 3, "qa": 3}
    assert not any(e["type"] == "qa_held" for e in events)
    assert scene["attempts"] == 3
