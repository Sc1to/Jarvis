import os
import tempfile

import pytest

from memory.session import SessionMemory


@pytest.fixture
def mem(tmp_path):
    db = str(tmp_path / "test.db")
    return SessionMemory(db_path=db)


def test_create_session_returns_uuid(mem):
    sid = mem.create_session(description="test run")
    assert isinstance(sid, str) and len(sid) == 36


def test_create_session_with_project(mem):
    sid = mem.create_session(project_id=42, description="with project")
    s = mem.get_session(sid)
    assert s.project_id == 42
    assert s.description == "with project"
    assert s.status == "running"


def test_get_session_not_found(mem):
    assert mem.get_session("nonexistent-id") is None


def test_log_event_returns_id(mem):
    sid = mem.create_session()
    eid = mem.log_event(sid, "conductor", "task_start", content="Starting backend agent")
    assert isinstance(eid, int) and eid > 0


def test_log_event_with_metadata(mem):
    sid = mem.create_session()
    mem.log_event(sid, "backend", "commit", content="feat: add /ping", metadata={"hash": "abc123"})
    log = mem.get_session_log(sid)
    assert len(log) == 1
    assert log[0].metadata["hash"] == "abc123"
    assert log[0].agent == "backend"
    assert log[0].event_type == "commit"


def test_log_multiple_events_ordered(mem):
    sid = mem.create_session()
    mem.log_event(sid, "conductor", "task_start")
    mem.log_event(sid, "backend", "task_complete", content="done")
    mem.log_event(sid, "conductor", "commit")
    log = mem.get_session_log(sid)
    assert [e.event_type for e in log] == ["task_start", "task_complete", "commit"]


def test_invalid_event_type_raises(mem):
    sid = mem.create_session()
    with pytest.raises(ValueError, match="Invalid event_type"):
        mem.log_event(sid, "conductor", "made_up_type")


def test_close_session(mem):
    sid = mem.create_session()
    mem.close_session(sid, "success")
    s = mem.get_session(sid)
    assert s.status == "closed"
    assert s.outcome == "success"
    assert s.closed_at is not None


def test_close_session_invalid_outcome(mem):
    sid = mem.create_session()
    with pytest.raises(ValueError, match="Invalid outcome"):
        mem.close_session(sid, "cancelled")


def test_list_sessions_empty(mem):
    assert mem.list_sessions() == []


def test_list_sessions(mem):
    s1 = mem.create_session(project_id=1, description="first")
    s2 = mem.create_session(project_id=1, description="second")
    sessions = mem.list_sessions(project_id=1)
    assert len(sessions) == 2


def test_list_sessions_all(mem):
    mem.create_session(project_id=1)
    mem.create_session(project_id=2)
    assert len(mem.list_sessions()) == 2


def test_all_valid_event_types(mem):
    sid = mem.create_session()
    for et in ["task_start", "task_complete", "failure", "replan", "commit", "internet_access", "parked"]:
        mem.log_event(sid, "agent", et)
    assert len(mem.get_session_log(sid)) == 7
