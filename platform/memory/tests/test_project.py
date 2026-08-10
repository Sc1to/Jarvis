import pytest

from memory.project import ProjectMemory


@pytest.fixture
def mem(tmp_path):
    return ProjectMemory(db_path=str(tmp_path / "test.db"))


def test_create_project_returns_id(mem):
    pid = mem.create_project("my-app", "A test project")
    assert isinstance(pid, int) and pid > 0


def test_get_project(mem):
    pid = mem.create_project("my-app", "desc")
    p = mem.get_project(pid)
    assert p.name == "my-app"
    assert p.description == "desc"
    assert p.id == pid


def test_get_project_not_found(mem):
    assert mem.get_project(9999) is None


def test_get_project_by_name(mem):
    mem.create_project("alpha", "first")
    p = mem.get_project_by_name("alpha")
    assert p is not None
    assert p.name == "alpha"


def test_get_project_by_name_not_found(mem):
    assert mem.get_project_by_name("ghost") is None


def test_list_projects(mem):
    mem.create_project("z-project")
    mem.create_project("a-project")
    projects = mem.list_projects()
    assert len(projects) == 2
    assert projects[0].name == "a-project"  # ordered by name


def test_save_and_get_decisions(mem):
    pid = mem.create_project("proj")
    did = mem.save_decision(pid, "architecture", "Use SQLite", "Simple and sufficient")
    decisions = mem.get_decisions(pid)
    assert len(decisions) == 1
    assert decisions[0].id == did
    assert decisions[0].decision_type == "architecture"
    assert decisions[0].content == "Use SQLite"


def test_get_decisions_by_type(mem):
    pid = mem.create_project("proj")
    mem.save_decision(pid, "architecture", "Use SQLite", "")
    mem.save_decision(pid, "tech", "Python 3.12", "")
    mem.save_decision(pid, "architecture", "Monolith first", "")

    arch = mem.get_decisions(pid, decision_type="architecture")
    assert len(arch) == 2
    tech = mem.get_decisions(pid, decision_type="tech")
    assert len(tech) == 1


def test_save_and_get_open_issues(mem):
    pid = mem.create_project("proj")
    iid = mem.save_open_issue(pid, "Auth not implemented yet")
    issues = mem.get_open_issues(pid)
    assert len(issues) == 1
    assert issues[0].id == iid
    assert issues[0].status == "open"


def test_resolve_issue(mem):
    pid = mem.create_project("proj")
    iid = mem.save_open_issue(pid, "Missing tests")
    mem.resolve_issue(iid, "Added pytest suite with 20 tests")
    open_issues = mem.get_open_issues(pid)
    assert len(open_issues) == 0
    all_issues = mem.get_all_issues(pid)
    assert all_issues[0].status == "resolved"
    assert all_issues[0].resolution == "Added pytest suite with 20 tests"
    assert all_issues[0].resolved_at is not None


def test_open_issues_excludes_resolved(mem):
    pid = mem.create_project("proj")
    i1 = mem.save_open_issue(pid, "Issue 1")
    i2 = mem.save_open_issue(pid, "Issue 2")
    mem.resolve_issue(i1, "Fixed")
    open_issues = mem.get_open_issues(pid)
    assert len(open_issues) == 1
    assert open_issues[0].id == i2


def test_decisions_scoped_to_project(mem):
    p1 = mem.create_project("proj1")
    p2 = mem.create_project("proj2")
    mem.save_decision(p1, "arch", "SQLite", "")
    assert len(mem.get_decisions(p2)) == 0
