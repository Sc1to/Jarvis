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


def test_unload_all_asks_ollama_to_unload_each_model_in_use():
    import httpx

    from bookforge.config import load_config
    from bookforge.model_admin import unload_all

    asked = []

    def handler(request):
        asked.append((request.url.path, request.read().decode()))
        return httpx.Response(200, json={})

    cfg = load_config()
    ollama = {"base_url": "http://127.0.0.1:11434/v1", "model": "qwen3.5:35b"}
    cfg.models.writer = cfg.models.writer.model_copy(update=ollama)
    cfg.models.critic = cfg.models.critic.model_copy(update=ollama)
    done = unload_all(cfg, httpx.MockTransport(handler))
    assert asked and all(path == "/api/generate" and '"keep_alive":0' in body.replace(" ", "") for path, body in asked)
    assert done == ["qwen3.5:35b"] and len(asked) == 1  # writer and critic share one model: unloaded once
