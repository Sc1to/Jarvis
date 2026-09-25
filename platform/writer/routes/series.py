import hashlib
import json
import os
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import db
import llm

router = APIRouter()


def _series_bible_path(series_id: str) -> str:
    return os.path.join(db.series_data_dir(series_id), "series_bible.json")


def _read_series_bible(series_id: str) -> dict:
    p = _series_bible_path(series_id)
    if not os.path.exists(p):
        return {"metadata": {}, "ledger": {}}
    with open(p) as f:
        return json.load(f)


def _write_series_bible(series_id: str, bible: dict) -> None:
    p = _series_bible_path(series_id)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        json.dump(bible, f, indent=2)


# ── CRUD ──────────────────────────────────────────────────────────────────────

class CreateSeriesBody(BaseModel):
    title: str


@router.get("/series")
def list_series():
    return db.list_series()


@router.post("/series", status_code=201)
def create_series(body: CreateSeriesBody):
    title = body.title.strip()
    if not title:
        raise HTTPException(400, "title required")
    series = db.create_series(title)
    db.ensure_series_data_dir(series["id"])
    _write_series_bible(series["id"], {
        "metadata": {
            "series_id": series["id"],
            "title": series["title"],
            "last_updated": datetime.now(timezone.utc).isoformat(),
        },
        "ledger": {},
    })
    return series


@router.get("/series/{series_id}")
def get_series(series_id: str):
    series = db.get_series(series_id)
    if not series:
        raise HTTPException(404, "Not found")
    return {**series, "books": db.list_books_in_series(series_id)}


@router.delete("/series/{series_id}")
def delete_series_route(series_id: str):
    if not db.get_series(series_id):
        raise HTTPException(404, "Not found")
    db.delete_series(series_id)
    return {"ok": True}


# ── Series Bible ──────────────────────────────────────────────────────────────

@router.get("/series/{series_id}/bible")
def get_series_bible(series_id: str):
    if not db.get_series(series_id):
        raise HTTPException(404, "Not found")
    return _read_series_bible(series_id)


class EntityBody(BaseModel):
    entity_id: str
    data: dict


@router.post("/series/{series_id}/bible/entity")
def upsert_series_entity(series_id: str, body: EntityBody):
    if not db.get_series(series_id):
        raise HTTPException(404, "Not found")
    bible = _read_series_bible(series_id)
    bible["ledger"][body.entity_id] = body.data
    bible.setdefault("metadata", {})["last_updated"] = datetime.now(timezone.utc).isoformat()
    _write_series_bible(series_id, bible)
    return {"ok": True, "entity_id": body.entity_id}


# ── North Star & Style Sheet ──────────────────────────────────────────────────

def read_series_text(series_id: str, filename: str) -> str:
    p = os.path.join(db.series_data_dir(series_id), filename)
    return open(p).read() if os.path.exists(p) else ""


def _write_series_text(series_id: str, filename: str, content: str) -> None:
    d = db.series_data_dir(series_id)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, filename), "w") as f:
        f.write(content)


class TextBody(BaseModel):
    content: str


@router.get("/series/{series_id}/north-star")
def get_series_north_star(series_id: str):
    if not db.get_series(series_id):
        raise HTTPException(404, "Not found")
    return {"content": read_series_text(series_id, "north_star.md")}


@router.post("/series/{series_id}/north-star")
def save_series_north_star(series_id: str, body: TextBody):
    if not db.get_series(series_id):
        raise HTTPException(404, "Not found")
    _write_series_text(series_id, "north_star.md", body.content)
    return {"ok": True}


@router.get("/series/{series_id}/style-sheet")
def get_series_style_sheet(series_id: str):
    if not db.get_series(series_id):
        raise HTTPException(404, "Not found")
    return {"content": read_series_text(series_id, "style_sheet.md")}


@router.post("/series/{series_id}/style-sheet")
def save_series_style_sheet(series_id: str, body: TextBody):
    if not db.get_series(series_id):
        raise HTTPException(404, "Not found")
    _write_series_text(series_id, "style_sheet.md", body.content)
    return {"ok": True}


# ── Series-scoped agent model overrides ─────────────────────────────────────
# Agent keys that fall back to another agent's model when unset, matching the
# fallback chain each real call site uses (see llm/db.resolve_agent callers).
_AGENT_FALLBACKS = {
    "beat_generator": "writer_agent",
    "beat_expander": "writer_agent",
    "text_op_expand": "writer_agent",
    "text_op_rephrase": "writer_agent",
    "text_op_notes": "qa_agent",
}
AGENT_KEYS = [
    "story_architect", "bible_agent", "research_agent", "writer_agent", "qa_agent", "bible_updater",
    "beat_generator", "beat_expander", "text_op_expand", "text_op_rephrase", "text_op_notes",
]


