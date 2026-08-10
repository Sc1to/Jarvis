import sys
import pytest
from tools.terminal import TerminalTool, _truncate

linux_only = pytest.mark.skipif(sys.platform == "win32", reason="terminal tool targets Ubuntu")


@pytest.fixture
def term(tmp_path):
    return TerminalTool(str(tmp_path))


@linux_only
def test_simple_echo(term, tmp_path):
    r = term.execute_command("echo hello", str(tmp_path))
    assert r.success
    assert "hello" in r.output


@linux_only
def test_exit_code_nonzero(term, tmp_path):
    r = term.execute_command("exit 42", str(tmp_path))
    assert not r.success
    assert r.metadata["exit_code"] == 42


@linux_only
def test_stdout_and_stderr_captured(term, tmp_path):
    r = term.execute_command("echo out && echo err >&2", str(tmp_path))
    assert "out" in r.metadata["stdout"]
    assert "err" in r.metadata["stderr"]


def test_working_dir_outside_root_rejected(term, tmp_path):
    r = term.execute_command("echo bad", "/tmp/somewhere_else")
    assert not r.success
    assert "outside" in r.error


def test_blocked_sudo(term, tmp_path):
    r = term.execute_command("sudo ls", str(tmp_path))
    assert not r.success
    assert "Blocked" in r.error


def test_blocked_curl(term, tmp_path):
    r = term.execute_command("curl https://example.com", str(tmp_path))
    assert not r.success
    assert "Blocked" in r.error


def test_blocked_wget(term, tmp_path):
    r = term.execute_command("wget https://example.com", str(tmp_path))
    assert not r.success


def test_blocked_rm_rf_root(term, tmp_path):
    r = term.execute_command("rm -rf /", str(tmp_path))
    assert not r.success


@linux_only
def test_timeout(tmp_path):
    fast = TerminalTool(str(tmp_path), timeout=1)
    r = fast.execute_command("sleep 10", str(tmp_path))
    assert not r.success
    assert "timed out" in r.error.lower()


@linux_only
def test_execution_time_recorded(term, tmp_path):
    r = term.execute_command("true", str(tmp_path))
    assert "execution_time" in r.metadata
    assert isinstance(r.metadata["execution_time"], float)


def test_truncate_short():
    assert _truncate("abc") == "abc"


def test_truncate_long():
    long = "x" * 60_000
    result = _truncate(long)
    assert len(result) < 60_000
    assert "truncated" in result
