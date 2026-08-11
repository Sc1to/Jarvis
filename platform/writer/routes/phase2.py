import json
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

import db
import llm
from deps import current_user

router = APIRouter()

CONSOLIDATOR_SYSTEM = """You are the Bible Consolidator. Extract every named entity from the approved story bible tiers and produce a structured JSON entity ledger.

Rules:
- Assign unique IDs: CHAR_001, CHAR_002, LOC_001, LOC_002, FRAC_001, OBJ_001, etc.
- Include every named character, location, faction, and significant object
- For each entity, list all alias forms (name variants, role descriptions, nicknames, pronouns used)
- coreFacts: 3-6 key timeless facts (for characters: appearance, personality, role; for locations: geography, culture, period setting)
- eventLog: concrete events from the tier text, tagged to act and chapter number
- lifecycle: list of act numbers where this entity is active

Output ONLY valid JSON. No preamble, no explanation, no markdown fences. Structure:
{
  "ledger": {
    "ID": {
      "type": "character|location|faction|object",
      "name": "canonical name",
      "aliases": ["variant 1", "role description"],
      "coreFacts": {"key": "value"},
      "eventLog": [{"act": 1, "chapter": 1, "event": "what happens"}],
      "lifecycle": [1, 2, 3]
    }
  }
}"""

RESEARCH_SYSTEM = """You are the Research & Completion Agent. Enrich and complete the entity ledger from the story bible.

For each entity:
1. If any entity is a placeholder (identified by role rather than a real name), invent a complete identity: full period-appropriate name, physical description, speech mannerisms, backstory, and relationships to existing ledger entries
2. Add authentic period detail to location entries: culture, architecture, customs, relevant historical context if the story is set in a real period
3. Add a "relationships" map to character entries where relationships to other entities are evident
4. If you detect internal contradictions between entities, add a "flags" list: [{"issue": "description", "severity": "warning|error"}]

Return ONLY the complete enriched ledger as valid JSON. Same structure as input — make additions only, never deletions. No preamble, no markdown fences."""


def _extract_json(text: str) -> dict:
    text = text.strip()
    if "```json" in text:
        text = text[text.index("```json") + 7:]
        text = text[:text.index("```")]
    elif "```" in text:
        text = text[text.index("```") + 3:]
        text = text[:text.rindex("```")]
    # Find outermost braces
    start = text.find("{")
    end = text.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError("No JSON object found in response")
    return json.loads(text[start:end])


def _read_tiers(book_dir: str) -> list[dict]:
    path = os.path.join(book_dir, "tiers.json")
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return json.load(f)


def _bible_path(book_id: str) -> str:
    return os.path.join(db.data_dir(book_id), "bible.json")


def _read_bible(book_id: str) -> dict | None:
    p = _bible_path(book_id)
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)


# ── Status ─────────────────────────────────────────────────────────────────────

@router.get("/books/{book_id}/phase2/status")
def phase2_status(book_id: str):
    tiers = _read_tiers(book_id)
    phase1_complete = len(tiers) == 4 and all(t.get("approved") for t in tiers)

    bible = _read_bible(book_id)
    bible_exists = bible is not None
    meta = bible.get("metadata", {}) if bible else {}

    return {
        "phase1_complete": phase1_complete,
        "bible_exists": bible_exists,
        "phase2_status": meta.get("phase2_status", "idle"),
        "phase2_approved": meta.get("phase2_approved", False),
        "entity_count": len(bible.get("ledger", {})) if bible else 0,
    }


# ── Consolidate ────────────────────────────────────────────────────────────────

@router.post("/books/{book_id}/phase2/consolidate")
def consolidate(book_id: str, user: str = Depends(current_user)):
    async def generate():
        provider = db.get_setting("agent_bible_agent_provider")
        model = db.get_setting("agent_bible_agent_model")
        if not provider or not model:
            yield f'data: {json.dumps({"type": "error", "message": "Bible Agent has no model assigned — go to Settings."})}\n\n'
            return

        book_dir = db.data_dir(book_id)
        yield f'data: {json.dumps({"type": "status", "message": "Reading approved tiers…"})}\n\n'

        ns_path = os.path.join(book_dir, "north_star.md")
        north_star = open(ns_path).read() if os.path.exists(ns_path) else ""

        tiers = _read_tiers(book_id)
        tier_labels = ["Book", "Acts", "Chapters", "Scenes"]
        tier_text = "\n\n".join(
            f"## Tier {i + 1} — {tier_labels[i]}\n\n{t['content']}"
            for i, t in enumerate(tiers)
            if t.get("approved") and t.get("content")
        )

        context = f"## North Star\n\n{north_star}\n\n{tier_text}"
        messages = [{"role": "user", "content": f"Extract the entity ledger from this story bible:\n\n{context}"}]

        yield f'data: {json.dumps({"type": "status", "message": "Running Bible Consolidator…"})}\n\n'

        full_text = ""
        try:
            async for token in llm.provider_tokens(provider, model, messages, CONSOLIDATOR_SYSTEM, user):
                full_text += token
                yield f'data: {json.dumps({"type": "token", "content": token})}\n\n'
        except Exception as e:
            yield f'data: {json.dumps({"type": "error", "message": str(e)})}\n\n'
            return

        try:
            bible = _extract_json(full_text)
        except Exception as e:
            yield f'data: {json.dumps({"type": "error", "message": f"Could not parse JSON response: {e}"})}\n\n'
            return

        if "ledger" not in bible:
            bible = {"ledger": bible}

        bible["metadata"] = {
            "consolidated_at": datetime.now(timezone.utc).isoformat(),
            "phase2_status": "consolidated",
            "phase2_approved": False,
        }

        with open(_bible_path(book_id), "w") as f:
            json.dump(bible, f, indent=2)

        from git import Repo
        repo = Repo(book_dir)
        repo.index.add(["bible.json"])
        repo.index.commit("Phase 2 — Consolidate entity ledger from approved tiers")

        entity_count = len(bible.get("ledger", {}))
        yield f'data: {json.dumps({"type": "saved", "entity_count": entity_count})}\n\n'

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Research & Complete ────────────────────────────────────────────────────────

