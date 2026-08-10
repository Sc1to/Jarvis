"""Tool library tests — filesystem, terminal, git, security."""
import sys
import time
import tempfile
from pathlib import Path

# Add platform to path so we can import tools directly
PLATFORM = Path(__file__).parent.parent.parent / "platform"
sys.path.insert(0, str(PLATFORM))


def _test_filesystem() -> tuple[bool, str]:
    try:
        from tools.filesystem import FilesystemTool
        with tempfile.TemporaryDirectory() as tmp:
            tool = FilesystemTool(allowed_root=tmp)
            r = tool.write("hello.txt", "hello world")
            if not r.success:
                return False, f"write failed: {r.error}"
            r = tool.read("hello.txt")
            if not r.success or r.data != "hello world":
                return False, f"read failed: {r}"
            r = tool.delete("hello.txt")
            if not r.success:
                return False, f"delete failed: {r.error}"
            return True, "write / read / delete OK"
    except Exception as exc:
        return False, str(exc)


def _test_filesystem_security() -> tuple[bool, str]:
    try:
        from tools.filesystem import FilesystemTool
        with tempfile.TemporaryDirectory() as tmp:
            tool = FilesystemTool(allowed_root=tmp)
            r = tool.read("../../etc/passwd")
            if r.success:
                return False, "path traversal was NOT blocked — security hole"
            return True, "path traversal correctly rejected"
    except Exception as exc:
        return False, str(exc)


def _test_terminal() -> tuple[bool, str]:
    try:
        from tools.terminal import TerminalTool
        tool = TerminalTool()
        r = tool.run('echo "hello from terminal"')
        if not r.success:
            return False, f"run failed: {r.error}"
        if "hello from terminal" not in r.data:
            return False, f"unexpected output: {r.data!r}"
        return True, "echo output verified"
    except Exception as exc:
        return False, str(exc)


def _test_git() -> tuple[bool, str]:
    try:
        from tools.git_tool import GitTool
        with tempfile.TemporaryDirectory() as tmp:
            tool = GitTool(repo_path=tmp)
            r = tool.init()
            if not r.success:
                return False, f"init failed: {r.error}"
            # Write a file and commit
            Path(tmp, "test.txt").write_text("test")
            r = tool.add("test.txt")
            if not r.success:
                return False, f"add failed: {r.error}"
            r = tool.commit("test commit")
            if not r.success:
                return False, f"commit failed: {r.error}"
            r = tool.log(limit=1)
            if not r.success or not r.data:
                return False, f"log failed: {r}"
            return True, "init / add / commit / log OK"
    except Exception as exc:
        return False, str(exc)


def run(base_url: str) -> tuple[int, int]:
    # These tests run locally — base_url is unused
    passed = failed = 0
    for label, fn in [
        ("filesystem: write / read / delete", _test_filesystem),
        ("filesystem: path traversal blocked", _test_filesystem_security),
        ("terminal: run echo",                _test_terminal),
        ("git: init / add / commit / log",    _test_git),
    ]:
        t0 = time.time()
        ok, detail = fn()
        ms = int((time.time() - t0) * 1000)
        status = "\033[32m[PASS]\033[0m" if ok else "\033[31m[FAIL]\033[0m"
        print(f"  {status}  {label}  ({ms}ms)")
        if not ok:
            print(f"         Detail: {detail}")
        passed += ok
        failed += (not ok)
    return passed, failed


if __name__ == "__main__":
    p, f = run("http://localhost")
    print(f"\n{p} passed, {f} failed")
