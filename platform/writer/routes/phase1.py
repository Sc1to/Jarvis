import json
import os
import re
from datetime import datetime, timezone

import asyncio

from fastapi import APIRouter, Depends
from git import Repo
from pydantic import BaseModel

import db
import jobs as job_store
import llm
import prompt_store
from deps import current_user

router = APIRouter()

STORY_ARCHITECT_SYSTEM = """You are the Story Architect — a creative collaborator helping an author develop the North Star document for their specific novel.

Your job is to draw out their vision through conversation. Ask one or two focused questions per response. When you sense they have a strong handle on premise, protagonist, conflict, world, theme, and landing, tell them you have enough and invite them to lock it.

Keep responses to 150-250 words. Weave questions into prose — never bullet them."""

WRITING_PREFS_PROMPT = """From our conversation, extract the author's stated writing preferences for this novel.

Write a concise specification covering:

## Voice & Tone
The narrative register and emotional atmosphere (e.g. dry and sardonic, lyrical and introspective, spare and documentary). Use only what the author stated or clearly implied.

## Point of View
POV and narrative distance (e.g. close third-person limited, first-person unreliable narrator). If not discussed, write "Not specified".

## Tense
Past or present tense. If not discussed, write "Not specified".

## Target Length
Words per scene or chapter if mentioned. If not mentioned, write "Not specified".

## Style Constraints
Any explicit stylistic rules the author mentioned (e.g. no adverbs, short sentences, no chapter epigraphs, specific dialogue punctuation preferences).

## Genre & Audience
Genre and intended reader if stated.

## Prose Rhythm
How sentence length and paragraph structure should work in this novel. If the author did not address this, write: "Vary sentence length. Mix short punchy sentences (3–7 words) with longer ones (20–30 words). Never three long sentences in a row. New paragraph at action shifts."

## Dialogue
Rules for how dialogue should be written and attributed. If the author did not address this, write: "No adverbs on dialogue tags. Attribute through action or expression adjacent to the line, not speech-tag verbs. Every exchange must advance the scene — never stall or recap."

## What to Avoid
Patterns the author wants to prohibit. If not stated, write: "Adverbs modifying dialogue tags. Abstract emotional summary (e.g. 'he felt afraid'). Rhetorical questions in narration. Head-hopping between POV characters within a scene."

Rules:
- For Voice & Tone, POV, Tense, Target Length, Style Constraints, Genre & Audience: only include what came from the conversation — write "Not specified" if nothing was said
- For Prose Rhythm, Dialogue, What to Avoid: use the author's stated preferences if available; otherwise use the sensible craft defaults shown above
- Use the author's own words where possible
- 300-500 words total. Specificity over completeness."""

SYNTHESIS_PROMPT = """Write the North Star document now using only the specific details from our conversation. This is locked as a hard constraint for every AI agent on this project.

Rules:
- Use the actual character names, place names, and events from our conversation — never placeholders like "[protagonist]" or "[location]"
- Write statements of fact about this novel, not descriptions of what the novel will contain
- Wrong: "The protagonist faces a difficult choice about loyalty"
- Right: "Hamid refuses to translate the crusaders' demands to the Constantinople merchants, even when threatened"

Format as clean markdown:
## Premise
## Protagonist
## Conflict
## World
## Theme
## Landing

500-800 words. Specificity over elegance."""

BIBLE_AGENT_SYSTEM = """You are the Bible Agent. You write the structural bible for a specific novel, tier by tier, from the North Star document and any approved earlier tiers.

Critical rules:
- Write actual content about this specific novel — never describe what content will go here
- Use the real character names, place names, factions, and events from the North Star; never placeholders like "[protagonist]" or "[city]"
- Every entry state and exit state must be a concrete, verifiable fact about the story world at that moment
- Wrong: "The protagonist arrives at an important location and meets a key figure"
- Right: "Hamid arrives at the Constantinople harbour. The Venetian fleet is anchored in the Golden Horn. Brother Tomás is waiting on the dock."
- Output ONLY the requested tier. No preamble, no commentary, no "Here is the tier:" — just the content."""

TIER_EDITOR_SYSTEM = """You are a copy editor. Your job is to apply one specific change to a document.

You MUST copy the document verbatim — character by character — except for the single part the author asked to change.
Do not rephrase, restructure, summarise, or rewrite anything you were not asked to change.
If you are unsure what to change, change as little as possible.
Output only the modified document. No preamble, no explanation."""

SCENE_WRITER_SYSTEM = """You are a scene development editor. Write a detailed scene brief for one specific scene — not prose.

Output the brief using these exact sections:

## Location
Specific geographical setting: place name, interior/exterior, time of day, relevant physical details.

## Mood
The dominant emotional atmosphere of the scene (e.g. tense, melancholic, hopeful, threatening). How it should feel to the reader.

## Characters Present
Each character with their emotional state and goal entering this scene.

## Scene Beats
Numbered list of what happens, in order. Concrete actions and decisions — no prose sentences, just clear beats.

## Key Dialogue Points
The exchanges or lines that must occur. Paraphrase is fine — capture intent, not exact wording.

## Sensory & Atmosphere Notes
Specific sensory details (sounds, smells, light, weather, texture) that should colour the scene.

## Entry / Exit State
- Entry: [world state at scene open]
- Exit: [world state at scene close — this is the QA contract]

Rules:
- Use specific character names, locations, and facts from the story bible and North Star
- No prose — bullets and short sentences only
- Be specific, not vague"""

SCENE_BIBLE_SYNC_SYSTEM = """You are a story bible updater. Given an approved scene and the current entity skeleton, identify any NEW entities in the scene not yet in the skeleton.

Output ONLY valid JSON:
{
  "new_entities": [
    {"id": "CHAR_004", "name": "full name", "type": "character|location|faction|object", "aliases": [], "coreFacts": {}, "appearsInActs": []}
  ]
}

Rules:
- Only list entities NOT already in the skeleton (check by name and all aliases)
- IDs continue from the highest existing ID of that type (e.g. if CHAR_003 exists, next is CHAR_004)
- If no new entities, return {"new_entities": []}
- Output ONLY the JSON — no preamble, no explanation, no markdown fences"""

MINI_CONSOLIDATOR_SYSTEM = """You are a story bible extractor. Extract a structured entity skeleton from a novel's North Star document and act breakdown.

Output ONLY valid JSON — no preamble, no fences, no commentary.

Schema:
{
  "acts": [{"number": 1, "title": "Act title as written"}],
  "entities": [
    {
      "id": "CHAR_001",
      "name": "Full name as used in text",
      "type": "character | location | faction | object",
      "aliases": ["alternate names or titles"],
      "coreFacts": {"key": "value — only facts directly stated in the source"},
      "appearsInActs": [1, 2]
    }
  ]
}

Rules:
- Acts: extract from act headers in the breakdown (### Act N — [Title])
- Entity IDs: CHAR_001… for characters, LOC_001… for locations, FRAC_001… for factions, OBJ_001… for objects. Number sequentially per type.
- Only extract entities explicitly named in the source — never invent or infer
- coreFacts: only facts directly stated — role, nationality, relationship, physical trait. No invented backstory.
- appearsInActs: list act numbers where the entity is explicitly mentioned
- Include every named character, named location, faction, and significant named object"""

TIER_LABELS = ["Book", "Acts", "Chapters", "Scenes"]

TIER_INSTRUCTIONS = [
    """Write the Tier 1 Book synopsis for this novel.
3-5 paragraphs of narrative: the full journey from opening to ending, the protagonist's arc, the central turning points, how it resolves. Use the specific names, places, and events from the North Star.
Format: ## Book Synopsis""",

    """Write the Tier 2 act breakdown for this novel.
3-4 acts. For each act: its title and scope, the dramatic question it poses, how it opens and closes (one concrete sentence each), and 2-3 specific key events with named characters and places.
Format: ### Act N — [Title]""",

    """Write the chapter summaries for the current act only (see ## Current Act above).

List every chapter in this act. For each chapter:

### Chapter N — [Title]
**Act:** {act}.{position} (e.g. 2.1 for first chapter of act 2, 2.2 for second)
**Entry:** [concrete world state at chapter open — named characters, place, situation]
**Exit:** [concrete world state at chapter end — what has changed]

[2-3 sentence summary using specific character names and events from the North Star and story bible]

Critical rules:
- This act only — do not write chapters for other acts
- Derive the chapter count from the act's scope in the act breakdown; typically 3-6 chapters per act
- Entry and Exit must be different concrete facts, not restatements of each other
- Use real names from the entity ledger and North Star — never placeholders like [protagonist] or [location]
- Flat sequential list — no sub-headers, no act grouping header
- Chapter numbers are continuous across all acts — use the starting number given in ## Chapter Numbering above
- Start directly with ### Chapter {N} using the starting number from context — no preamble, no commentary""",

    """Write the scene list for the current chapter only (see ## Current Chapter above).

List every scene in this chapter. For each scene:

### Scene N — [Title]
**Chapter:** {chapter} | **Setting:** [specific named location] | **POV:** [character name]
**Entry:** [exact world state — named characters, place, situation]
**Exit:** [exact world state — what has changed; this is the QA contract]

[1-2 sentence summary using specific character names and events]

Critical rules:
- This chapter only — typically 3-6 scenes per chapter
- Entry and Exit are QA contracts — concrete, verifiable facts about the story world at that moment
- Entry and Exit must be meaningfully different — Exit is not a restatement of Entry
- Setting must be a specific named location from the entity ledger, not a vague description
- POV must be a named character from the entity ledger
- Scene numbers are continuous across the whole novel — the starting number for this chapter is given in ## Scene Numbering above; use it for the first scene
- No preamble, no commentary — start directly with ### Scene {N} using the starting number from context""",
]