@router.post("/books/{book_id}/phase2/run")
def research_run(book_id: str, user: str = Depends(current_user)):
    async def generate():
        provider = db.get_setting("agent_research_agent_provider")
        model = db.get_setting("agent_research_agent_model")
        if not provider or not model:
            yield f'data: {json.dumps({"type": "error", "message": "Research Agent has no model assigned — go to Settings."})}\n\n'
            return

        book_dir = db.data_dir(book_id)
        bible = _read_bible(book_id)
        if not bible:
            yield f'data: {json.dumps({"type": "error", "message": "Run consolidation first."})}\n\n'
            return

        ns_path = os.path.join(book_dir, "north_star.md")
        north_star = open(ns_path).read() if os.path.exists(ns_path) else ""

        yield f'data: {json.dumps({"type": "status", "message": "Running Research & Completion Agent…"})}\n\n'

        ledger_json = json.dumps(bible.get("ledger", {}), indent=2)
        messages = [{"role": "user", "content": f"## North Star\n\n{north_star}\n\n## Current Entity Ledger\n\n{ledger_json}\n\nEnrich and complete this ledger."}]

        full_text = ""
        try:
            async for token in llm.provider_tokens(provider, model, messages, RESEARCH_SYSTEM, user):
                full_text += token
                yield f'data: {json.dumps({"type": "token", "content": token})}\n\n'
        except Exception as e:
            yield f'data: {json.dumps({"type": "error", "message": str(e)})}\n\n'
            return

        try:
            enriched_ledger = _extract_json(full_text)
        except Exception as e:
            yield f'data: {json.dumps({"type": "error", "message": f"Could not parse JSON response: {e}"})}\n\n'
            return

        if "ledger" in enriched_ledger:
            enriched_ledger = enriched_ledger["ledger"]

        original_ledger = bible.get("ledger", {})
        bible_diff = {
            "phase": 2,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "added_fields": {
                eid: [k for k in enriched_ledger.get(eid, {}) if k not in original_ledger.get(eid, {})]
                for eid in enriched_ledger
            },
        }

        bible["ledger"] = enriched_ledger
        bible["metadata"]["phase2_status"] = "researched"
        bible["metadata"]["researched_at"] = datetime.now(timezone.utc).isoformat()

        with open(_bible_path(book_id), "w") as f:
            json.dump(bible, f, indent=2)

        diff_path = os.path.join(book_dir, "bible_diff.json")
        with open(diff_path, "w") as f:
            json.dump(bible_diff, f, indent=2)

        from git import Repo
        repo = Repo(book_dir)
        repo.index.add(["bible.json", "bible_diff.json"])
        repo.index.commit("Phase 2 — Research & entity completion")

        yield f'data: {json.dumps({"type": "saved", "entity_count": len(enriched_ledger)})}\n\n'

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Approve ────────────────────────────────────────────────────────────────────

@router.post("/books/{book_id}/phase2/approve")
def phase2_approve(book_id: str):
    bible = _read_bible(book_id)
    if not bible:
        return {"error": "No bible.json found — run consolidation first"}

    bible.setdefault("metadata", {})
    bible["metadata"]["phase2_approved"] = True
    bible["metadata"]["phase2_approved_at"] = datetime.now(timezone.utc).isoformat()
    bible["metadata"]["phase2_status"] = "approved"

    with open(_bible_path(book_id), "w") as f:
        json.dump(bible, f, indent=2)

    from git import Repo
    repo = Repo(db.data_dir(book_id))
    repo.index.add(["bible.json"])
    repo.index.commit("Phase 2 approved — Writing Loop unlocked")

    return {"ok": True, "entity_count": len(bible.get("ledger", {}))}
