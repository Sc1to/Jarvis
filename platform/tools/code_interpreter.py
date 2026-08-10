import ast
import subprocess
import tempfile
from pathlib import Path
from .base import Tool, ToolResult

TIMEOUT = 30
_BLOCKED_IMPORTS = frozenset({"subprocess", "socket", "os.system"})


class CodeInterpreterTool(Tool):
    def __init__(self, allowed_root: str):
        self._root = str(Path(allowed_root).resolve())

    @property
    def name(self) -> str:
        return "code_interpreter"

    @property
    def description(self) -> str:
        return "Execute Python or JavaScript code snippets in isolated subprocesses"

    def _validate_wd(self, working_directory: str) -> str:
        wd = str(Path(working_directory).resolve())
        if not wd.startswith(self._root):
            raise PermissionError("working_directory outside allowed root")
        return wd

    def execute(self, params: dict) -> ToolResult:
        op = params.get("op", "run_python")
        try:
            match op:
                case "run_python":     return self.run_python(params["code"], params.get("working_directory", self._root))
                case "run_javascript": return self.run_javascript(params["code"], params.get("working_directory", self._root))
                case "validate_syntax": return self.validate_syntax(params["code"], params.get("language", "python"))
                case _:                return ToolResult(success=False, output="", error=f"Unknown op: {op}")
        except PermissionError as e:
            return ToolResult(success=False, output="", error=str(e))
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))

    def run_python(self, code: str, working_directory: str) -> ToolResult:
        wd = self._validate_wd(working_directory)
        syntax_check = self.validate_syntax(code, "python")
        if not syntax_check.success:
            return syntax_check

        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False, dir="/tmp") as f:
            f.write(code)
            script = f.name

        try:
            r = subprocess.run(
                ["python3", script],
                cwd=wd,
                capture_output=True,
                text=True,
                timeout=TIMEOUT,
                stdin=subprocess.DEVNULL,
                env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp"},
            )
            return ToolResult(
                success=r.returncode == 0,
                output=r.stdout or r.stderr,
                error=r.stderr if r.returncode != 0 else None,
                metadata={"exit_code": r.returncode, "stdout": r.stdout, "stderr": r.stderr},
            )
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, output="", error=f"Timed out after {TIMEOUT}s")
        finally:
            Path(script).unlink(missing_ok=True)

    def run_javascript(self, code: str, working_directory: str) -> ToolResult:
        wd = self._validate_wd(working_directory)
        with tempfile.NamedTemporaryFile(suffix=".js", mode="w", delete=False, dir="/tmp") as f:
            f.write(code)
            script = f.name

        try:
            r = subprocess.run(
                ["node", script],
                cwd=wd,
                capture_output=True,
                text=True,
                timeout=TIMEOUT,
                stdin=subprocess.DEVNULL,
                env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp"},
            )
            return ToolResult(
                success=r.returncode == 0,
                output=r.stdout or r.stderr,
                error=r.stderr if r.returncode != 0 else None,
                metadata={"exit_code": r.returncode},
            )
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, output="", error=f"Timed out after {TIMEOUT}s")
        except FileNotFoundError:
            return ToolResult(success=False, output="", error="node not found — install Node.js")
        finally:
            Path(script).unlink(missing_ok=True)

    def validate_syntax(self, code: str, language: str = "python") -> ToolResult:
        if language != "python":
            return ToolResult(success=True, output=f"Syntax check for {language}: not implemented, proceeding")
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return ToolResult(success=False, output="", error=f"SyntaxError: {e}")

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in _BLOCKED_IMPORTS:
                        return ToolResult(success=False, output="", error=f"Blocked import: {alias.name!r}")
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod in _BLOCKED_IMPORTS or mod.startswith("os") and any(
                    n.name == "system" for n in (node.names or [])
                ):
                    return ToolResult(success=False, output="", error=f"Blocked import: {mod!r}")

        return ToolResult(success=True, output="Syntax OK")