def _draft_path(book_id: str, tier: int) -> str:
    return os.path.join(db.data_dir(book_id), f"tier_{tier}_draft.md")


def _read_tiers(book_id: str) -> list[dict]:
    path = os.path.join(db.data_dir(book_id), "tiers.json")
    tiers = json.load(open(path)) if os.path.exists(path) else [{"content": None, "approved": False} for _ in range(4)]
    for i, tier in enumerate(tiers):
        if not tier.get("approved"):
            dp = _draft_path(book_id, i + 1)
            tier["draft"] = open(dp).read() if os.path.exists(dp) else None
    return tiers


# ── North Star ─────────────────────────────────────────────────────────────────

@router.get("/books/{book_id}/phase1/north-star")
def get_north_star(book_id: str):
    book_dir = db.data_dir(book_id)
    ns_path = os.path.join(book_dir, "north_star.md")
    wp_path = os.path.join(book_dir, "writing_prefs.md")
    chat_path = os.path.join(book_dir, "north_star_chat.json")
    messages = json.load(open(chat_path)) if os.path.exists(chat_path) else None
    if not os.path.exists(ns_path):
        return {"locked": False, "document": None, "writing_prefs": None, "messages": messages}
    writing_prefs = open(wp_path).read() if os.path.exists(wp_path) else None
    with open(ns_path) as f:
        return {"locked": True, "document": f.read(), "writing_prefs": writing_prefs, "messages": messages}


class SaveMessagesBody(BaseModel):
    messages: list[dict]


@router.patch("/books/{book_id}/phase1/north-star/messages")
def save_north_star_messages(book_id: str, body: SaveMessagesBody):
    path = os.path.join(db.ensure_data_dir(book_id), "north_star_chat.json")
    with open(path, "w") as f:
        json.dump(body.messages, f)
    return {"ok": True}


class ReplyBody(BaseModel):
    messages: list[dict]


def _series_system(book_id: str, base_system: str) -> str:
    from routes.series import read_series_text
    book = db.get_book(book_id)
    series_id = book and book.get("series_id")
    if not series_id:
        return base_system
    ns = read_series_text(series_id, "north_star.md")
    if not ns:
        return base_system
    return f"## Series North Star (fixed constraints for all books in this series)\n\n{ns}\n\n---\n\n{base_system}"


@router.post("/books/{book_id}/phase1/north-star/reply")
async def north_star_reply(book_id: str, body: ReplyBody, user: str = Depends(current_user)):
    from fastapi import HTTPException
    provider = db.get_setting("agent_story_architect_provider")
    model = db.get_setting("agent_story_architect_model")
    if not provider or not model:
        raise HTTPException(400, "Story Architect has no model assigned — go to Settings.")
    system = _series_system(book_id, prompt_store.get("story_architect", STORY_ARCHITECT_SYSTEM))
    job_id, job = job_store.create()

    async def _bg():
        full_text = ""
        try:
            async for token in llm.provider_tokens(provider, model, body.messages, system, user):
                full_text += token
                job["tokens"] += token
            job["status"] = "done"
            job["result"] = full_text
        except Exception as e:
            job["status"] = "error"
            job["error"] = str(e) or type(e).__name__

    asyncio.create_task(_bg())
    return {"job_id": job_id}


class LockBody(BaseModel):
    messages: list[dict]


@router.post("/books/{book_id}/phase1/north-star/lock")
async def north_star_lock(book_id: str, body: LockBody, user: str = Depends(current_user)):
    import asyncio
    from routes.series import read_series_text
    synthesis_msgs = body.messages + [{"role": "user", "content": prompt_store.get("synthesis", SYNTHESIS_PROMPT)}]
    prefs_msgs = body.messages + [{"role": "user", "content": prompt_store.get("writing_prefs", WRITING_PREFS_PROMPT)}]

    book = db.get_book(book_id)
    series_id = book and book.get("series_id")
    if series_id:
        ss = read_series_text(series_id, "style_sheet.md")
        if ss:
            prefs_msgs = body.messages + [{"role": "user", "content": (
                f"Series style sheet (use as baseline, adapt specifics for this book):\n\n{ss}\n\n"
                + prompt_store.get("writing_prefs", WRITING_PREFS_PROMPT)
            )}]

    system = _series_system(book_id, prompt_store.get("story_architect", STORY_ARCHITECT_SYSTEM))
    document, writing_prefs = await asyncio.gather(
        llm.call_llm("story_architect", synthesis_msgs, system, user),
        llm.call_llm("story_architect", prefs_msgs, system, user),
    )

    book_dir = db.ensure_data_dir(book_id)
    with open(os.path.join(book_dir, "north_star.md"), "w") as f:
        f.write(document)
    with open(os.path.join(book_dir, "writing_prefs.md"), "w") as f:
        f.write(writing_prefs)

    repo = Repo(book_dir)
    repo.index.add(["north_star.md", "writing_prefs.md"])
    repo.index.commit("Lock North Star document and writing preferences")

    return {"ok": True, "document": document, "writing_prefs": writing_prefs}


# ── Bible Workshop ─────────────────────────────────────────────────────────────

@router.get("/books/{book_id}/phase1/bible/tiers")
def get_tiers(book_id: str):
    return _read_tiers(book_id)


class RunTierBody(BaseModel):
    tier: int


@router.post("/books/{book_id}/phase1/bible/run-tier")
async def run_tier(book_id: str, body: RunTierBody, user: str = Depends(current_user)):
    from fastapi import HTTPException
    provider = db.get_setting("agent_bible_agent_provider")
    model = db.get_setting("agent_bible_agent_model")
    if not provider or not model:
        raise HTTPException(400, "Bible Agent has no model assigned — go to Settings.")

    idx = body.tier - 1
    book_dir = db.data_dir(book_id)

    ns_path = os.path.join(book_dir, "north_star.md")
    north_star = open(ns_path).read() if os.path.exists(ns_path) else "[North Star not yet written]"

    tiers = _read_tiers(book_id)
    context = f"## North Star\n\n{north_star}"
    for i in range(idx):
        t = tiers[i]
        if t.get("approved") and t.get("content"):
            context += f"\n\n## Approved Tier {i + 1} — {TIER_LABELS[i]}\n\n{t['content']}"

    directives_path = os.path.join(book_dir, "directives.md")
    if os.path.exists(directives_path):
        context += f"\n\n## Author Directives\n\n{open(directives_path).read()}"

    tier_key = f"tier_{TIER_LABELS[idx].lower()}"
    messages = [{"role": "user", "content": f"{context}\n\n---\n\n{prompt_store.get(tier_key, TIER_INSTRUCTIONS[idx])}"}]
    system = prompt_store.get("bible_agent", BIBLE_AGENT_SYSTEM)

    job_id, job = job_store.create()

    async def _bg():
        full_text = ""
        try:
            async for token in llm.provider_tokens(provider, model, messages, system, user):
                full_text += token
                job["tokens"] += token
            with open(_draft_path(book_id, body.tier), "w") as f:
                f.write(full_text)
            job["status"] = "done"
            job["result"] = full_text
        except Exception as e:
            job["status"] = "error"
            job["error"] = str(e) or type(e).__name__

    asyncio.create_task(_bg())
    return {"job_id": job_id}


class ApproveTierBody(BaseModel):
    tier: int
    content: str


@router.post("/books/{book_id}/phase1/bible/approve-tier")
def approve_tier(book_id: str, body: ApproveTierBody):
    book_dir = db.ensure_data_dir(book_id)
    tiers = _read_tiers(book_id)
    tiers[body.tier - 1] = {"content": body.content, "approved": True}

    path = os.path.join(book_dir, "tiers.json")
    with open(path, "w") as f:
        json.dump(tiers, f, indent=2)

    dp = _draft_path(book_id, body.tier)
    if os.path.exists(dp):
        os.remove(dp)

    repo = Repo(book_dir)
    repo.index.add(["tiers.json"])
    repo.index.commit(f"Approve Bible Tier {body.tier} — {TIER_LABELS[body.tier - 1]}")

    return {"ok": True}


class EditTierBody(BaseModel):
    tier: int
    directive: str


@router.post("/books/{book_id}/phase1/bible/edit-tier")
async def edit_tier(book_id: str, body: EditTierBody, user: str = Depends(current_user)):
    from fastapi import HTTPException
    idx = body.tier - 1
    tiers = _read_tiers(book_id)
    current = tiers[idx].get("content") or tiers[idx].get("draft") or ""
    if not current:
        raise HTTPException(400, "No tier content to edit — run the agent first")

    provider = db.get_setting("agent_bible_agent_provider")
    model = db.get_setting("agent_bible_agent_model")
    if not provider or not model:
        raise HTTPException(400, "Bible Agent has no model assigned — go to Settings.")
    system = prompt_store.get("tier_editor", TIER_EDITOR_SYSTEM)
    messages = [{"role": "user", "content": (
        f"Make only this change to the document below: {body.directive}\n\n"
        f"Copy everything else verbatim.\n\n"
        f"## Document\n\n{current}"
    )}]

    job_id, job = job_store.create()

    async def _bg():
        full_text = ""
        try:
            async for token in llm.provider_tokens(provider, model, messages, system, user):
                full_text += token
                job["tokens"] += token
            with open(_draft_path(book_id, body.tier), "w") as f:
                f.write(full_text)
            job["status"] = "done"
            job["result"] = full_text
        except Exception as e:
            job["status"] = "error"
            job["error"] = str(e) or type(e).__name__

    asyncio.create_task(_bg())
    return {"job_id": job_id}


