import subprocess

import pytest

from bookforge import vcs
from bookforge.errors import VcsError


@pytest.fixture
def repo(tmp_path):
    vcs.init_repo(tmp_path / "r")
    return tmp_path / "r"


def test_init_is_idempotent(repo):
    assert vcs.is_repo(repo)
    vcs.init_repo(repo)
    assert vcs.is_repo(repo)


def test_commit_returns_sha_and_none_when_nothing_changed(repo):
    (repo / "a.md").write_text("one\n")
    sha = vcs.commit(repo, "add a", ["a.md"])
    assert sha and sha == vcs.head_sha(repo)
    assert vcs.commit(repo, "nothing", ["a.md"]) is None


def test_commit_only_stages_given_paths(repo):
    (repo / "a.md").write_text("a\n")
    (repo / "b.md").write_text("b\n")
    vcs.commit(repo, "only a", ["a.md"])
    assert vcs.is_dirty(repo)  # b.md still untracked
    tracked = subprocess.run(["git", "-C", str(repo), "ls-files"], capture_output=True, text=True).stdout.split()
    assert tracked == ["a.md"]


def test_commit_all_when_no_paths(repo):
    (repo / "a.md").write_text("a\n")
    (repo / "b.md").write_text("b\n")
    vcs.commit(repo, "everything")
    assert not vcs.is_dirty(repo)


def test_paths_cannot_escape_the_repo(repo, tmp_path):
    (tmp_path / "outside.md").write_text("x\n")
    with pytest.raises(VcsError, match="escapes"):
        vcs.commit(repo, "bad", ["../outside.md"])


def test_commits_use_bookforge_identity_without_any_git_config(repo):
    (repo / "a.md").write_text("a\n")
    vcs.commit(repo, "identity check", ["a.md"])
    author = subprocess.run(["git", "-C", str(repo), "log", "-1", "--format=%an <%ae>"], capture_output=True, text=True).stdout.strip()
    assert author == "bookforge <bookforge@localhost>"


def test_tags(repo):
    (repo / "a.md").write_text("a\n")
    vcs.commit(repo, "first")
    vcs.tag(repo, "b1-direction-approved")
    assert vcs.tag_exists(repo, "b1-direction-approved")
    assert vcs.list_tags(repo) == ["b1-direction-approved"]
    with pytest.raises(VcsError, match="already exists"):
        vcs.tag(repo, "b1-direction-approved")
    for bad in ("", "-rf", "has space", "a;b"):
        with pytest.raises(VcsError, match="invalid tag"):
            vcs.tag(repo, bad)


def test_commit_message_is_not_interpreted_by_a_shell(repo):
    (repo / "a.md").write_text("a\n")
    msg = "b1.ch05.s2: $(touch pwned); `touch pwned`"
    vcs.commit(repo, msg, ["a.md"])
    assert not (repo / "pwned").exists()
    subject = subprocess.run(["git", "-C", str(repo), "log", "-1", "--format=%s"], capture_output=True, text=True).stdout.strip()
    assert subject == msg