def _effective_agent(agent_key: str, series_id: str) -> tuple[str | None, str | None]:
    provider, model = db.resolve_agent(agent_key, series_id=series_id)
    fallback_key = _AGENT_FALLBACKS.get(agent_key)
    if not provider and fallback_key:
        provider, model = db.resolve_agent(fallback_key, series_id=series_id)
    return provider, model


class SeriesAgentModelBody(BaseModel):
    agent_key: str
    provider: str | None = None
    model: str | None = None


@router.get("/series/{series_id}/agent-models")
def get_series_agent_models(series_id: str):
    if not db.get_series(series_id):
        raise HTTPException(404, "Not found")
    overrides = db.get_series_agent_models(series_id)
    result = {}
    for key in AGENT_KEYS:
        override = overrides.get(key)
        eff_provider, eff_model = _effective_agent(key, series_id)
        result[key] = {
            "provider": override["provider"] if override else None,
            "model": override["model"] if override else None,
            "effective_provider": eff_provider,
            "effective_model": eff_model,
        }
    return result


@router.post("/series/{series_id}/agent-models")
def set_series_agent_model(series_id: str, body: SeriesAgentModelBody):
    if not db.get_series(series_id):
        raise HTTPException(404, "Not found")
    if body.agent_key not in AGENT_KEYS:
        raise HTTPException(400, f"Unknown agent key: {body.agent_key}")
    if body.provider and body.model:
        db.set_series_agent_model(series_id, body.agent_key, body.provider, body.model)
    else:
        db.clear_series_agent_model(series_id, body.agent_key)
    return {"ok": True}


# ── Style digest (compressed style sheet for QA) ──────────────────────────────
# QA checks style alignment on a sampled cadence rather than every scene, and
# uses this short digest rather than the full style sheet to keep its prompt
# small. The digest is cached and only regenerated when the style sheet text
# changes.

_STYLE_DIGEST_SYSTEM = """Compress this series style sheet into a short checklist a QA reviewer can use to judge whether a scene matches the series voice.

5-8 bullet points max. Cover POV/tense conventions, prose rhythm, recurring motifs, and any hard naming or wording rules. Drop rationale and examples — rules only.

Output the bullet list only. No preamble, no headers."""


def _style_digest_path(series_id: str) -> str:
    return os.path.join(db.series_data_dir(series_id), "style_digest.json")


async def get_style_digest(series_id: str, provider: str, model: str, user: str = "local") -> str:
    """Short, cached digest of the series style sheet for use in QA prompts.

    Regenerated only when the style sheet's content changes (tracked via hash),
    so QA runs against a stable, low-token summary instead of re-compressing
    the full style sheet on every check.
    """
    style_sheet = read_series_text(series_id, "style_sheet.md")
    if not style_sheet.strip():
        return ""

    source_hash = hashlib.sha256(style_sheet.encode()).hexdigest()
    cache_path = _style_digest_path(series_id)
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            cached = json.load(f)
        if cached.get("source_hash") == source_hash and cached.get("digest"):
            return cached["digest"]

    messages = [{"role": "user", "content": f"Series style sheet:\n\n{style_sheet}"}]
    digest = ""
    async for token in llm.provider_tokens(provider, model, messages, _STYLE_DIGEST_SYSTEM, user):
        digest += token
    digest = digest.strip()

    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump({"source_hash": source_hash, "digest": digest}, f, indent=2)
    return digest


# ── Promote book entity → series ─────────────────────────────────────────────

class PromoteEntityBody(BaseModel):
    entity_id: str