class DirectiveBody(BaseModel):
    directive: str


@router.post("/books/{book_id}/phase1/bible/directive")
def add_directive(book_id: str, body: DirectiveBody):
    path = os.path.join(db.ensure_data_dir(book_id), "directives.md")
    ts = datetime.now(timezone.utc).isoformat()
    with open(path, "a") as f:
        f.write(f"\n- [{ts}] {body.directive}")
    return {"ok": True}


# ── Bible Skeleton (mini-consolidation) ───────────────────────────────────────

def _skeleton_path(book_id: str) -> str:
    return os.path.join(db.data_dir(book_id), "bible_skeleton.json")


def _read_skeleton(book_id: str) -> dict:
    p = _skeleton_path(book_id)
    return json.load(open(p)) if os.path.exists(p) else {"acts": [], "entities": []}


def _extract_json_skeleton(text: str) -> dict:
    text = text.strip()
    if "```json" in text:
        text = text[text.index("```json") + 7:]
        text = text[:text.index("```")]
    elif "```" in text:
        text = text[text.index("```") + 3:]
        text = text[:text.rindex("```")]
    start = text.find("{")
    end = text.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError(f"No JSON object found in response (got {len(text)} chars)")
    return json.loads(text[start:end])


@router.get("/books/{book_id}/phase1/bible-skeleton")
def get_bible_skeleton(book_id: str):
    p = _skeleton_path(book_id)
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)


@router.post("/books/{book_id}/phase1/mini-consolidate")
async def mini_consolidate(book_id: str, user: str = Depends(current_user)):
    from fastapi import HTTPException
    import logging as _logging
    book_dir = db.data_dir(book_id)

    ns_path = os.path.join(book_dir, "north_star.md")
    north_star = open(ns_path).read() if os.path.exists(ns_path) else "[North Star not yet written]"

    tiers = _read_tiers(book_id)
    tier2 = tiers[1].get("content") or ""
    if not tier2:
        raise HTTPException(400, "Tier 2 (Acts) must be approved before mini-consolidation")

    provider = db.get_setting("agent_bible_agent_provider")
    model = db.get_setting("agent_bible_agent_model")
    if not provider or not model:
        raise HTTPException(400, "Bible Agent has no model assigned — go to Settings.")

    messages = [
        {"role": "user", "content": (
            "Fill in the JSON template below using ONLY the source material. "
            "Output the completed JSON and nothing else — no preamble, no explanation.\n\n"
            f"## North Star\n\n{north_star}\n\n"
            f"## Act Breakdown (Tier 2)\n\n{tier2}\n\n"
            "Fill in this template:\n"
            '{\n'
            '  "acts": [{"number": 1, "title": "act title from text"}, ...],\n'
            '  "entities": [\n'
            '    {"id": "CHAR_001", "name": "full name", "type": "character", "aliases": [], "coreFacts": {}, "appearsInActs": [1]},\n'
            '    {"id": "LOC_001", "name": "place name", "type": "location", "aliases": [], "coreFacts": {}, "appearsInActs": [1]}\n'
            '  ]\n'
            '}'
        )},
    ]
    system = prompt_store.get("mini_consolidator", MINI_CONSOLIDATOR_SYSTEM)

    job_id, job = job_store.create()

    async def _bg():
        full_text = ""
        try:
            async for token in llm.provider_tokens(provider, model, messages, system, user):
                full_text += token
                job["tokens"] += token
            skeleton = _extract_json_skeleton(full_text)
            with open(_skeleton_path(book_id), "w") as f:
                json.dump(skeleton, f, indent=2)
            job["status"] = "done"
            job["result"] = full_text
            job["meta"] = {
                "entity_count": len(skeleton.get("entities", [])),
                "act_count": len(skeleton.get("acts", [])),
            }
        except ValueError as e:
            _logging.getLogger(__name__).error("mini-consolidate parse fail:\n%s", full_text[:500])
            job["status"] = "error"
            job["error"] = f"JSON parse error: {e}"
        except Exception as e:
            job["status"] = "error"
            job["error"] = str(e) or type(e).__name__

    asyncio.create_task(_bg())
    return {"job_id": job_id}


class SkeletonEntityBody(BaseModel):
    name: str
    type: str
    purpose: str = ""
    aliases: list[str] = []
    coreFacts: dict = {}
    appearsInActs: list[int] = []


@router.post("/books/{book_id}/phase1/skeleton/entity", status_code=201)
def add_skeleton_entity(book_id: str, body: SkeletonEntityBody):
    skeleton = _read_skeleton(book_id)
    type_prefix = {"character": "CHAR", "location": "LOC", "faction": "FRAC", "object": "OBJ"}.get(body.type, "ENT")
    existing_of_type = [e for e in skeleton["entities"] if e.get("id", "").startswith(type_prefix)]
    new_id = f"{type_prefix}_{len(existing_of_type) + 1:03d}"
    entity = {
        "id": new_id,
        "name": body.name,
        "type": body.type,
        "aliases": body.aliases,
        "coreFacts": {**body.coreFacts, **({"purpose": body.purpose} if body.purpose else {})},
        "appearsInActs": body.appearsInActs,
    }
    skeleton["entities"].append(entity)
    with open(_skeleton_path(book_id), "w") as f:
        json.dump(skeleton, f, indent=2)
    return entity


class PatchEntityBody(BaseModel):
    name: str | None = None
    type: str | None = None
    aliases: list[str] | None = None
    coreFacts: dict | None = None
    appearsInActs: list[int] | None = None


@router.patch("/books/{book_id}/phase1/skeleton/entity/{entity_id}")
def patch_skeleton_entity(book_id: str, entity_id: str, body: PatchEntityBody):
    from fastapi import HTTPException
    skeleton = _read_skeleton(book_id)
    entity = next((e for e in skeleton["entities"] if e["id"] == entity_id), None)
    if not entity:
        raise HTTPException(404, "Entity not found")
    if body.name is not None:
        entity["name"] = body.name
    if body.type is not None:
        entity["type"] = body.type
    if body.aliases is not None:
        entity["aliases"] = body.aliases
    if body.coreFacts is not None:
        entity["coreFacts"] = {**entity.get("coreFacts", {}), **body.coreFacts}
    if body.appearsInActs is not None:
        entity["appearsInActs"] = body.appearsInActs
    with open(_skeleton_path(book_id), "w") as f:
        json.dump(skeleton, f, indent=2)
    return entity


# ── Tier 3 — per-act chapter summaries ────────────────────────────────────────

def _tier3_dir(book_id: str) -> str:
    return os.path.join(db.data_dir(book_id), "tier3")


def _tier3_act_path(book_id: str, act: int) -> str:
    return os.path.join(_tier3_dir(book_id), f"act_{act}.md")


def _tier3_status_path(book_id: str) -> str:
    return os.path.join(_tier3_dir(book_id), "status.json")


def _read_tier3_status(book_id: str) -> dict:
    p = _tier3_status_path(book_id)
    if os.path.exists(p):
        return json.load(open(p))
    skeleton = _read_skeleton(book_id)
    acts = [
        {"act": a["number"], "title": a.get("title", f"Act {a['number']}"), "approved": False, "chapters": []}
        for a in skeleton.get("acts", [])
    ]
    return {"acts": acts}


def _save_tier3_status(book_id: str, status: dict) -> None:
    os.makedirs(_tier3_dir(book_id), exist_ok=True)
    with open(_tier3_status_path(book_id), "w") as f:
        json.dump(status, f, indent=2)


def _parse_chapters(content: str) -> list[dict]:
    pattern = re.compile(r'^### Chapter (\d+)\s*[—–-]\s*(.+)$', re.MULTILINE)
    return [{"number": int(m.group(1)), "title": m.group(2).strip()} for m in pattern.finditer(content)]


def _format_skeleton_for_context(skeleton: dict) -> str:
    entities = skeleton.get("entities", [])
    if not entities:
        return ""
    lines = []
    for e in entities:
        facts = "; ".join(f"{k}: {v}" for k, v in e.get("coreFacts", {}).items())
        aliases = f" (also: {', '.join(e['aliases'])})" if e.get("aliases") else ""
        line = f"- [{e['id']}] {e['name']}{aliases} — {e['type']}"
        if facts:
            line += f". {facts}"
        lines.append(line)
    return "\n".join(lines)


@router.get("/books/{book_id}/phase1/tier3/act/{act_num}")
def get_tier3_act(book_id: str, act_num: int):
    from fastapi import HTTPException
    p = _tier3_act_path(book_id, act_num)
    if not os.path.exists(p):
        raise HTTPException(404, "No content for this act")
    return {"content": open(p).read()}


@router.get("/books/{book_id}/phase1/tier3/status")
def get_tier3_status(book_id: str):
    status = _read_tier3_status(book_id)
    for act_info in status.get("acts", []):
        act_info["has_content"] = os.path.exists(_tier3_act_path(book_id, act_info["act"]))
    return status


class RunActBody(BaseModel):
    act: int


