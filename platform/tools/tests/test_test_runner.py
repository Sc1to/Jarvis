import sys
import pytest
from tools.test_runner import TestRunnerTool, _parse_pytest, _parse_coverage

linux_only = pytest.mark.skipif(sys.platform == "win32", reason="test runner targets Ubuntu")


# ── Parser unit tests (pure Python, runs anywhere) ────────────────────────────

def test_parse_all_passed():
    out = "5 passed in 0.12s"
    m = _parse_pytest(out)
    assert m["passed"] == 5
    assert m["failed"] == 0
    assert m["total"] == 5


def test_parse_mixed():
    out = "3 passed, 2 failed, 1 error, 1 skipped"
    m = _parse_pytest(out)
    assert m["passed"] == 3
    assert m["failed"] == 2
    assert m["errors"] == 1
    assert m["skipped"] == 1
    assert m["total"] == 7


def test_parse_coverage():
    out = "TOTAL                    100     10    90%"
    assert _parse_coverage(out) == 90.0


def test_parse_coverage_missing():
    assert _parse_coverage("no coverage here") is None


# ── Integration tests (require pytest installed, Linux only) ──────────────────

@linux_only
def test_run_passing_tests(tmp_path):
    (tmp_path / "test_ok.py").write_text("def test_pass(): assert 1 == 1\n")
    runner = TestRunnerTool(str(tmp_path))
    r = runner.run_tests(str(tmp_path))
    assert r.success
    assert r.metadata["passed"] == 1
    assert r.metadata["failed"] == 0


@linux_only
def test_run_failing_tests(tmp_path):
    (tmp_path / "test_fail.py").write_text("def test_fail(): assert False\n")
    runner = TestRunnerTool(str(tmp_path))
    r = runner.run_tests(str(tmp_path))
    assert not r.success
    assert r.metadata["failed"] == 1


@linux_only
def test_run_mixed_results(tmp_path):
    (tmp_path / "test_mixed.py").write_text(
        "def test_ok(): assert True\n"
        "def test_bad(): assert False\n"
    )
    runner = TestRunnerTool(str(tmp_path))
    r = runner.run_tests(str(tmp_path))
    assert not r.success
    assert r.metadata["passed"] == 1
    assert r.metadata["failed"] == 1


@linux_only
def test_unknown_op(tmp_path):
    runner = TestRunnerTool(str(tmp_path))
    r = runner.execute({"op": "explode", "project_path": str(tmp_path)})
    assert not r.success
