"""`doctor`: environment checks. Local checks only for now.

TODO: replace with real implementation. Checks for the two colibri endpoints and
the Playwright web tool arrive in milestone 14.2 (llm.py and doctor).
"""

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from . import vcs
from .config import Config, host_config_path, load_config
from .errors import BookforgeError
from .state import load_state


@dataclass
class Check:
    name: str
    level: str  # pass | warn | fail
    detail: str = ""


def run_doctor(series: Path | None = None, book: str = "b1") -> list[Check]:
    checks: list[Check] = []

    v = sys.version_info
    checks.append(Check(
        "python", "pass" if v[:2] >= (3, 12) else "warn",
        f"{v.major}.{v.minor}.{v.micro}" + ("" if v[:2] >= (3, 12) else " (Jarvis targets 3.12)"),
    ))

    git = shutil.which("git")
    checks.append(Check("git", "pass" if git else "fail", git or "git not found on PATH"))

    config: Config | None = None
    try:
        config = load_config(series)
        host = host_config_path()
        checks.append(Check("config", "pass", f"valid ({host if host else 'built-in defaults'})"))
    except BookforgeError as e:
        checks.append(Check("config", "fail", str(e)))

    if config is not None:
        data_dir = Path(config.data_dir)
        if not data_dir.exists():
            checks.append(Check("data_dir", "warn", f"{data_dir} does not exist yet"))
        elif os.access(data_dir, os.W_OK):
            checks.append(Check("data_dir", "pass", str(data_dir)))
        else:
            checks.append(Check("data_dir", "fail", f"{data_dir} is not writable"))

        for role in ("writer", "critic"):
            m = getattr(config.models, role)
            if m.model:
                checks.append(Check(f"model_{role}", "pass", m.model))
            else:
                checks.append(Check(f"model_{role}", "warn", "models.%s.model not set (see `c/coli status`)" % role))

    if series is not None:
        try:
            state = load_state(series / "books" / book / "state.json")
            checks.append(Check("series_state", "pass", f"book {state.book}"))
        except BookforgeError as e:
            checks.append(Check("series_state", "fail", str(e)))
        else:
            if not vcs.is_repo(series):
                checks.append(Check("series_git", "fail", "not a git repository"))
            elif vcs.is_dirty(series):
                checks.append(Check("series_git", "warn", "uncommitted changes in the series"))
            else:
                checks.append(Check("series_git", "pass", "clean"))

    checks.append(Check("endpoints", "warn", "model endpoint and web tool checks arrive in milestone 14.2"))
    return checks