@router.post("/books/{book_id}/phase1/tier3/run-act")
async def run_tier3_act(book_id: str, body: RunActBody, user: str = Depends(current_user)):
    from fastapi import HTTPException
    provider = db.get_setting("agent_bible_agent_provider")
    model = db.get_setting("agent_bible_agent_model")
    if not provider or not model:
        raise HTTPException(400, "Bible Agent has no model assigned — go to Settings.")

    book_dir = db.data_dir(book_id)

    ns_path = os.path.join(book_dir, "north_star.md")
    north_star = open(ns_path).read() if os.path.exists(ns_path) else "[North Star not yet written]"

    tiers = _read_tiers(book_id)
    tier1 = tiers[0].get("content") or ""
    tier2 = tiers[1].get("content") or ""

    skeleton = _read_skeleton(book_id)
    entity_summary = _format_skeleton_for_context(skeleton)
    current_act = next((a for a in skeleton.get("acts", []) if a["number"] == body.act), None)
    act_title = current_act.get("title", f"Act {body.act}") if current_act else f"Act {body.act}"

    status = _read_tier3_status(book_id)
    prior_acts_text = ""
    for act_info in status.get("acts", []):
        if act_info["act"] < body.act and act_info.get("approved"):
            act_path = _tier3_act_path(book_id, act_info["act"])
            if os.path.exists(act_path):
                prior_acts_text += f"\n\n## Approved Act {act_info['act']} — {act_info['title']}\n\n{open(act_path).read()}"

    context = f"## North Star\n\n{north_star}"
    if tier1:
        context += f"\n\n## Book Synopsis (Tier 1)\n\n{tier1}"
    if tier2:
        context += f"\n\n## Act Breakdown (Tier 2)\n\n{tier2}"
    if entity_summary:
        context += f"\n\n## Story Bible — Entities\n\n{entity_summary}"
    if prior_acts_text:
        context += prior_acts_text
    context += f"\n\n## Current Act\n\nAct {body.act} — {act_title}"

    start_chapter = 1 + sum(
        len(a.get("chapters", []))
        for a in status.get("acts", [])
        if a["act"] < body.act
    )
    context += f"\n\n## Chapter Numbering\n\nChapters are numbered continuously across all acts. This act's first chapter is Chapter {start_chapter}."

    directives_path = os.path.join(book_dir, "directives.md")
    if os.path.exists(directives_path):
        context += f"\n\n## Author Directives\n\n{open(directives_path).read()}"

    instruction = prompt_store.get("tier_chapters", TIER_INSTRUCTIONS[2])
    messages = [{"role": "user", "content": f"{context}\n\n---\n\n{instruction}"}]
    system = prompt_store.get("bible_agent", BIBLE_AGENT_SYSTEM)

    job_id, job = job_store.create()

    async def _bg():
        full_text = ""
        try:
            async for token in llm.provider_tokens(provider, model, messages, system, user):
                full_text += token
                job["tokens"] += token
            os.makedirs(_tier3_dir(book_id), exist_ok=True)
            with open(_tier3_act_path(book_id, body.act), "w") as f:
                f.write(full_text)
            job["status"] = "done"
            job["result"] = full_text
        except Exception as e:
            job["status"] = "error"
            job["error"] = str(e) or type(e).__name__

    asyncio.create_task(_bg())
    return {"job_id": job_id}


class ApproveActBody(BaseModel):
    act: int
    content: str


@router.post("/books/{book_id}/phase1/tier3/approve-act")
def approve_tier3_act(book_id: str, body: ApproveActBody):
    os.makedirs(_tier3_dir(book_id), exist_ok=True)
    with open(_tier3_act_path(book_id, body.act), "w") as f:
        f.write(body.content)

    chapters = _parse_chapters(body.content)

    status = _read_tier3_status(book_id)
    for act_info in status.get("acts", []):
        if act_info["act"] == body.act:
            act_info["approved"] = True
            act_info["chapters"] = chapters
            break

    _save_tier3_status(book_id, status)

    book_dir = db.data_dir(book_id)
    repo = Repo(book_dir)
    rel_act = os.path.relpath(_tier3_act_path(book_id, body.act), book_dir)
    rel_status = os.path.relpath(_tier3_status_path(book_id), book_dir)
    repo.index.add([rel_act, rel_status])
    repo.index.commit(f"Approve Tier 3 Act {body.act} — {len(chapters)} chapters parsed")

    return {"ok": True, "chapters": chapters}


class EditActBody(BaseModel):
    act: int
    directive: str


@router.post("/books/{book_id}/phase1/tier3/edit-act")
async def edit_tier3_act(book_id: str, body: EditActBody, user: str = Depends(current_user)):
    from fastapi import HTTPException
    act_path = _tier3_act_path(book_id, body.act)
    if not os.path.exists(act_path):
        raise HTTPException(400, "No content for this act — run the agent first")

    current = open(act_path).read()
    provider = db.get_setting("agent_bible_agent_provider")
    model = db.get_setting("agent_bible_agent_model")
    if not provider or not model:
        raise HTTPException(400, "Bible Agent has no model assigned — go to Settings.")
    system = prompt_store.get("tier_editor", TIER_EDITOR_SYSTEM)
    messages = [{"role": "user", "content": (
        f"Make only this change to the document below: {body.directive}\n\n"
        f"Copy everything else verbatim.\n\n"
        f"## Document\n\n{current}"
    )}]

    job_id, job = job_store.create()

    async def _bg():
        full_text = ""
        try:
            async for token in llm.provider_tokens(provider, model, messages, system, user):
                full_text += token
                job["tokens"] += token
            with open(act_path, "w") as f:
                f.write(full_text)
            job["status"] = "done"
            job["result"] = full_text
        except Exception as e:
            job["status"] = "error"
            job["error"] = str(e) or type(e).__name__

    asyncio.create_task(_bg())
    return {"job_id": job_id}


# ── Tier 4 — per-chapter scene lists ──────────────────────────────────────────


def _tier4_dir(book_id: str) -> str:
    return os.path.join(db.data_dir(book_id), "tier4")


def _tier4_chapter_path(book_id: str, chapter: int) -> str:
    return os.path.join(_tier4_dir(book_id), f"chapter_{chapter:02d}.md")


def _tier4_scene_path(book_id: str, chapter: int, scene: int) -> str:
    return os.path.join(_tier4_dir(book_id), f"chapter_{chapter:02d}_scene_{scene:02d}.md")


def _tier4_status_path(book_id: str) -> str:
    return os.path.join(_tier4_dir(book_id), "status.json")


def _read_tier4_status(book_id: str) -> dict:
    p = _tier4_status_path(book_id)
    if os.path.exists(p):
        return json.load(open(p))
    # Build from tier3 chapter index (flatten all approved acts)
    tier3_status = _read_tier3_status(book_id)
    chapters = []
    for act_info in tier3_status.get("acts", []):
        for ch in act_info.get("chapters", []):
            chapters.append({"number": ch["number"], "title": ch.get("title", f"Chapter {ch['number']}"), "approved": False})
    chapters.sort(key=lambda c: c["number"])
    return {"chapters": chapters}


def _save_tier4_status(book_id: str, status: dict) -> None:
    os.makedirs(_tier4_dir(book_id), exist_ok=True)
    with open(_tier4_status_path(book_id), "w") as f:
        json.dump(status, f, indent=2)


def _extract_chapter_section(content: str, chapter_number: int) -> str:
    """Extract the markdown block for one chapter from a tier3 act file."""
    pattern = re.compile(r'^(### Chapter \d+.*?)(?=^### Chapter \d+|\Z)', re.MULTILINE | re.DOTALL)
    for match in pattern.finditer(content):
        header = re.match(r'^### Chapter (\d+)', match.group(1))
        if header and int(header.group(1)) == chapter_number:
            return match.group(1).strip()
    return ""


def _get_chapter_summary(book_id: str, chapter_number: int) -> str:
    """Read a chapter's tier3 summary from whichever act file contains it."""
    tier3_status = _read_tier3_status(book_id)
    for act_info in tier3_status.get("acts", []):
        for ch in act_info.get("chapters", []):
            if ch["number"] == chapter_number:
                act_path = _tier3_act_path(book_id, act_info["act"])
                if os.path.exists(act_path):
                    return _extract_chapter_section(open(act_path).read(), chapter_number)
    return ""


@router.get("/books/{book_id}/phase1/tier4/status")
def get_tier4_status(book_id: str):
    status = _read_tier4_status(book_id)
    for ch in status.get("chapters", []):
        ch["has_content"] = os.path.exists(_tier4_chapter_path(book_id, ch["number"]))
        for s in ch.get("scenes", []):
            s["has_content"] = os.path.exists(_tier4_scene_path(book_id, ch["number"], s["number"]))
    return status


class RunChapterBody(BaseModel):
    chapter: int


