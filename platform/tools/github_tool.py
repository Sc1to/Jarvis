import json
import sqlite3
import subprocess
from .base import Tool, ToolResult

try:
    from github import Github
except ImportError:
    Github = None  # type: ignore

DB_PATH = "/opt/platform/data/platform.db"


def _load_token() -> str | None:
    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute("SELECT value FROM config WHERE key='github_token'").fetchone()
        conn.close()
        return row[0] if row else None
    except Exception:
        return None


class GitHubTool(Tool):
    @property
    def name(self) -> str:
        return "github"

    @property
    def description(self) -> str:
        return "GitHub repo management — token loaded from platform SQLite config"

    def _client(self):
        if Github is None:
            raise RuntimeError("PyGithub not installed — run: pip install PyGithub")
        token = _load_token()
        if not token:
            raise RuntimeError("GitHub token not configured — set it via the admin panel (Phase 5)")
        return Github(token)

    def execute(self, params: dict) -> ToolResult:
        op = params.get("op")
        try:
            match op:
                case "list_repos":   return self.list_repos(params["username"])
                case "clone_repo":   return self.clone_repo(params["repo_url"], params["destination_path"])
                case "push":         return self.push(params["repo_path"], params.get("remote", "origin"), params.get("branch", "main"))
                case "create_pr":    return self.create_pr(params["repo"], params["title"], params["body"], params["head_branch"], params.get("base_branch", "main"))
                case "list_issues":  return self.list_issues(params["repo"])
                case "get_repo_info": return self.get_repo_info(params["repo"])
                case _:              return ToolResult(success=False, output="", error=f"Unknown op: {op}")
        except RuntimeError as e:
            return ToolResult(success=False, output="", error=str(e))
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))

    def list_repos(self, username: str) -> ToolResult:
        g = self._client()
        repos = [{"name": r.name, "url": r.html_url, "private": r.private} for r in g.get_user(username).get_repos()]
        return ToolResult(success=True, output=json.dumps(repos, indent=2), metadata={"count": len(repos)})

    def clone_repo(self, repo_url: str, destination_path: str) -> ToolResult:
        r = subprocess.run(["git", "clone", repo_url, destination_path], capture_output=True, text=True)
        return ToolResult(success=r.returncode == 0, output=r.stdout.strip(), error=r.stderr.strip() or None)

    def push(self, repo_path: str, remote: str = "origin", branch: str = "main") -> ToolResult:
        r = subprocess.run(["git", "push", remote, branch], cwd=repo_path, capture_output=True, text=True)
        return ToolResult(success=r.returncode == 0, output=r.stdout.strip(), error=r.stderr.strip() or None)

    def create_pr(self, repo: str, title: str, body: str, head_branch: str, base_branch: str = "main") -> ToolResult:
        g = self._client()
        pr = g.get_repo(repo).create_pull(title=title, body=body, head=head_branch, base=base_branch)
        return ToolResult(success=True, output=pr.html_url, metadata={"pr_number": pr.number, "url": pr.html_url})

    def list_issues(self, repo: str) -> ToolResult:
        g = self._client()
        issues = [{"number": i.number, "title": i.title, "url": i.html_url} for i in g.get_repo(repo).get_issues(state="open")]
        return ToolResult(success=True, output=json.dumps(issues, indent=2), metadata={"count": len(issues)})

    def get_repo_info(self, repo: str) -> ToolResult:
        g = self._client()
        r = g.get_repo(repo)
        info = {"name": r.name, "description": r.description, "default_branch": r.default_branch, "url": r.html_url}
        return ToolResult(success=True, output=json.dumps(info, indent=2), metadata=info)
