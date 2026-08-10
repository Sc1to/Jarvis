import json
import subprocess
import sys
import pytest
from tools.git_tool import GitTool

linux_only = pytest.mark.skipif(sys.platform == "win32", reason="git tool targets Ubuntu")


@pytest.fixture
def repo(tmp_path):
    t = GitTool()
    r = t.init(str(tmp_path))
    assert r.success
    # Minimal local config so commits work
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(tmp_path), check=True)
    return t, tmp_path


@linux_only
def test_init_creates_git_dir(tmp_path):
    t = GitTool()
    r = t.init(str(tmp_path / "repo"))
    assert r.success
    assert (tmp_path / "repo" / ".git").is_dir()


@linux_only
def test_status_shows_untracked(repo):
    t, path = repo
    (path / "new.txt").write_text("hi")
    r = t.status(str(path))
    assert r.success
    assert "new.txt" in r.output


@linux_only
def test_add_and_commit(repo):
    t, path = repo
    (path / "a.txt").write_text("a")
    t.add(str(path))
    r = t.commit(str(path), "add a.txt")
    assert r.success


@linux_only
def test_log_structure(repo):
    t, path = repo
    (path / "b.txt").write_text("b")
    t.add(str(path))
    t.commit(str(path), "add b.txt")
    r = t.log(str(path), limit=5)
    assert r.success
    commits = json.loads(r.output)
    assert len(commits) >= 1
    assert all(k in commits[0] for k in ("hash", "message", "timestamp", "author"))
    assert commits[0]["message"] == "add b.txt"


@linux_only
def test_diff_staged(repo):
    t, path = repo
    (path / "c.txt").write_text("c")
    t.add(str(path))
    r = t.diff(str(path), staged=True)
    assert r.success
    assert "c.txt" in r.output


@linux_only
def test_branch_create_and_checkout(repo):
    t, path = repo
    # Need a commit first
    (path / "x.txt").write_text("x")
    t.add(str(path))
    t.commit(str(path), "initial")

    r = t.branch_create(str(path), "feature")
    assert r.success

    # Checkout default branch (main or master depending on git version)
    r = t.branch_checkout(str(path), "main")
    if not r.success:
        r = t.branch_checkout(str(path), "master")
    assert r.success


@linux_only
def test_unknown_op():
    t = GitTool()
    r = t.execute({"op": "teleport", "repo_path": "/tmp"})
    assert not r.success
    assert "Unknown op" in r.error