@router.post("/books/{book_id}/phase1/tier4/run-chapter")
async def run_tier4_chapter(book_id: str, body: RunChapterBody, user: str = Depends(current_user)):
    from fastapi import HTTPException

    provider = db.get_setting("agent_bible_agent_provider")
    model = db.get_setting("agent_bible_agent_model")
    if not provider or not model:
        raise HTTPException(400, "Bible Agent has no model assigned — go to Settings.")

    book_dir = db.data_dir(book_id)
    ns_path = os.path.join(book_dir, "north_star.md")
    north_star = open(ns_path).read() if os.path.exists(ns_path) else "[North Star not yet written]"

    skeleton = _read_skeleton(book_id)
    entity_summary = _format_skeleton_for_context(skeleton)

    chapter_summary = _get_chapter_summary(book_id, body.chapter)
    prev_summary = _get_chapter_summary(book_id, body.chapter - 1) if body.chapter > 1 else ""
    next_summary = _get_chapter_summary(book_id, body.chapter + 1)

    tier4_status = _read_tier4_status(book_id)
    chapter_info = next((c for c in tier4_status.get("chapters", []) if c["number"] == body.chapter), None)
    chapter_title = chapter_info.get("title", f"Chapter {body.chapter}") if chapter_info else f"Chapter {body.chapter}"

    context = f"## North Star\n\n{north_star}"
    if entity_summary:
        context += f"\n\n## Story Bible — Entities\n\n{entity_summary}"
    if prev_summary:
        context += f"\n\n## Previous Chapter (Chapter {body.chapter - 1}) — for continuity\n\n{prev_summary}"
    if chapter_summary:
        context += f"\n\n## Current Chapter\n\n{chapter_summary}"
    else:
        context += f"\n\n## Current Chapter\n\nChapter {body.chapter} — {chapter_title}"
    if next_summary:
        context += f"\n\n## Next Chapter (Chapter {body.chapter + 1}) — forward context\n\n{next_summary}"

    start_scene = 1 + sum(
        len(ch.get("scenes", []))
        for ch in tier4_status.get("chapters", [])
        if ch["number"] < body.chapter
    )
    context += f"\n\n## Scene Numbering\n\nScenes are numbered continuously across the whole novel. This chapter's first scene is Scene {start_scene}."

    instruction = prompt_store.get("tier_scenes", TIER_INSTRUCTIONS[3])
    messages = [{"role": "user", "content": f"{context}\n\n---\n\n{instruction}"}]
    system = prompt_store.get("bible_agent", BIBLE_AGENT_SYSTEM)

    job_id, job = job_store.create()

    async def _bg() -> None:
        full_text = ""
        try:
            async for token in llm.provider_tokens(provider, model, messages, system, user):
                full_text += token
                job["tokens"] += token
            os.makedirs(_tier4_dir(book_id), exist_ok=True)
            with open(_tier4_chapter_path(book_id, body.chapter), "w") as f:
                f.write(full_text)
            job["status"] = "done"
            job["result"] = full_text
        except Exception as e:
            job["status"] = "error"
            job["error"] = str(e) or type(e).__name__

    asyncio.create_task(_bg())
    return {"job_id": job_id}



@router.get("/books/{book_id}/phase1/tier4/chapter/{chapter_num}/scene/{scene_num}")
def get_tier4_scene(book_id: str, chapter_num: int, scene_num: int):
    path = _tier4_scene_path(book_id, chapter_num, scene_num)
    if not os.path.exists(path):
        from fastapi import HTTPException
        raise HTTPException(404, "No scene content on disk")
    with open(path) as f:
        return {"content": f.read()}


@router.get("/books/{book_id}/phase1/tier4/chapter/{chapter_num}/plan")
def get_tier4_chapter_plan(book_id: str, chapter_num: int):
    path = _tier4_chapter_path(book_id, chapter_num)
    if not os.path.exists(path):
        from fastapi import HTTPException
        raise HTTPException(404, "No plan on disk for this chapter")
    with open(path) as f:
        return {"content": f.read()}


class ApproveChapterBody(BaseModel):
    chapter: int
    content: str


@router.post("/books/{book_id}/phase1/tier4/approve-chapter")
def approve_tier4_chapter(book_id: str, body: ApproveChapterBody):
    os.makedirs(_tier4_dir(book_id), exist_ok=True)
    with open(_tier4_chapter_path(book_id, body.chapter), "w") as f:
        f.write(body.content)

    # Parse scene headings from the plan to create scene entries
    scene_pattern = re.compile(r'^### Scene (\d+)\s*[—–:\-]+\s*(.+)', re.MULTILINE)
    scenes = [
        {"number": int(m.group(1)), "title": m.group(2).strip(), "approved": False}
        for m in scene_pattern.finditer(body.content)
    ]
    if not scenes:
        from fastapi import HTTPException
        raise HTTPException(422, "No scene headers found in plan — ensure the agent output uses '### Scene N — Title' format")

    status = _read_tier4_status(book_id)
    for ch in status.get("chapters", []):
        if ch["number"] == body.chapter:
            ch["scenes"] = scenes
            # ch["approved"] stays False — set True when all scenes approved
            break

    _save_tier4_status(book_id, status)

    book_dir = db.data_dir(book_id)
    repo = Repo(book_dir)
    rel_chapter = os.path.relpath(_tier4_chapter_path(book_id, body.chapter), book_dir)
    rel_status = os.path.relpath(_tier4_status_path(book_id), book_dir)
    repo.index.add([rel_chapter, rel_status])
    repo.index.commit(f"Lock scene plan — Chapter {body.chapter} ({len(scenes)} scenes)")

    return {"ok": True, "scenes": len(scenes)}


class EditChapterBody(BaseModel):
    chapter: int
    directive: str


@router.post("/books/{book_id}/phase1/tier4/edit-chapter")
async def edit_tier4_chapter(book_id: str, body: EditChapterBody, user: str = Depends(current_user)):
    from fastapi import HTTPException
    chapter_path = _tier4_chapter_path(book_id, body.chapter)
    if not os.path.exists(chapter_path):
        raise HTTPException(400, "No content for this chapter — run the agent first")

    current = open(chapter_path).read()
    provider = db.get_setting("agent_bible_agent_provider")
    model = db.get_setting("agent_bible_agent_model")
    if not provider or not model:
        raise HTTPException(400, "Bible Agent has no model assigned — go to Settings.")
    system = prompt_store.get("tier_editor", TIER_EDITOR_SYSTEM)
    messages = [{"role": "user", "content": (
        f"Make only this change to the document below: {body.directive}\n\n"
        f"Copy everything else verbatim.\n\n"
        f"## Document\n\n{current}"
    )}]

    job_id, job = job_store.create()

    async def _bg():
        full_text = ""
        try:
            async for token in llm.provider_tokens(provider, model, messages, system, user):
                full_text += token
                job["tokens"] += token
            with open(chapter_path, "w") as f:
                f.write(full_text)
            job["status"] = "done"
            job["result"] = full_text
        except Exception as e:
            job["status"] = "error"
            job["error"] = str(e) or type(e).__name__

    asyncio.create_task(_bg())
    return {"job_id": job_id}


# ── Individual scene endpoints ─────────────────────────────────────────────────

class RunSceneBody(BaseModel):
    scene: int
    directive: str = ""


@router.post("/books/{book_id}/phase1/tier4/chapter/{chapter_num}/run-scene")
async def run_scene(book_id: str, chapter_num: int, body: RunSceneBody, user: str = Depends(current_user)):
    from fastapi import HTTPException
    provider = db.get_setting("agent_bible_agent_provider")
    model = db.get_setting("agent_bible_agent_model")
    if not provider or not model:
        raise HTTPException(400, "Bible Agent has no model assigned — go to Settings.")

    book_dir = db.data_dir(book_id)
    ns_path = os.path.join(book_dir, "north_star.md")
    north_star = open(ns_path).read() if os.path.exists(ns_path) else ""
    skeleton = _read_skeleton(book_id)
    entity_summary = _format_skeleton_for_context(skeleton)
    chapter_summary = _get_chapter_summary(book_id, chapter_num)

    plan_path = _tier4_chapter_path(book_id, chapter_num)
    scene_plan_section = ""
    if os.path.exists(plan_path):
        plan = open(plan_path).read()
        m = re.search(
            r'^(### Scene ' + str(body.scene) + r'\s*[—–:\-].*?)(?=^### Scene \d+|\Z)',
            plan, re.MULTILINE | re.DOTALL
        )
        if m:
            scene_plan_section = m.group(1).strip()

    prev_scene_tail = ""
    if body.scene > 1:
        prev_path = _tier4_scene_path(book_id, chapter_num, body.scene - 1)
        if os.path.exists(prev_path):
            text = open(prev_path).read()
            prev_scene_tail = text[-600:] if len(text) > 600 else text

    context = f"## North Star\n\n{north_star}"
    if entity_summary:
        context += f"\n\n## Story Bible — Entities\n\n{entity_summary}"
    if chapter_summary:
        context += f"\n\n## Chapter Summary\n\n{chapter_summary}"
    if prev_scene_tail:
        context += f"\n\n## Previous Scene (ending)\n\n…{prev_scene_tail}"
    context += f"\n\n## Scene to Write\n\n{scene_plan_section or f'Scene {body.scene} of Chapter {chapter_num}'}"
    if body.directive.strip():
        context += f"\n\n## Author directive\n\n{body.directive}"

    messages = [{"role": "user", "content": context + "\n\nWrite the scene brief now. Use ONLY the 7 section headers from the instructions. Do NOT write prose sentences or paragraphs. Bullets and short phrases only."}]

    job_id, job = job_store.create()

    async def _bg():
        full_text = ""
        try:
            async for token in llm.provider_tokens(provider, model, messages, SCENE_WRITER_SYSTEM, user):
                full_text += token
                job["tokens"] += token
            os.makedirs(_tier4_dir(book_id), exist_ok=True)
            with open(_tier4_scene_path(book_id, chapter_num, body.scene), "w") as f:
                f.write(full_text)
            job["status"] = "done"
            job["result"] = full_text
        except Exception as e:
            job["status"] = "error"
            job["error"] = str(e) or type(e).__name__

    asyncio.create_task(_bg())
    return {"job_id": job_id}


class ApproveSceneBody(BaseModel):
    content: str


