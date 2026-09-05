import uuid

_jobs: dict[str, dict] = {}


def create(meta: dict | None = None) -> tuple[str, dict]:
    job_id = uuid.uuid4().hex[:12]
    job: dict = {"status": "running", "tokens": "", "result": None, "error": None, "meta": meta or {}}
    _jobs[job_id] = job
    return job_id, job


def get(job_id: str) -> dict | None:
    return _jobs.get(job_id)
