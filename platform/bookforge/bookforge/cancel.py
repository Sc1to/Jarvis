"""Stopping a running job.

A job runs in its own thread. `cancel` sets that job's flag; `check()` is called before every model call, so the job
stops at the next one (a call already in flight finishes first, which can take a minute on a large model). `Cancelled` is a
BaseException on purpose: the many `except Exception` and `except BookforgeError` handlers that let a run survive one failed
page or one failed scene must not swallow a stop request. The runner catches it and leaves the work done so far in place;
an item that was not finished is simply done again on the next run.
"""

import threading

_local = threading.local()


class Cancelled(BaseException):
    """The author stopped the job."""


def bind(event: threading.Event | None) -> None:
    """Make `check()` in this thread watch `event` (None: stop watching)."""
    _local.event = event


def requested() -> bool:
    event = getattr(_local, "event", None)
    return event is not None and event.is_set()


def check() -> None:
    if requested():
        raise Cancelled()