@router.post("/books/{book_id}/phase1/tier4/chapter/{chapter_num}/scene/{scene_num}/approve")
async def approve_scene(book_id: str, chapter_num: int, scene_num: int, body: ApproveSceneBody, user: str = Depends(current_user)):
    job_id, job = job_store.create()

    async def _bg():
        try:
            os.makedirs(_tier4_dir(book_id), exist_ok=True)
            with open(_tier4_scene_path(book_id, chapter_num, scene_num), "w") as f:
                f.write(body.content)

            status = _read_tier4_status(book_id)
            chapter_complete = False
            for ch in status.get("chapters", []):
                if ch["number"] == chapter_num:
                    for s in ch.get("scenes", []):
                        if s["number"] == scene_num:
                            s["approved"] = True
                            break
                    if all(s.get("approved") for s in ch.get("scenes", [])):
                        ch["approved"] = True
                        chapter_complete = True
                    break
            _save_tier4_status(book_id, status)

            book_dir = db.data_dir(book_id)
            repo = Repo(book_dir)
            rel_scene = os.path.relpath(_tier4_scene_path(book_id, chapter_num, scene_num), book_dir)
            rel_status = os.path.relpath(_tier4_status_path(book_id), book_dir)
            repo.index.add([rel_scene, rel_status])
            repo.index.commit(f"Approve Chapter {chapter_num} Scene {scene_num}")

            job["meta"]["chapter_complete"] = chapter_complete

            # Bible sync
            provider = db.get_setting("agent_bible_agent_provider")
            model = db.get_setting("agent_bible_agent_model")
            if not provider or not model:
                job["meta"]["new_entities"] = 0
                job["status"] = "done"
                job["result"] = "saved"
                return

            skeleton = _read_skeleton(book_id)
            tier3_status = _read_tier3_status(book_id)
            act_num = next(
                (a["act"] for a in tier3_status.get("acts", [])
                 for ch in a.get("chapters", []) if ch["number"] == chapter_num),
                None
            )

            sync_messages = [{"role": "user", "content": (
                f"## Current Entity Skeleton\n\n{json.dumps(skeleton.get('entities', []), indent=2)}\n\n"
                f"## Approved Scene (Chapter {chapter_num}, Scene {scene_num})\n\n{body.content}\n\n"
                "List any new entities in this scene not already in the skeleton."
            )}]

            last_error = None
            result = None
            for _attempt in range(2):
                full_sync = ""
                try:
                    async for token in llm.provider_tokens(provider, model, sync_messages, SCENE_BIBLE_SYNC_SYSTEM, user):
                        full_sync += token
                except Exception as e:
                    job["status"] = "error"
                    job["error"] = str(e) or type(e).__name__
                    return
                try:
                    result = _extract_json_skeleton(full_sync)
                    last_error = None
                    break
                except Exception as e:
                    last_error = e

            if last_error is not None:
                job["status"] = "error"
                job["error"] = str(last_error)
                return

            new_entities = result.get("new_entities", [])
            if new_entities:
                if act_num is not None:
                    for e in new_entities:
                        if act_num not in e.get("appearsInActs", []):
                            e.setdefault("appearsInActs", []).append(act_num)
                skeleton.setdefault("entities", []).extend(new_entities)
                with open(_skeleton_path(book_id), "w") as f:
                    json.dump(skeleton, f, indent=2)
                rel_skel = os.path.relpath(_skeleton_path(book_id), book_dir)
                repo.index.add([rel_skel])
                repo.index.commit(f"Bible sync — Ch{chapter_num} Sc{scene_num} (+{len(new_entities)} entities)")

            job["meta"]["new_entities"] = len(new_entities)
            job["status"] = "done"
            job["result"] = "saved"
        except Exception as e:
            job["status"] = "error"
            job["error"] = str(e) or type(e).__name__

    asyncio.create_task(_bg())
    return {"job_id": job_id}


class EditSceneBody(BaseModel):
    directive: str


@router.post("/books/{book_id}/phase1/tier4/chapter/{chapter_num}/scene/{scene_num}/edit")
async def edit_scene(book_id: str, chapter_num: int, scene_num: int, body: EditSceneBody, user: str = Depends(current_user)):
    from fastapi import HTTPException
    scene_path = _tier4_scene_path(book_id, chapter_num, scene_num)
    if not os.path.exists(scene_path):
        raise HTTPException(400, "No scene content yet — run the agent first")
    provider = db.get_setting("agent_bible_agent_provider")
    model = db.get_setting("agent_bible_agent_model")
    if not provider or not model:
        raise HTTPException(400, "Bible Agent has no model assigned — go to Settings.")
    current = open(scene_path).read()
    messages = [{"role": "user", "content": (
        f"Make only this change to the scene below: {body.directive}\n\n"
        f"Copy everything else verbatim.\n\n## Scene\n\n{current}"
    )}]

    job_id, job = job_store.create()

    async def _bg():
        full_text = ""
        try:
            async for token in llm.provider_tokens(provider, model, messages, TIER_EDITOR_SYSTEM, user):
                full_text += token
                job["tokens"] += token
            with open(scene_path, "w") as f:
                f.write(full_text)
            job["status"] = "done"
            job["result"] = full_text
        except Exception as e:
            job["status"] = "error"
            job["error"] = str(e) or type(e).__name__

    asyncio.create_task(_bg())
    return {"job_id": job_id}


# ── Auto-Bible background implementation ──────────────────────────────────────

async def _bg_call(provider: str, model: str, messages: list, system: str, user: str, json_mode: bool = False) -> str:
    result = ""
    async for token in llm.provider_tokens(provider, model, messages, system, user, json_mode=json_mode):
        result += token
    return result


async def _bg_run_tier12(book_id: str, tier: int, user: str, log_cb) -> str:
    """Run Tier 1 or Tier 2 using the same context as the SSE endpoint."""
    provider = db.get_setting("agent_bible_agent_provider")
    model = db.get_setting("agent_bible_agent_model")

    book_dir = db.data_dir(book_id)
    ns_path = os.path.join(book_dir, "north_star.md")
    north_star = open(ns_path).read() if os.path.exists(ns_path) else "[North Star not yet written]"

    idx = tier - 1
    tiers = _read_tiers(book_id)
    context = f"## North Star\n\n{north_star}"
    for i in range(idx):
        t = tiers[i]
        if t.get("approved") and t.get("content"):
            context += f"\n\n## Approved Tier {i + 1} — {TIER_LABELS[i]}\n\n{t['content']}"

    tier_key = f"tier_{TIER_LABELS[idx].lower()}"
    messages = [{"role": "user", "content": f"{context}\n\n---\n\n{prompt_store.get(tier_key, TIER_INSTRUCTIONS[idx])}"}]
    system = prompt_store.get("bible_agent", BIBLE_AGENT_SYSTEM)

    log_cb(f"Running Tier {tier} ({TIER_LABELS[idx]})...")
    return await _bg_call(provider, model, messages, system, user)


def _bg_approve_tier12(book_id: str, tier: int, content: str) -> None:
    book_dir = db.ensure_data_dir(book_id)
    tiers = _read_tiers(book_id)
    tiers[tier - 1] = {"content": content, "approved": True}
    dp = _draft_path(book_id, tier)
    if os.path.exists(dp):
        os.remove(dp)
    path = os.path.join(book_dir, "tiers.json")
    with open(path, "w") as f:
        json.dump(tiers, f, indent=2)
    try:
        repo = Repo(book_dir)
        repo.index.add(["tiers.json"])
        repo.index.commit(f"Auto-approve Bible Tier {tier} — {TIER_LABELS[tier - 1]}")
    except Exception:
        pass


async def _bg_mini_consolidate(book_id: str, user: str, log_cb) -> None:
    """Extract entity skeleton from North Star + Tier 2 (same context as SSE endpoint)."""
    provider = db.get_setting("agent_bible_agent_provider")
    model = db.get_setting("agent_bible_agent_model")

    book_dir = db.data_dir(book_id)
    ns_path = os.path.join(book_dir, "north_star.md")
    north_star = open(ns_path).read() if os.path.exists(ns_path) else "[North Star not yet written]"

    tiers = _read_tiers(book_id)
    tier2 = tiers[1].get("content") or ""

    messages = [{"role": "user", "content": (
        "Fill in the JSON template below using ONLY the source material. "
        "Output the completed JSON and nothing else — no preamble, no explanation.\n\n"
        f"## North Star\n\n{north_star}\n\n"
        f"## Act Breakdown (Tier 2)\n\n{tier2}\n\n"
        "Fill in this template:\n"
        '{\n'
        '  "acts": [{"number": 1, "title": "act title from text"}, ...],\n'
        '  "entities": [\n'
        '    {"id": "CHAR_001", "name": "full name", "type": "character", "aliases": [], "coreFacts": {}, "appearsInActs": [1]},\n'
        '    {"id": "LOC_001", "name": "place name", "type": "location", "aliases": [], "coreFacts": {}, "appearsInActs": [1]}\n'
        '  ]\n'
        '}'
    )}]
    system = prompt_store.get("mini_consolidator", MINI_CONSOLIDATOR_SYSTEM)

    log_cb("Running mini-consolidate (entity skeleton)...")
    full_text = await _bg_call(provider, model, messages, system, user)

    try:
        skeleton = _extract_json_skeleton(full_text)
    except Exception as e:
        raise RuntimeError(f"Mini-consolidate JSON parse error: {e}")

    with open(_skeleton_path(book_id), "w") as f:
        json.dump(skeleton, f, indent=2)
    log_cb(f"Mini-consolidate done — {len(skeleton.get('entities', []))} entities, {len(skeleton.get('acts', []))} acts.")


