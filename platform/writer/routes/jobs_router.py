from fastapi import APIRouter
import jobs as job_store

router = APIRouter()


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    from fastapi import HTTPException
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found — server may have restarted")
    return {
        "status": job["status"],
        "tokens": job["tokens"],
        "result": job["result"],
        "error": job["error"],
        "meta": job["meta"],
    }
