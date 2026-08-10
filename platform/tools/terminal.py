import subprocess
import time
from pathlib import Path
from .base import Tool, ToolResult

MAX_OUTPUT = 50_000
DEFAULT_TIMEOUT = 60

# Patterns that are never allowed regardless of context
_BLOCKED = [
    "rm -rf /",
    "rm -rf /*",
    "sudo ",
    "sudo\t",
    "chmod 777",
    "wget ",
    "curl ",
    "ssh ",
    ":(){:|:&};:",  # fork bomb
]

_SAFE_ENV = {
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "HOME": "/tmp",
    "LANG": "C.UTF-8",
}


class TerminalTool(Tool):
    def __init__(self, allowed_root: str, timeout: int = DEFAULT_TIMEOUT):
        self._root = str(Path(allowed_root).resolve())
        self._timeout = timeout

    @property
    def name(self) -> str:
        return "terminal"

    @property
    def description(self) -> str:
        return "Sandboxed command execution within allowed_root"

    def execute(self, params: dict) -> ToolResult:
        return self.execute_command(
            params["command"],
            params.get("working_directory", self._root),
        )

    def execute_command(self, command: str, working_directory: str) -> ToolResult:
        wd = Path(working_directory).resolve()
        root = Path(self._root)
        if wd != root and not wd.is_relative_to(root):
            return ToolResult(success=False, output="", error="working_directory outside allowed root")

        for blocked in _BLOCKED:
            if blocked in command:
                return ToolResult(success=False, output="", error=f"Blocked command pattern: {blocked!r}")

        start = time.monotonic()
        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=str(wd),
                capture_output=True,
                text=True,
                timeout=self._timeout,
                stdin=subprocess.DEVNULL,
                env=_SAFE_ENV,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error=f"Command timed out after {self._timeout}s",
                metadata={"exit_code": -1, "execution_time": self._timeout},
            )

        elapsed = round(time.monotonic() - start, 3)
        stdout = _truncate(proc.stdout)
        stderr = _truncate(proc.stderr)

        return ToolResult(
            success=proc.returncode == 0,
            output=stdout or stderr,
            error=stderr if proc.returncode != 0 and stderr else None,
            metadata={
                "exit_code": proc.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "execution_time": elapsed,
            },
        )


def _truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT:
        return text
    return text[:MAX_OUTPUT] + f"\n... [truncated — {len(text):,} chars total]"
