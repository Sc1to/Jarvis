"""
Text operation tools for the author edit view.

These endpoints are stateless — they receive only the selected prose text plus
novel.genre and novel.language extracted from writing_prefs.md. No bible, no ledger.
"""

import os

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import db
from deps import current_user
import llm
import prompt_store

router = APIRouter()

TEXT_OP_EXPAND_SYSTEM = """You are an expert prose editor.

Whenever you're given text, expand it according to the instructions below.
Imitate the current writing style exactly — keep mannerisms, word choice,
and sentence structure intact. Use the same tense and voice.

Expand the text by fleshing out the details, descriptions, and context.

If the original contains dialogue, preserve the substance but adjust wording
as needed to reach the target length. Split into new paragraphs where natural:
a location change, a new action starting, or someone beginning to speak.

Only return the expanded text, nothing else."""

TEXT_OP_REPHRASE_SYSTEM = """You are an expert prose editor.

Rephrase the following text according to the instruction provided.
Imitate and keep the current writing style — leave mannerisms, word choice,
and sentence structure intact. Use the same tense and voice.

Only return the rephrased text, nothing else."""

TEXT_OP_NOTES_SYSTEM = """You are an expert editor familiar with {genre} fiction.

The author has provided a scene for feedback. Give specific, actionable notes on:
- Voice consistency with the established narrative style
- Pacing — where it moves well, where it stalls
- Show vs. tell — flag abstract summary statements
- Dialogue — does it advance the scene or stall it?
- Any canon flags you can identify from context

Be direct. Point to specific sentences where relevant.
Write your response in Markdown. Use {language} spelling."""


def _extract_prefs(book_id: str) -> tuple[str, str]:
    """Extract genre and language from writing_prefs.md as a best-effort parse."""
    p = os.path.join(db.data_dir(book_id), "writing_prefs.md")
    if not os.path.exists(p):
        return "literary", "British English"
    content = open(p).read()
    genre = "literary"
    language = "British English"
    for line in content.splitlines():
        lower = line.lower()
        if "genre" in lower and ":" in line:
            val = line.split(":", 1)[1].strip()
            if val and val.lower() != "not specified":
                genre = val
        if "language" in lower and ":" in line:
            val = line.split(":", 1)[1].strip()
            if val and val.lower() != "not specified":
                language = val
    return genre, language


def _sse(event: dict) -> str:
    import json
    return f"data: {json.dumps(event)}\n\n"


class ExpandBody(BaseModel):
    scene_prose: str


class RephraseBody(BaseModel):
    scene_prose: str
    instruction: str


class EditorialNotesBody(BaseModel):
    scene_prose: str


@router.post("/books/{book_id}/text-ops/expand")
def expand_selection(book_id: str, body: ExpandBody, user: str = Depends(current_user)):
    async def generate():
        provider = db.get_setting("agent_text_op_expand_provider") or db.get_setting("agent_writer_agent_provider")
        model = db.get_setting("agent_text_op_expand_model") or db.get_setting("agent_writer_agent_model")
        if not provider or not model:
            yield _sse({"type": "error", "message": "No model configured — assign one in Settings or configure the Writer agent."})
            return

        system = prompt_store.get("text_op_expand", TEXT_OP_EXPAND_SYSTEM)
        try:
            async for token in llm.provider_tokens(
                provider, model,
                [{"role": "user", "content": body.scene_prose}],
                system,
                user,
            ):
                yield _sse({"type": "token", "content": token})
        except Exception as e:
            yield _sse({"type": "error", "message": str(e)})
            return
        yield _sse({"type": "done"})

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/books/{book_id}/text-ops/rephrase")
def rephrase_selection(book_id: str, body: RephraseBody, user: str = Depends(current_user)):
    async def generate():
        provider = db.get_setting("agent_text_op_rephrase_provider") or db.get_setting("agent_writer_agent_provider")
        model = db.get_setting("agent_text_op_rephrase_model") or db.get_setting("agent_writer_agent_model")
        if not provider or not model:
            yield _sse({"type": "error", "message": "No model configured — assign one in Settings or configure the Writer agent."})
            return

        system = prompt_store.get("text_op_rephrase", TEXT_OP_REPHRASE_SYSTEM)
        user_msg = f"Instruction: {body.instruction}\n\nText to rephrase:\n\n{body.scene_prose}"
        try:
            async for token in llm.provider_tokens(
                provider, model,
                [{"role": "user", "content": user_msg}],
                system,
                user,
            ):
                yield _sse({"type": "token", "content": token})
        except Exception as e:
            yield _sse({"type": "error", "message": str(e)})
            return
        yield _sse({"type": "done"})

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/books/{book_id}/text-ops/editorial-notes")
async def editorial_notes(book_id: str, body: EditorialNotesBody, user: str = Depends(current_user)):
    provider = db.get_setting("agent_text_op_notes_provider") or db.get_setting("agent_qa_agent_provider")
    model = db.get_setting("agent_text_op_notes_model") or db.get_setting("agent_qa_agent_model")
    if not provider or not model:
        return {"error": "No model configured — assign one in Settings or configure the QA agent."}

    genre, language = _extract_prefs(book_id)
    system = prompt_store.get("text_op_notes", TEXT_OP_NOTES_SYSTEM).format(
        genre=genre, language=language
    )
    result = ""
    async for token in llm.provider_tokens(provider, model, [{"role": "user", "content": body.scene_prose}], system, user):
        result += token
    return {"notes": result}
