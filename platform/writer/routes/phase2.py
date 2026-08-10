from fastapi import APIRouter

router = APIRouter()


@router.get("/books/{book_id}/phase2/status")
def phase2_status(book_id: str):
    return {"status": "idle"}


@router.post("/books/{book_id}/phase2/run")
def phase2_run(book_id: str):
    return {"ok": True}


@router.post("/books/{book_id}/phase2/approve")
def phase2_approve(book_id: str):
    return {"ok": True}
