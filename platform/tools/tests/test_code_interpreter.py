import sys
import pytest
from tools.code_interpreter import CodeInterpreterTool

linux_only = pytest.mark.skipif(sys.platform == "win32", reason="code interpreter targets Ubuntu")


@pytest.fixture
def interp(tmp_path):
    return CodeInterpreterTool(str(tmp_path))


# ── Syntax validation (pure Python AST, runs anywhere) ───────────────────────

def test_valid_syntax(interp):
    r = interp.validate_syntax("x = 1 + 2\nprint(x)", "python")
    assert r.success
    assert "Syntax OK" in r.output


def test_syntax_error(interp):
    r = interp.validate_syntax("def broken(:", "python")
    assert not r.success
    assert "SyntaxError" in r.error


def test_blocked_import_subprocess(interp):
    r = interp.validate_syntax("import subprocess", "python")
    assert not r.success
    assert "subprocess" in r.error


def test_blocked_import_socket(interp):
    r = interp.validate_syntax("import socket", "python")
    assert not r.success


def test_non_python_syntax_passthrough(interp):
    r = interp.validate_syntax("const x = 1;", "javascript")
    assert r.success  # no python check, just passes through


# ── Execution tests (require python3, Linux only) ─────────────────────────────

@linux_only
def test_run_python_basic(interp, tmp_path):
    r = interp.run_python("print('hello world')", str(tmp_path))
    assert r.success
    assert "hello world" in r.output


@linux_only
def test_run_python_arithmetic(interp, tmp_path):
    r = interp.run_python("print(2 ** 10)", str(tmp_path))
    assert r.success
    assert "1024" in r.output


@linux_only
def test_run_python_blocked_import_rejected_at_syntax(interp, tmp_path):
    r = interp.run_python("import subprocess\nsubprocess.run(['ls'])", str(tmp_path))
    assert not r.success
    # Blocked at AST validation stage, before execution
    assert "subprocess" in r.error


@linux_only
def test_run_python_working_dir_outside_root_rejected(tmp_path):
    interp = CodeInterpreterTool(str(tmp_path))
    r = interp.run_python("print('x')", "/tmp/other")
    assert not r.success
    assert "outside" in r.error


@linux_only
def test_execute_dispatch(interp, tmp_path):
    r = interp.execute({"op": "run_python", "code": "print(42)", "working_directory": str(tmp_path)})
    assert r.success
    assert "42" in r.output


@linux_only
def test_unknown_op(interp):
    r = interp.execute({"op": "magic", "code": ""})
    assert not r.success
    assert "Unknown op" in r.error