@router.post("/books/{book_id}/promote-entity")
def promote_entity_to_series(book_id: str, body: PromoteEntityBody):
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(404, "Book not found")
    series_id = book.get("series_id")
    if not series_id:
        raise HTTPException(400, "Book is not part of a series")

    book_bible_path = os.path.join(db.data_dir(book_id), "bible.json")
    if not os.path.exists(book_bible_path):
        raise HTTPException(400, "Book has no bible.json yet")

    with open(book_bible_path) as f:
        book_bible = json.load(f)

    entity = book_bible.get("ledger", {}).get(body.entity_id)
    if not entity:
        raise HTTPException(404, f"Entity {body.entity_id} not found in book bible")

    series_bible = _read_series_bible(series_id)
    series_ledger = series_bible.get("ledger", {})

    existing = series_ledger.get(body.entity_id, {})
    series_entry = {
        "type": entity.get("type", existing.get("type")),
        "name": entity.get("name", existing.get("name")),
        "series_facts": entity.get("series_facts", existing.get("series_facts", {})),
    }
    series_ledger[body.entity_id] = series_entry

    series_bible["ledger"] = series_ledger
    series_bible.setdefault("metadata", {})["last_updated"] = datetime.now(timezone.utc).isoformat()
    _write_series_bible(series_id, series_bible)

    return {"ok": True, "entity_id": body.entity_id}


# ── Extract entities from North Star ─────────────────────────────────────────

_ID_PREFIXES = {"character": "CHAR", "location": "LOC", "faction": "FRAC", "object": "OBJ"}

_EXTRACT_SYSTEM = """Extract all named characters, locations, factions, and significant objects from the text.
For each entity populate series_facts with permanent descriptive details:
- character: appearance, background, values, personality
- location: description, significance, atmosphere
- faction: purpose, ideology, membership
- object: appearance, significance

Return JSON only (no preamble, no fences):
{
  "entities": [
    {"type": "character", "name": "...", "series_facts": {"appearance": "...", "background": "...", "values": "...", "personality": "..."}},
    {"type": "location",  "name": "...", "series_facts": {"description": "...", "significance": "..."}},
    {"type": "faction",   "name": "...", "series_facts": {"purpose": "...", "ideology": "..."}},
    {"type": "object",    "name": "...", "series_facts": {"appearance": "...", "significance": "..."}}
  ]
}

Include only named, specific entities. Skip generic concepts."""


def _next_id(ledger: dict, prefix: str) -> str:
    nums = [int(k.split("_")[1]) for k in ledger if k.startswith(prefix + "_") and k.split("_")[1].isdigit()]
    return f"{prefix}_{(max(nums) + 1 if nums else 1):03d}"


def _extract_json_entities(text: str) -> list:
    text = text.strip()
    if "```json" in text:
        text = text[text.index("```json") + 7:]
        text = text[:text.index("```")]
    elif "```" in text:
        text = text[text.index("```") + 3:]
        text = text[:text.rindex("```")]
    s, e = text.find("{"), text.rfind("}") + 1
    if s != -1 and e:
        obj = json.loads(text[s:e])
        if "entities" in obj:
            return obj["entities"]
    s, e = text.find("["), text.rfind("]") + 1
    if s != -1 and e:
        return json.loads(text[s:e])
    raise ValueError("No JSON found")


@router.post("/series/{series_id}/extract-entities")
async def extract_entities_from_north_star(series_id: str):
    if not db.get_series(series_id):
        raise HTTPException(404, "Not found")

    north_star = read_series_text(series_id, "north_star.md")
    if not north_star.strip():
        raise HTTPException(400, "North Star is empty — write it first")

    provider, model = db.resolve_agent("bible_agent", series_id=series_id)
    if not provider or not model:
        raise HTTPException(400, "Bible Agent has no model assigned — go to Settings")

    messages = [{"role": "user", "content": f"## Series North Star\n\n{north_star}\n\nExtract all named entities."}]
    full_text = ""
    async for token in llm.provider_tokens(provider, model, messages, _EXTRACT_SYSTEM, "local", json_mode=True):
        full_text += token

    try:
        raw_entities = _extract_json_entities(full_text)
    except Exception as e:
        raise HTTPException(500, f"Could not parse LLM response: {e}")

    series_bible = _read_series_bible(series_id)
    ledger = series_bible.get("ledger", {})

    added = []
    for ent in raw_entities:
        etype = ent.get("type", "").lower()
        prefix = _ID_PREFIXES.get(etype)
        if not prefix or not ent.get("name"):
            continue
        eid = _next_id(ledger, prefix)
        ledger[eid] = {
            "type": etype,
            "name": ent["name"],
            "series_facts": ent.get("series_facts", {}),
        }
        added.append({"id": eid, "name": ent["name"], "type": etype})

    series_bible["ledger"] = ledger
    series_bible.setdefault("metadata", {})["last_updated"] = datetime.now(timezone.utc).isoformat()
    _write_series_bible(series_id, series_bible)

    return {"ok": True, "added": len(added), "entities": added}
