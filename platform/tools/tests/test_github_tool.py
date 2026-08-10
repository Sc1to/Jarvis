import json
from unittest.mock import MagicMock, patch
from tools.github_tool import GitHubTool


def test_no_token_returns_clear_error():
    t = GitHubTool()
    with patch("tools.github_tool._load_token", return_value=None), \
         patch("tools.github_tool.Github", new=MagicMock()):
        r = t.execute({"op": "list_repos", "username": "user"})
    assert not r.success
    assert "token" in r.error.lower()


def test_list_repos_mocked():
    mock_repo = MagicMock()
    mock_repo.name = "my-repo"
    mock_repo.html_url = "https://github.com/user/my-repo"
    mock_repo.private = False

    mock_user = MagicMock()
    mock_user.get_repos.return_value = [mock_repo]

    with patch("tools.github_tool._load_token", return_value="tok"), \
         patch("tools.github_tool.Github") as MockGH:
        MockGH.return_value.get_user.return_value = mock_user
        r = GitHubTool().list_repos("user")

    assert r.success
    data = json.loads(r.output)
    assert data[0]["name"] == "my-repo"
    assert r.metadata["count"] == 1


def test_create_pr_mocked():
    mock_pr = MagicMock()
    mock_pr.html_url = "https://github.com/user/repo/pull/42"
    mock_pr.number = 42

    mock_gh_repo = MagicMock()
    mock_gh_repo.create_pull.return_value = mock_pr

    with patch("tools.github_tool._load_token", return_value="tok"), \
         patch("tools.github_tool.Github") as MockGH:
        MockGH.return_value.get_repo.return_value = mock_gh_repo
        r = GitHubTool().create_pr("user/repo", "Title", "Body", "feature")

    assert r.success
    assert "pull/42" in r.output
    assert r.metadata["pr_number"] == 42


def test_list_issues_mocked():
    mock_issue = MagicMock()
    mock_issue.number = 1
    mock_issue.title = "Bug"
    mock_issue.html_url = "https://github.com/user/repo/issues/1"

    mock_gh_repo = MagicMock()
    mock_gh_repo.get_issues.return_value = [mock_issue]

    with patch("tools.github_tool._load_token", return_value="tok"), \
         patch("tools.github_tool.Github") as MockGH:
        MockGH.return_value.get_repo.return_value = mock_gh_repo
        r = GitHubTool().list_issues("user/repo")

    assert r.success
    data = json.loads(r.output)
    assert data[0]["title"] == "Bug"


def test_get_repo_info_mocked():
    mock_gh_repo = MagicMock()
    mock_gh_repo.name = "repo"
    mock_gh_repo.description = "A repo"
    mock_gh_repo.default_branch = "main"
    mock_gh_repo.html_url = "https://github.com/user/repo"

    with patch("tools.github_tool._load_token", return_value="tok"), \
         patch("tools.github_tool.Github") as MockGH:
        MockGH.return_value.get_repo.return_value = mock_gh_repo
        r = GitHubTool().get_repo_info("user/repo")

    assert r.success
    assert r.metadata["default_branch"] == "main"


def test_unknown_op():
    t = GitHubTool()
    with patch("tools.github_tool._load_token", return_value="tok"), \
         patch("tools.github_tool.Github"):
        r = t.execute({"op": "launch_rocket"})
    assert not r.success
    assert "Unknown op" in r.error
