"""Background jobs for the HTTP service: a pipeline run takes hours, so a request starts it and returns.

One job at a time per series (the series is one Git repository and one set of state files), and one at a time
overall, because every series uses the same model server and two series at once mixed up their stories. A job's record
is saved to `books/<book>/logs/jobs/<id>.json` when it starts and again when it ends, so the history survives
a restart; a record still saying `running` that this process does not know about is shown as `interrupted`.
"""

import json
import logging
import secrets
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import activity, cancel
from .errors import BookforgeError

log = logging.getLogger("platform_bookforge.jobs")


class BusyError(BookforgeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Job:
    id: str
    series: str
    book: str
    kind: str  # run | stale-fix | bench
    status: str = "running"  # running | done | failed | interrupted | cancelled
    cancel_requested: bool = False  # the author asked it to stop; it stops at its next model call
    activity: dict = field(default_factory=dict)  # what it is doing now: layer, scene, step, model calls (see activity.py)
    started: str = field(default_factory=_now)
    finished: str | None = None
    params: dict = field(default_factory=dict)
    result: dict | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class JobManager:
    def __init__(self) -> None:
        self.on_finish: Callable[[Job], None] | None = None  # called in the job's thread after it has ended
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._active: dict[str, str] = {}  # series -> job id
        self._threads: dict[str, threading.Thread] = {}
        self._stops: dict[str, threading.Event] = {}

    def busy(self, series: str) -> Job | None:
        with self._lock:
            jid = self._active.get(series)
            return self._jobs.get(jid) if jid else None

    def start(self, root: Path, series: str, book: str, kind: str, params: dict, fn: Callable[[], dict]) -> Job:
        """Run `fn` in a thread. `fn` returns the job's result (a JSON-able dict); an exception fails the job."""
        with self._lock:
            if series in self._active:
                current = self._jobs[self._active[series]]
                raise BusyError(f"series '{series}' is busy: {current.kind} job {current.id} is {current.status}")
            if self._active:
                # The models are one shared server. Found on a real run: with two series working at once, a reply for one
                # series described the other series' story. So only one job runs at a time, whichever series it is for.
                other_series, other_id = next(iter(self._active.items()))
                other = self._jobs[other_id]
                raise BusyError(f"another series is busy: {other.kind} job {other.id} in '{other_series}' is {other.status}; "
                                "jobs run one at a time because they share the model server. Pause it or wait for it to finish.")
            job = Job(id=datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(2),
                      series=series, book=book, kind=kind, params=params)
            self._jobs[job.id] = job
            self._active[series] = job.id
            self._stops[job.id] = threading.Event()
        self._save(root, job)
        thread = threading.Thread(target=self._run, args=(root, job, fn), name=f"bookforge-{job.id}", daemon=True)
        self._threads[job.id] = thread
        thread.start()
        return job

    def cancel(self, root: Path, series: str, job_id: str | None = None) -> Job:
        """Ask the running job of a series to stop. It does so at its next model call."""
        with self._lock:
            jid = self._active.get(series)
            job = self._jobs.get(jid) if jid else None
            if job is None or (job_id is not None and job.id != job_id):
                raise BookforgeError(f"no running job to stop in series '{series}'")
            job.cancel_requested = True
            self._stops[job.id].set()
        self._save(root, job)
        return job

    def _run(self, root: Path, job: Job, fn: Callable[[], dict]) -> None:
        stop = self._stops.get(job.id)
        cancel.bind(stop)
        activity.bind(job.activity)
        try:
            result = fn()
            job.result, job.status = result, ("cancelled" if stop is not None and stop.is_set() else "done")
        except cancel.Cancelled:
            job.status = "cancelled"
        except Exception as e:  # a failed job is recorded, never a dead thread with no trace
            log.exception("job %s failed", job.id)
            job.error, job.status = str(e) or e.__class__.__name__, "failed"
        finally:
            cancel.bind(None)
            activity.bind(None)
            job.finished = _now()
            self._save(root, job)
            with self._lock:
                if self._active.get(job.series) == job.id:
                    del self._active[job.series]
            if self.on_finish:
                try:
                    self.on_finish(job)
                except Exception:  # a notification problem must not turn a finished job into a dead thread
                    log.exception("on_finish failed for job %s", job.id)

    def wait(self, job_id: str, timeout: float | None = None) -> None:
        """Block until a job ends (tests)."""
        thread = self._threads.get(job_id)
        if thread:
            thread.join(timeout)

    @staticmethod
    def _dir(root: Path, book: str) -> Path:
        return root / "books" / book / "logs" / "jobs"

    def _save(self, root: Path, job: Job) -> None:
        try:
            d = self._dir(root, job.book)
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{job.id}.json").write_text(json.dumps(job.to_dict(), indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        except OSError as e:
            log.warning("could not save job record %s: %s", job.id, e)

    def get(self, root: Path, series: str, book: str, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
        if job and job.series == series and job.book == book:
            return job.to_dict()
        return self._read(self._dir(root, book) / f"{job_id}.json")

    def list(self, root: Path, series: str, book: str) -> list[dict]:
        with self._lock:
            live = {j.id: j.to_dict() for j in self._jobs.values() if j.series == series and j.book == book}
        d = self._dir(root, book)
        for path in sorted(d.glob("*.json")) if d.is_dir() else []:
            if path.stem not in live and (rec := self._read(path)):
                live[path.stem] = rec
        return sorted(live.values(), key=lambda j: j["id"], reverse=True)

    @staticmethod
    def _read(path: Path) -> dict | None:
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if rec.get("status") == "running":
            rec["status"] = "interrupted"  # saved as running by a process that is gone
        return rec
