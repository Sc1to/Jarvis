import threading

import pytest

from bookforge.jobs import BusyError, JobManager


def test_only_one_job_runs_at_a_time_across_series(tmp_path):
    jobs = JobManager()
    release = threading.Event()
    first = jobs.start(tmp_path / "a", "a", "b1", "run", {}, lambda: (release.wait(5), {})[1])
    with pytest.raises(BusyError, match="another series is busy"):
        jobs.start(tmp_path / "b", "b", "b1", "run", {}, lambda: {})
    with pytest.raises(BusyError, match="series 'a' is busy"):
        jobs.start(tmp_path / "a", "a", "b1", "run", {}, lambda: {})
    release.set()
    jobs.wait(first.id, 5)
    second = jobs.start(tmp_path / "b", "b", "b1", "run", {}, lambda: {})  # free again once the first ended
    jobs.wait(second.id, 5)
    assert second.status == "done"
