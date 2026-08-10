import json
import re
from pathlib import Path
from .base import Tool, ToolResult
from .terminal import TerminalTool

MAX_OUTPUT = 10_000
TIMEOUT = 300  # 5 minutes


class TestRunnerTool(Tool):
    def __init__(self, allowed_root: str):
        self._terminal = TerminalTool(allowed_root, timeout=TIMEOUT)

    @property
    def name(self) -> str:
        return "test_runner"

    @property
    def description(self) -> str:
        return "Execute test suites and return structured pass/fail results"

    def execute(self, params: dict) -> ToolResult:
        op = params.get("op", "run_tests")
        project_path = params["project_path"]
        try:
            match op:
                case "run_tests":      return self.run_tests(project_path, params.get("test_command"))
                case "run_single_test": return self.run_single_test(project_path, params["test_identifier"])
                case "get_coverage":   return self.get_coverage(project_path)
                case _:                return ToolResult(success=False, output="", error=f"Unknown op: {op}")
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))

    def _detect_command(self, project_path: str) -> str:
        p = Path(project_path)
        if (
            (p / "pytest.ini").exists()
            or (p / "pyproject.toml").exists()
            or list(p.glob("tests/test_*.py"))
            or list(p.glob("test_*.py"))
        ):
            return "python3 -m pytest -v --tb=short 2>&1"
        if (p / "package.json").exists():
            try:
                pkg = json.loads((p / "package.json").read_text())
                deps = {**pkg.get("devDependencies", {}), **pkg.get("dependencies", {})}
                if "jest" in deps:
                    return "npx jest --no-coverage 2>&1"
                if "mocha" in deps:
                    return "npx mocha 2>&1"
            except Exception:
                pass
        return "python3 -m pytest -v --tb=short 2>&1"

    def run_tests(self, project_path: str, test_command: str | None = None) -> ToolResult:
        cmd = test_command or self._detect_command(project_path)
        result = self._terminal.execute_command(cmd, project_path)
        raw = (result.metadata.get("stdout", "") + result.metadata.get("stderr", ""))[:MAX_OUTPUT]
        meta = _parse_pytest(raw)
        return ToolResult(
            success=meta["failed"] == 0 and meta["errors"] == 0,
            output=raw,
            metadata=meta,
        )

    def run_single_test(self, project_path: str, test_identifier: str) -> ToolResult:
        return self.run_tests(project_path, f"python3 -m pytest {test_identifier} -v --tb=short 2>&1")

    def get_coverage(self, project_path: str) -> ToolResult:
        result = self._terminal.execute_command(
            "python3 -m pytest --cov=. --cov-report=term-missing --tb=no -q 2>&1",
            project_path,
        )
        raw = result.metadata.get("stdout", "")[:MAX_OUTPUT]
        pct = _parse_coverage(raw)
        return ToolResult(success=True, output=raw, metadata={"coverage": pct})


def _parse_pytest(output: str) -> dict:
    meta: dict = {"total": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": 0, "failures": [], "coverage": None}
    for key, pattern in [("passed", r"(\d+) passed"), ("failed", r"(\d+) failed"),
                          ("errors", r"(\d+) error"), ("skipped", r"(\d+) skipped")]:
        m = re.search(pattern, output)
        if m:
            meta[key] = int(m.group(1))
    meta["total"] = meta["passed"] + meta["failed"] + meta["errors"] + meta["skipped"]
    return meta


def _parse_coverage(output: str) -> float | None:
    m = re.search(r"TOTAL\s+\d+\s+\d+\s+(\d+)%", output)
    return float(m.group(1)) if m else None
