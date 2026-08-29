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

    provider = db.get_setting("agent_bible_agent_provider")
    model = db.get_setting("agent_bible_agent_model")
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
