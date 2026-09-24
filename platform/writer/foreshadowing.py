"""
Per-book foreshadowing seed catalog (WRITER_SPEC.md §4.4).

Stored in <book_dir>/foreshadowing_brief.json so it is versioned with the book:
  {
    "seeds": [
      {
        "id": "SEED_001",
        "description": "...",                    # plant-only wording, no plot context
        "plant_act_range": {"from": 1, "to": 2},
        "payoff_act": 3,
        "status": "unplanted" | "planted" | "resolved",
        "planted_at": {"chapter": 5, "act": 2} | null,
        "resolved_at": {"chapter": 14, "act": 3} | null
      }
    ]
  }

Seeds are tracked at chapter/act granularity, not the exact-scene precision
WRITER_SPEC.md §4.4 describes — scene numbers don't exist until each
chapter's Tier 4 is individually approved, long after a seed may be created
and long before its payoff chapter is reached. The exact scene a seed is
planted or resolved in is decided by the Tier 4 scene-list step itself
(see routes/phase1.py), recorded as Plants:/Resolves: on that scene; this
module only tracks which act a seed is open in and whether it's been used.
"""
import json
import os

import db

FILE_NAME = "foreshadowing_brief.json"


def _path(book_id: str) -> str:
    return os.path.join(db.data_dir(book_id), FILE_NAME)


def read(book_id: str) -> dict:
    data: dict = {}
    p = _path(book_id)
    if os.path.exists(p):
        try:
            with open(p) as f:
                data = json.load(f)
        except Exception:
            data = {}
    return normalise(data)


def write(book_id: str, data: dict) -> dict:
    clean = normalise(data)
    with open(_path(book_id), "w") as f:
        json.dump(clean, f, indent=2)
    return clean


def _normalise_seed(raw: dict) -> dict | None:
    seed_id = str(raw.get("id") or "").strip()
    description = str(raw.get("description") or "").strip()
    if not seed_id or not description:
        return None

    plant_range = raw.get("plant_act_range") or {}
    try:
        plant_from = int(plant_range.get("from"))
        plant_to = int(plant_range.get("to"))
    except (TypeError, ValueError):
        return None

    try:
        payoff_act = int(raw.get("payoff_act"))
    except (TypeError, ValueError):
        return None

    status = raw.get("status")
    if status not in ("unplanted", "planted", "resolved"):
        status = "unplanted"

    return {
        "id": seed_id,
        "description": description,
        "plant_act_range": {"from": plant_from, "to": plant_to},
        "payoff_act": payoff_act,
        "status": status,
        "planted_at": raw.get("planted_at") if isinstance(raw.get("planted_at"), dict) else None,
        "resolved_at": raw.get("resolved_at") if isinstance(raw.get("resolved_at"), dict) else None,
    }


def normalise(data: dict) -> dict:
    seeds = []
    for raw in data.get("seeds") or []:
        if not isinstance(raw, dict):
            continue
        seed = _normalise_seed(raw)
        if seed:
            seeds.append(seed)
    return {"seeds": seeds}


def seeds_open_for_planting(book_id: str, act: int) -> list[dict]:
    """Unplanted seeds whose plant window covers this act."""
    return [
        s for s in read(book_id)["seeds"]
        if s["status"] == "unplanted" and s["plant_act_range"]["from"] <= act <= s["plant_act_range"]["to"]
    ]


def seeds_open_for_resolution(book_id: str, act: int) -> list[dict]:
    """Planted seeds due to pay off in this act."""
    return [
        s for s in read(book_id)["seeds"]
        if s["status"] == "planted" and s["payoff_act"] == act
    ]


def seed_by_id(book_id: str, seed_id: str) -> dict | None:
    return next((s for s in read(book_id)["seeds"] if s["id"] == seed_id), None)


def mark_planted(book_id: str, seed_ids: list[str], chapter: int, act: int) -> dict:
    data = read(book_id)
    ids = set(seed_ids)
    for s in data["seeds"]:
        if s["id"] in ids and s["status"] == "unplanted":
            s["status"] = "planted"
            s["planted_at"] = {"chapter": chapter, "act": act}
    return write(book_id, data)


def mark_resolved(book_id: str, seed_ids: list[str], chapter: int, act: int) -> dict:
    data = read(book_id)
    ids = set(seed_ids)
    for s in data["seeds"]:
        if s["id"] in ids and s["status"] == "planted":
            s["status"] = "resolved"
            s["resolved_at"] = {"chapter": chapter, "act": act}
    return write(book_id, data)