async def _bg_run_tier3_act(book_id: str, act: int, user: str, log_cb) -> str:
    """Run Tier 3 for one act using the same context as the SSE endpoint."""
    provider = db.get_setting("agent_bible_agent_provider")
    model = db.get_setting("agent_bible_agent_model")

    book_dir = db.data_dir(book_id)
    ns_path = os.path.join(book_dir, "north_star.md")
    north_star = open(ns_path).read() if os.path.exists(ns_path) else "[North Star not yet written]"

    tiers = _read_tiers(book_id)
    tier1 = tiers[0].get("content") or ""
    tier2 = tiers[1].get("content") or ""

    skeleton = _read_skeleton(book_id)
    entity_summary = _format_skeleton_for_context(skeleton)
    current_act = next((a for a in skeleton.get("acts", []) if a["number"] == act), None)
    act_title = current_act.get("title", f"Act {act}") if current_act else f"Act {act}"

    status = _read_tier3_status(book_id)
    prior_acts_text = ""
    for act_info in status.get("acts", []):
        if act_info["act"] < act and act_info.get("approved"):
            act_path = _tier3_act_path(book_id, act_info["act"])
            if os.path.exists(act_path):
                prior_acts_text += f"\n\n## Approved Act {act_info['act']} — {act_info['title']}\n\n{open(act_path).read()}"

    context = f"## North Star\n\n{north_star}"
    if tier1:
        context += f"\n\n## Book Synopsis (Tier 1)\n\n{tier1}"
    if tier2:
        context += f"\n\n## Act Breakdown (Tier 2)\n\n{tier2}"
    if entity_summary:
        context += f"\n\n## Story Bible — Entities\n\n{entity_summary}"
    if prior_acts_text:
        context += prior_acts_text
    context += f"\n\n## Current Act\n\nAct {act} — {act_title}"

    start_chapter = 1 + sum(
        len(a.get("chapters", []))
        for a in status.get("acts", [])
        if a["act"] < act
    )
    context += f"\n\n## Chapter Numbering\n\nChapters are numbered continuously across all acts. This act's first chapter is Chapter {start_chapter}."

    instruction = prompt_store.get("tier_chapters", TIER_INSTRUCTIONS[2])
    messages = [{"role": "user", "content": f"{context}\n\n---\n\n{instruction}"}]
    system = prompt_store.get("bible_agent", BIBLE_AGENT_SYSTEM)

    log_cb(f"Running Tier 3 Act {act} (chapter summaries)...")
    return await _bg_call(provider, model, messages, system, user)


def _bg_approve_tier3_act(book_id: str, act: int, content: str) -> list:
    """Save, update status, commit. Returns parsed chapters list."""
    os.makedirs(_tier3_dir(book_id), exist_ok=True)
    with open(_tier3_act_path(book_id, act), "w") as f:
        f.write(content)

    chapters = _parse_chapters(content)
    status = _read_tier3_status(book_id)
    for act_info in status.get("acts", []):
        if act_info["act"] == act:
            act_info["approved"] = True
            act_info["chapters"] = chapters
            break
    _save_tier3_status(book_id, status)

    book_dir = db.data_dir(book_id)
    try:
        repo = Repo(book_dir)
        rel_act = os.path.relpath(_tier3_act_path(book_id, act), book_dir)
        rel_status = os.path.relpath(_tier3_status_path(book_id), book_dir)
        repo.index.add([rel_act, rel_status])
        repo.index.commit(f"Auto-approve Tier 3 Act {act} — {len(chapters)} chapters parsed")
    except Exception:
        pass
    return chapters


async def _bg_run_tier4_chapter(book_id: str, chapter: int, user: str, log_cb) -> str:
    """Run Tier 4 for one chapter using the same context as the SSE endpoint."""
    provider = db.get_setting("agent_bible_agent_provider")
    model = db.get_setting("agent_bible_agent_model")

    book_dir = db.data_dir(book_id)
    ns_path = os.path.join(book_dir, "north_star.md")
    north_star = open(ns_path).read() if os.path.exists(ns_path) else "[North Star not yet written]"

    skeleton = _read_skeleton(book_id)
    entity_summary = _format_skeleton_for_context(skeleton)
    chapter_summary = _get_chapter_summary(book_id, chapter)
    prev_summary = _get_chapter_summary(book_id, chapter - 1) if chapter > 1 else ""
    next_summary = _get_chapter_summary(book_id, chapter + 1)

    tier4_status = _read_tier4_status(book_id)
    chapter_info = next((c for c in tier4_status.get("chapters", []) if c["number"] == chapter), None)
    chapter_title = chapter_info.get("title", f"Chapter {chapter}") if chapter_info else f"Chapter {chapter}"

    context = f"## North Star\n\n{north_star}"
    if entity_summary:
        context += f"\n\n## Story Bible — Entities\n\n{entity_summary}"
    if prev_summary:
        context += f"\n\n## Previous Chapter (Chapter {chapter - 1}) — for continuity\n\n{prev_summary}"
    if chapter_summary:
        context += f"\n\n## Current Chapter\n\n{chapter_summary}"
    else:
        context += f"\n\n## Current Chapter\n\nChapter {chapter} — {chapter_title}"
    if next_summary:
        context += f"\n\n## Next Chapter (Chapter {chapter + 1}) — forward context\n\n{next_summary}"

    start_scene = 1 + sum(
        len(ch.get("scenes", []))
        for ch in tier4_status.get("chapters", [])
        if ch["number"] < chapter
    )
    context += f"\n\n## Scene Numbering\n\nScenes are numbered continuously across the whole novel. This chapter's first scene is Scene {start_scene}."

    instruction = prompt_store.get("tier_scenes", TIER_INSTRUCTIONS[3])
    messages = [{"role": "user", "content": f"{context}\n\n---\n\n{instruction}"}]
    system = prompt_store.get("bible_agent", BIBLE_AGENT_SYSTEM)

    log_cb(f"Running Tier 4 Chapter {chapter} (scene list)...")
    return await _bg_call(provider, model, messages, system, user)


def _bg_approve_tier4_chapter(book_id: str, chapter: int, content: str) -> list:
    """Save plan, parse scenes, update status, commit. Returns scenes list."""
    os.makedirs(_tier4_dir(book_id), exist_ok=True)
    with open(_tier4_chapter_path(book_id, chapter), "w") as f:
        f.write(content)

    scene_pattern = re.compile(r'^### Scene (\d+)\s*[—–:\-]+\s*(.+)', re.MULTILINE)
    scenes = [
        {"number": int(m.group(1)), "title": m.group(2).strip(), "approved": False}
        for m in scene_pattern.finditer(content)
    ]
    if not scenes:
        raise RuntimeError(f"No scene headers found in Tier 4 Chapter {chapter} output — ensure agent uses '### Scene N — Title' format")

    status = _read_tier4_status(book_id)
    for ch in status.get("chapters", []):
        if ch["number"] == chapter:
            ch["scenes"] = scenes
            break
    _save_tier4_status(book_id, status)

    book_dir = db.data_dir(book_id)
    try:
        repo = Repo(book_dir)
        rel_chapter = os.path.relpath(_tier4_chapter_path(book_id, chapter), book_dir)
        rel_status = os.path.relpath(_tier4_status_path(book_id), book_dir)
        repo.index.add([rel_chapter, rel_status])
        repo.index.commit(f"Auto-approve scene plan — Chapter {chapter} ({len(scenes)} scenes)")
    except Exception:
        pass
    return scenes


async def _bg_run_scene_brief(book_id: str, chapter_num: int, scene_num: int, user: str, log_cb) -> str:
    """Run a scene brief using the same context as the SSE endpoint."""
    provider = db.get_setting("agent_bible_agent_provider")
    model = db.get_setting("agent_bible_agent_model")

    book_dir = db.data_dir(book_id)
    ns_path = os.path.join(book_dir, "north_star.md")
    north_star = open(ns_path).read() if os.path.exists(ns_path) else ""

    skeleton = _read_skeleton(book_id)
    entity_summary = _format_skeleton_for_context(skeleton)
    chapter_summary = _get_chapter_summary(book_id, chapter_num)

    plan_path = _tier4_chapter_path(book_id, chapter_num)
    scene_plan_section = ""
    if os.path.exists(plan_path):
        plan = open(plan_path).read()
        m = re.search(
            r'^(### Scene ' + str(scene_num) + r'\s*[—–:\-].*?)(?=^### Scene \d+|\Z)',
            plan, re.MULTILINE | re.DOTALL
        )
        if m:
            scene_plan_section = m.group(1).strip()

    prev_scene_tail = ""
    if scene_num > 1:
        prev_path = _tier4_scene_path(book_id, chapter_num, scene_num - 1)
        if os.path.exists(prev_path):
            text = open(prev_path).read()
            prev_scene_tail = text[-600:] if len(text) > 600 else text

    context = f"## North Star\n\n{north_star}"
    if entity_summary:
        context += f"\n\n## Story Bible — Entities\n\n{entity_summary}"
    if chapter_summary:
        context += f"\n\n## Chapter Summary\n\n{chapter_summary}"
    if prev_scene_tail:
        context += f"\n\n## Previous Scene (ending)\n\n…{prev_scene_tail}"
    context += f"\n\n## Scene to Write\n\n{scene_plan_section or f'Scene {scene_num} of Chapter {chapter_num}'}"

    messages = [{"role": "user", "content": context + "\n\nWrite the scene brief now. Use ONLY the 7 section headers from the instructions. Do NOT write prose sentences or paragraphs. Bullets and short phrases only."}]

    log_cb(f"Running scene brief Ch{chapter_num} Sc{scene_num}...")
    return await _bg_call(provider, model, messages, SCENE_WRITER_SYSTEM, user)


