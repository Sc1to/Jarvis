"""What a running job is doing right now, for the dashboard.

A job runs in its own thread (`jobs.py`). `bind` gives that thread a dict; the helpers below fill it in as the work goes on,
and the status route returns it with the job, so the Overview can say "writing drafts for b1.ch03.s2, waiting for the model for
84 s" instead of only "running". Everything is a no-op when nothing is bound (the CLI, the tests), so the pipeline code can call it
freely. In memory only: the job runs inside the API process, and a restart ends the job anyway.
"""

import threading
from datetime import datetime, timezone

_local = threading.local()
LABEL_CHARS = 70


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def bind(state: dict | None) -> None:
    """Make the helpers in this thread write into `state` (None: stop)."""
    _local.state = state


def _state() -> dict | None:
    return getattr(_local, "state", None)


def set(**fields) -> None:  # noqa: A001 - reads naturally at the call site: activity.set(scene=...)
    s = _state()
    if s is not None:
        s.update(fields)


def add(name: str, n: int = 1) -> None:
    s = _state()
    if s is not None:
        s[name] = int(s.get(name, 0)) + n


def call_started(role: str, label: str) -> None:
    s = _state()
    if s is not None:
        s.update(call_started=_now(), call_role=role, call_label=" ".join(label.split())[:LABEL_CHARS])
        s["calls"] = int(s.get("calls", 0)) + 1


def call_finished() -> None:
    s = _state()
    if s is not None:
        s.pop("call_started", None)
        s.pop("call_role", None)
        s.pop("call_label", None)
        s["last_call_finished"] = _now()
