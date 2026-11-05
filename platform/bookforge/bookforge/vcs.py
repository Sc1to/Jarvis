"""Git for a series repository, through the git binary.

One commit per accepted step, tags at checkpoints (docs/BOOKFORGE.md, Version control).
Commits are made as 'bookforge' regardless of the host's git identity.
"""

import logging
import re
import subprocess
from pathlib import Path
from typing import Iterable

from .errors import VcsError

log = logging.getLogger("platform_bookforge.vcs")

_IDENTITY = ["-c", "user.name=bookforge", "-c", "user.email=bookforge@localhost"]
_TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    try:
        proc = subprocess.run(
            ["git", *_IDENTITY, "-C", str(root), *args],
            capture_output=True, text=True, timeout=60,
        )
    except FileNotFoundError as e:
        raise VcsError("git is not installed") from e
    except subprocess.TimeoutExpired as e:
        raise VcsError(f"git {args[0]} timed out") from e
    if check and proc.returncode != 0:
        raise VcsError(f"git {' '.join(args)} failed: {(proc.stderr or proc.stdout).strip()}")
    return proc


def is_repo(root: Path) -> bool:
    return (root / ".git").exists()


def init_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    if not is_repo(root):
        _git(root, "init", "-b", "main")


def _relative_paths(root: Path, paths: Iterable[str | Path]) -> list[str]:
    root_resolved = root.resolve()
    out = []
    for p in paths:
        full = (root_resolved / p).resolve()
        try:
            out.append(str(full.relative_to(root_resolved)))
        except ValueError as e:
            raise VcsError(f"path escapes the series repository: {p}") from e
    return out


def commit(root: Path, message: str, paths: Iterable[str | Path] | None = None) -> str | None:
    """Stage `paths` (everything if None) and commit. Returns the new sha, or None if nothing changed."""
    if paths is None:
        _git(root, "add", "-A")
    else:
        rel = _relative_paths(root, paths)
        if rel:
            _git(root, "add", "--", *rel)
    if _git(root, "diff", "--cached", "--quiet", check=False).returncode == 0:
        return None
    _git(root, "commit", "-q", "-m", message)
    sha = head_sha(root)
    log.info("committed %s: %s", sha[:8] if sha else "?", message)
    return sha


def head_sha(root: Path) -> str | None:
    proc = _git(root, "rev-parse", "HEAD", check=False)
    return proc.stdout.strip() if proc.returncode == 0 else None


def tag_exists(root: Path, name: str) -> bool:
    return _git(root, "rev-parse", "-q", "--verify", f"refs/tags/{name}", check=False).returncode == 0


def tag(root: Path, name: str, message: str | None = None) -> None:
    if not _TAG_RE.match(name):
        raise VcsError(f"invalid tag name: {name!r}")
    if tag_exists(root, name):
        raise VcsError(f"tag already exists: {name}")
    _git(root, "tag", "-a", name, "-m", message or name)


def list_tags(root: Path) -> list[str]:
    return [t for t in _git(root, "tag", "--list").stdout.split() if t]


def is_dirty(root: Path) -> bool:
    return bool(_git(root, "status", "--porcelain").stdout.strip())