async def _bg_approve_scene_brief(book_id: str, chapter_num: int, scene_num: int, content: str, user: str, log_cb) -> None:
    """Save scene brief, update status, bible sync, commit."""
    os.makedirs(_tier4_dir(book_id), exist_ok=True)
    with open(_tier4_scene_path(book_id, chapter_num, scene_num), "w") as f:
        f.write(content)

    # Update scene status
    status = _read_tier4_status(book_id)
    chapter_complete = False
    for ch in status.get("chapters", []):
        if ch["number"] == chapter_num:
            for s in ch.get("scenes", []):
                if s["number"] == scene_num:
                    s["approved"] = True
                    break
            if all(s.get("approved") for s in ch.get("scenes", [])):
                ch["approved"] = True
                chapter_complete = True
            break
    _save_tier4_status(book_id, status)

    # Bible sync — extract new entities (2 attempts)
    provider = db.get_setting("agent_bible_agent_provider")
    model = db.get_setting("agent_bible_agent_model")
    book_dir = db.data_dir(book_id)
    skeleton = _read_skeleton(book_id)

    tier3_status = _read_tier3_status(book_id)
    act_num = next(
        (a["act"] for a in tier3_status.get("acts", [])
         for ch in a.get("chapters", []) if ch["number"] == chapter_num),
        None
    )

    sync_messages = [{"role": "user", "content": (
        f"## Current Entity Skeleton\n\n{json.dumps(skeleton.get('entities', []), indent=2)}\n\n"
        f"## Approved Scene (Chapter {chapter_num}, Scene {scene_num})\n\n{content}\n\n"
        "List any new entities in this scene not already in the skeleton."
    )}]

    new_entity_count = 0
    for attempt in range(2):
        log_cb(f"Bible sync Ch{chapter_num} Sc{scene_num} attempt {attempt + 1}...")
        full_sync = ""
        try:
            async for token in llm.provider_tokens(provider, model, sync_messages, SCENE_BIBLE_SYNC_SYSTEM, user):
                full_sync += token
            result = _extract_json_skeleton(full_sync)
            new_entities = result.get("new_entities", [])
            if new_entities:
                if act_num is not None:
                    for e in new_entities:
                        if act_num not in e.get("appearsInActs", []):
                            e.setdefault("appearsInActs", []).append(act_num)
                skeleton.setdefault("entities", []).extend(new_entities)
                new_entity_count = len(new_entities)
            log_cb(f"Bible sync Ch{chapter_num} Sc{scene_num} ok (+{new_entity_count} entities)")
            break
        except Exception as exc:
            log_cb(f"Bible sync attempt {attempt + 1} failed: {exc}")

    try:
        repo = Repo(book_dir)
        rel_scene = os.path.relpath(_tier4_scene_path(book_id, chapter_num, scene_num), book_dir)
        rel_status = os.path.relpath(_tier4_status_path(book_id), book_dir)
        files_to_add = [rel_scene, rel_status]
        if new_entity_count > 0:
            with open(_skeleton_path(book_id), "w") as f:
                json.dump(skeleton, f, indent=2)
            files_to_add.append(os.path.relpath(_skeleton_path(book_id), book_dir))
        repo.index.add(files_to_add)
        repo.index.commit(f"Auto-approve Ch{chapter_num} Sc{scene_num}{f' (+{new_entity_count} entities)' if new_entity_count else ''}")
    except Exception:
        pass


async def _run_auto_bible(book_id: str, job_id: str, user: str) -> None:
    def log_cb(msg: str) -> None:
        db.append_bible_job_log(job_id, msg)

    def is_cancelled() -> bool:
        job = db.get_bible_job(job_id)
        return job is None or job.get("status") == "cancelled"

    def step(name: str) -> None:
        db.update_bible_job(job_id, current_step=name)

    try:
        # ── Tier 1 ─────────────────────────────────────────────────────────────
        tiers = _read_tiers(book_id)
        if not tiers[0].get("approved"):
            if is_cancelled():
                return
            step("tier1")
            content = await _bg_run_tier12(book_id, 1, user, log_cb)
            _bg_approve_tier12(book_id, 1, content)
            log_cb("Tier 1 approved.")
        else:
            log_cb("Tier 1 already approved — skipping.")

        # ── Tier 2 ─────────────────────────────────────────────────────────────
        tiers = _read_tiers(book_id)
        if not tiers[1].get("approved"):
            if is_cancelled():
                return
            step("tier2")
            content = await _bg_run_tier12(book_id, 2, user, log_cb)
            _bg_approve_tier12(book_id, 2, content)
            log_cb("Tier 2 approved.")
        else:
            log_cb("Tier 2 already approved — skipping.")

        # ── Mini-consolidate ───────────────────────────────────────────────────
        if not os.path.exists(_skeleton_path(book_id)):
            if is_cancelled():
                return
            step("mini_consolidate")
            await _bg_mini_consolidate(book_id, user, log_cb)
        else:
            log_cb("Entity skeleton already exists — skipping mini-consolidate.")

        # ── Tier 3 (per act) ───────────────────────────────────────────────────
        skeleton = _read_skeleton(book_id)
        acts = [a["number"] for a in skeleton.get("acts", [])] or [1, 2, 3]

        for act in acts:
            status = _read_tier3_status(book_id)
            act_info = next((a for a in status.get("acts", []) if a["act"] == act), None)
            if act_info and act_info.get("approved"):
                log_cb(f"Tier 3 Act {act} already approved — skipping.")
                continue
            if is_cancelled():
                return
            step(f"tier3_act{act}")
            content = await _bg_run_tier3_act(book_id, act, user, log_cb)
            chapters = _bg_approve_tier3_act(book_id, act, content)
            log_cb(f"Tier 3 Act {act} approved — {len(chapters)} chapters.")

        # ── Tier 4 (per chapter) ───────────────────────────────────────────────
        tier4_status = _read_tier4_status(book_id)
        all_chapters = [ch["number"] for ch in tier4_status.get("chapters", [])]

        for chapter in all_chapters:
            tier4_status = _read_tier4_status(book_id)
            ch_info = next((c for c in tier4_status.get("chapters", []) if c["number"] == chapter), None)
            # Approved here means scenes have been populated (not all scenes approved)
            if ch_info and ch_info.get("scenes"):
                log_cb(f"Tier 4 Chapter {chapter} plan already locked — skipping.")
                continue
            if is_cancelled():
                return
            step(f"tier4_ch{chapter}")
            content = await _bg_run_tier4_chapter(book_id, chapter, user, log_cb)
            try:
                scenes = _bg_approve_tier4_chapter(book_id, chapter, content)
                log_cb(f"Tier 4 Chapter {chapter} locked — {len(scenes)} scenes.")
            except RuntimeError as e:
                log_cb(f"WARNING: {e} — skipping chapter {chapter}")
                continue

        # ── Scene briefs (per chapter × scene) ────────────────────────────────
        tier4_status = _read_tier4_status(book_id)
        for ch_info in tier4_status.get("chapters", []):
            chapter = ch_info["number"]
            for scene_info in ch_info.get("scenes", []):
                scene_num = scene_info["number"]
                brief_path = _tier4_scene_path(book_id, chapter, scene_num)
                if os.path.exists(brief_path):
                    log_cb(f"Scene brief Ch{chapter} Sc{scene_num} exists — skipping.")
                    continue
                if is_cancelled():
                    return
                step(f"scene_brief_ch{chapter}_sc{scene_num}")
                content = await _bg_run_scene_brief(book_id, chapter, scene_num, user, log_cb)
                await _bg_approve_scene_brief(book_id, chapter, scene_num, content, user, log_cb)

        db.update_bible_job(job_id, status="done", finished_at=datetime.now(timezone.utc).isoformat())
        log_cb("Auto-bible complete.")

    except Exception as exc:
        db.update_bible_job(job_id, status="error", error=str(exc),
                            finished_at=datetime.now(timezone.utc).isoformat())
        log_cb(f"Error: {exc}")


# ── Auto-Bible endpoints ───────────────────────────────────────────────────────

@router.post("/books/{book_id}/phase1/auto-bible", status_code=202)
async def start_auto_bible(book_id: str, user: str = Depends(current_user)):
    if not db.get_book(book_id):
        from fastapi import HTTPException
        raise HTTPException(404, "Book not found")
    existing = db.get_active_bible_job(book_id)
    if existing:
        return {"job_id": existing["id"], "status": "already_running"}
    job_id = db.create_bible_job(book_id, user)
    asyncio.create_task(_run_auto_bible(book_id, job_id, user))
    return {"job_id": job_id, "status": "started"}


@router.get("/books/{book_id}/phase1/auto-bible/status")
def get_auto_bible_status(book_id: str, user: str = Depends(current_user)):
    job = db.get_active_bible_job(book_id)
    if not job:
        from fastapi import HTTPException
        raise HTTPException(404, "No active auto-bible job")
    return {
        "job_id": job["id"],
        "status": job["status"],
        "current_step": job["current_step"],
        "log": json.loads(job["log"]),
        "started_at": job["started_at"],
        "finished_at": job["finished_at"],
        "error": job["error"],
    }


@router.post("/books/{book_id}/phase1/auto-bible/cancel")
def cancel_auto_bible(book_id: str, user: str = Depends(current_user)):
    job = db.get_active_bible_job(book_id)
    if not job:
        from fastapi import HTTPException
        raise HTTPException(404, "No active auto-bible job")
    db.update_bible_job(job["id"], status="cancelled", finished_at=datetime.now(timezone.utc).isoformat())
    return {"ok": True}
