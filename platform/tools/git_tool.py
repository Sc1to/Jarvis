import json
import subprocess
from pathlib import Path
from .base import Tool, ToolResult

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "Platform Conductor",
    "GIT_AUTHOR_EMAIL": "conductor@platform.local",
    "GIT_COMMITTER_NAME": "Platform Conductor",
    "GIT_COMMITTER_EMAIL": "conductor@platform.local",
    "HOME": "/tmp",
    "PATH": "/usr/local/bin:/usr/bin:/bin",
}


class GitTool(Tool):
    @property
    def name(self) -> str:
        return "git"

    @property
    def description(self) -> str:
        return "Local Git version control, scoped to a repository path"

    def execute(self, params: dict) -> ToolResult:
        op = params.get("op")
        repo = params.get("repo_path", "")
        try:
            match op:
                case "init":            return self.init(repo)
                case "status":          return self.status(repo)
                case "add":             return self.add(repo, params.get("paths", ["."]))
                case "commit":          return self.commit(repo, params["message"])
                case "diff":            return self.diff(repo, params.get("staged", False))
                case "log":             return self.log(repo, params.get("limit", 10))
                case "branch_list":     return self.branch_list(repo)
                case "branch_create":   return self.branch_create(repo, params["name"])
                case "branch_checkout": return self.branch_checkout(repo, params["name"])
                case _:                 return ToolResult(success=False, output="", error=f"Unknown op: {op}")
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))

    def _run(self, args: list[str], repo_path: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git"] + args,
            cwd=repo_path,
            capture_output=True,
            text=True,
            env=_GIT_ENV,
        )

    def _ok(self, r: subprocess.CompletedProcess) -> ToolResult:
        return ToolResult(
            success=r.returncode == 0,
            output=r.stdout.strip(),
            error=r.stderr.strip() or None,
        )

    def init(self, repo_path: str) -> ToolResult:
        Path(repo_path).mkdir(parents=True, exist_ok=True)
        return self._ok(self._run(["init"], repo_path))

    def status(self, repo_path: str) -> ToolResult:
        return self._ok(self._run(["status", "--short"], repo_path))

    def add(self, repo_path: str, paths: list[str] = ["."]) -> ToolResult:
        return self._ok(self._run(["add"] + paths, repo_path))

    def commit(self, repo_path: str, message: str) -> ToolResult:
        return self._ok(self._run(["commit", "-m", message], repo_path))

    def diff(self, repo_path: str, staged: bool = False) -> ToolResult:
        args = ["diff", "--staged"] if staged else ["diff"]
        return self._ok(self._run(args, repo_path))

    def log(self, repo_path: str, limit: int = 10) -> ToolResult:
        fmt = "%H\x1f%s\x1f%aI\x1f%an"
        r = self._run(["log", f"-{limit}", f"--format={fmt}"], repo_path)
        if r.returncode != 0:
            return ToolResult(success=False, output="", error=r.stderr.strip())
        entries = []
        for line in r.stdout.strip().splitlines():
            parts = line.split("\x1f")
            if len(parts) == 4:
                entries.append({"hash": parts[0], "message": parts[1], "timestamp": parts[2], "author": parts[3]})
        return ToolResult(success=True, output=json.dumps(entries, indent=2), metadata={"commits": entries})

    def branch_list(self, repo_path: str) -> ToolResult:
        return self._ok(self._run(["branch"], repo_path))

    def branch_create(self, repo_path: str, name: str) -> ToolResult:
        return self._ok(self._run(["checkout", "-b", name], repo_path))

    def branch_checkout(self, repo_path: str, name: str) -> ToolResult:
        return self._ok(self._run(["checkout", name], repo_path))
