import json
import os
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from git import Repo
from pydantic import BaseModel

import db
import llm
import prompt_store
from deps import current_user

router = APIRouter()

STORY_ARCHITECT_SYSTEM = """You are the Story Architect — a creative collaborator helping an author develop the North Star document for their specific novel.

Your job is to draw out their vision through conversation. Ask one or two focused questions per response. When you sense they have a strong handle on premise, protagonist, conflict, world, theme, and landing, tell them you have enough and invite them to lock it.

Keep responses to 150-250 words. Weave questions into prose — never bullet them."""

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
- Start directly with ### Chapter N — no preamble, no commentary""",

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
- Scene numbers restart at 1 for each chapter
- No preamble, no commentary — start directly with ### Scene 1""",
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
    chat_path = os.path.join(book_dir, "north_star_chat.json")
    messages = json.load(open(chat_path)) if os.path.exists(chat_path) else None
    if not os.path.exists(ns_path):
        return {"locked": False, "document": None, "messages": messages}
    with open(ns_path) as f:
        return {"locked": True, "document": f.read(), "messages": messages}


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


@router.post("/books/{book_id}/phase1/north-star/reply")
def north_star_reply(book_id: str, body: ReplyBody, user: str = Depends(current_user)):
    return llm.stream_chat("story_architect", body.messages, prompt_store.get("story_architect", STORY_ARCHITECT_SYSTEM), user)


class LockBody(BaseModel):
    messages: list[dict]


@router.post("/books/{book_id}/phase1/north-star/lock")
async def north_star_lock(book_id: str, body: LockBody, user: str = Depends(current_user)):
    messages = body.messages + [{"role": "user", "content": prompt_store.get("synthesis", SYNTHESIS_PROMPT)}]
    document = await llm.call_llm("story_architect", messages, prompt_store.get("story_architect", STORY_ARCHITECT_SYSTEM), user)

    book_dir = db.ensure_data_dir(book_id)
    path = os.path.join(book_dir, "north_star.md")
    with open(path, "w") as f:
        f.write(document)

    repo = Repo(book_dir)
    repo.index.add(["north_star.md"])
    repo.index.commit("Lock North Star document")

    return {"ok": True, "document": document}


# ── Bible Workshop ─────────────────────────────────────────────────────────────

@router.get("/books/{book_id}/phase1/bible/tiers")
def get_tiers(book_id: str):
    return _read_tiers(book_id)


class RunTierBody(BaseModel):
    tier: int


@router.post("/books/{book_id}/phase1/bible/run-tier")
def run_tier(book_id: str, body: RunTierBody, user: str = Depends(current_user)):
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

    provider = db.get_setting("agent_bible_agent_provider")
    model = db.get_setting("agent_bible_agent_model")
    system = prompt_store.get("bible_agent", BIBLE_AGENT_SYSTEM)

    async def generate():
        if not provider or not model:
            yield f'data: {json.dumps({"type": "error", "message": "Bible Agent has no model assigned — go to Settings."})}\n\n'
            return
        full_text = ""
        try:
            async for token in llm.provider_tokens(provider, model, messages, system, user):
                full_text += token
                yield f'data: {json.dumps({"type": "token", "content": token})}\n\n'
        except Exception as e:
            msg = str(e) or type(e).__name__
            yield f'data: {json.dumps({"type": "error", "message": msg})}\n\n'
            return
        with open(_draft_path(book_id, body.tier), "w") as f:
            f.write(full_text)
        yield f'data: {json.dumps({"type": "done"})}\n\n'

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


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
def edit_tier(book_id: str, body: EditTierBody, user: str = Depends(current_user)):
    idx = body.tier - 1
    tiers = _read_tiers(book_id)
    current = tiers[idx].get("content") or tiers[idx].get("draft") or ""
    if not current:
        from fastapi import HTTPException
        raise HTTPException(400, "No tier content to edit — run the agent first")

    provider = db.get_setting("agent_bible_agent_provider")
    model = db.get_setting("agent_bible_agent_model")
    system = prompt_store.get("tier_editor", TIER_EDITOR_SYSTEM)
    messages = [{"role": "user", "content": (
        f"Make only this change to the document below: {body.directive}\n\n"
        f"Copy everything else verbatim.\n\n"
        f"## Document\n\n{current}"
    )}]

    async def generate():
        if not provider or not model:
            yield f'data: {json.dumps({"type": "error", "message": "Bible Agent has no model assigned — go to Settings."})}\n\n'
            return
        full_text = ""
        try:
            async for token in llm.provider_tokens(provider, model, messages, system, user):
                full_text += token
                yield f'data: {json.dumps({"type": "token", "content": token})}\n\n'
        except Exception as e:
            msg = str(e) or type(e).__name__
            yield f'data: {json.dumps({"type": "error", "message": msg})}\n\n'
            return
        with open(_draft_path(book_id, body.tier), "w") as f:
            f.write(full_text)
        yield f'data: {json.dumps({"type": "done"})}\n\n'

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


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
def mini_consolidate(book_id: str, user: str = Depends(current_user)):
    book_dir = db.data_dir(book_id)

    ns_path = os.path.join(book_dir, "north_star.md")
    north_star = open(ns_path).read() if os.path.exists(ns_path) else "[North Star not yet written]"

    tiers = _read_tiers(book_id)
    tier2 = tiers[1].get("content") or ""
    if not tier2:
        from fastapi import HTTPException
        raise HTTPException(400, "Tier 2 (Acts) must be approved before mini-consolidation")

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

    provider = db.get_setting("agent_bible_agent_provider")
    model = db.get_setting("agent_bible_agent_model")
    system = prompt_store.get("mini_consolidator", MINI_CONSOLIDATOR_SYSTEM)

    async def generate():
        if not provider or not model:
            yield f'data: {json.dumps({"type": "error", "message": "Bible Agent has no model assigned — go to Settings."})}\n\n'
            return
        full_text = ""
        try:
            async for token in llm.provider_tokens(provider, model, messages, system, user):
                full_text += token
                yield f'data: {json.dumps({"type": "token", "content": token})}\n\n'
        except Exception as e:
            yield f'data: {json.dumps({"type": "error", "message": str(e) or type(e).__name__})}\n\n'
            return

        try:
            skeleton = _extract_json_skeleton(full_text)
        except Exception as e:
            import logging
            logging.getLogger(__name__).error("mini-consolidate parse fail:\n%s", full_text[:500])
            yield f'data: {json.dumps({"type": "error", "message": f"JSON parse error: {e}"})}\n\n'
            return

        with open(_skeleton_path(book_id), "w") as f:
            json.dump(skeleton, f, indent=2)

        entity_count = len(skeleton.get("entities", []))
        act_count = len(skeleton.get("acts", []))
        yield f'data: {json.dumps({"type": "saved", "entity_count": entity_count, "act_count": act_count})}\n\n'

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


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


@router.get("/books/{book_id}/phase1/tier3/status")
def get_tier3_status(book_id: str):
    status = _read_tier3_status(book_id)
    for act_info in status.get("acts", []):
        act_info["has_content"] = os.path.exists(_tier3_act_path(book_id, act_info["act"]))
    return status


class RunActBody(BaseModel):
    act: int


@router.post("/books/{book_id}/phase1/tier3/run-act")
def run_tier3_act(book_id: str, body: RunActBody, user: str = Depends(current_user)):
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

    directives_path = os.path.join(book_dir, "directives.md")
    if os.path.exists(directives_path):
        context += f"\n\n## Author Directives\n\n{open(directives_path).read()}"

    instruction = prompt_store.get("tier_chapters", TIER_INSTRUCTIONS[2])
    messages = [{"role": "user", "content": f"{context}\n\n---\n\n{instruction}"}]

    provider = db.get_setting("agent_bible_agent_provider")
    model = db.get_setting("agent_bible_agent_model")
    system = prompt_store.get("bible_agent", BIBLE_AGENT_SYSTEM)

    async def generate():
        if not provider or not model:
            yield f'data: {json.dumps({"type": "error", "message": "Bible Agent has no model assigned — go to Settings."})}\n\n'
            return
        full_text = ""
        try:
            async for token in llm.provider_tokens(provider, model, messages, system, user):
                full_text += token
                yield f'data: {json.dumps({"type": "token", "content": token})}\n\n'
        except Exception as e:
            yield f'data: {json.dumps({"type": "error", "message": str(e) or type(e).__name__})}\n\n'
            return
        os.makedirs(_tier3_dir(book_id), exist_ok=True)
        with open(_tier3_act_path(book_id, body.act), "w") as f:
            f.write(full_text)
        yield f'data: {json.dumps({"type": "done"})}\n\n'

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


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
def edit_tier3_act(book_id: str, body: EditActBody, user: str = Depends(current_user)):
    act_path = _tier3_act_path(book_id, body.act)
    if not os.path.exists(act_path):
        from fastapi import HTTPException
        raise HTTPException(400, "No content for this act — run the agent first")

    current = open(act_path).read()
    provider = db.get_setting("agent_bible_agent_provider")
    model = db.get_setting("agent_bible_agent_model")
    system = prompt_store.get("tier_editor", TIER_EDITOR_SYSTEM)
    messages = [{"role": "user", "content": (
        f"Make only this change to the document below: {body.directive}\n\n"
        f"Copy everything else verbatim.\n\n"
        f"## Document\n\n{current}"
    )}]

    async def generate():
        if not provider or not model:
            yield f'data: {json.dumps({"type": "error", "message": "Bible Agent has no model assigned — go to Settings."})}\n\n'
            return
        full_text = ""
        try:
            async for token in llm.provider_tokens(provider, model, messages, system, user):
                full_text += token
                yield f'data: {json.dumps({"type": "token", "content": token})}\n\n'
        except Exception as e:
            yield f'data: {json.dumps({"type": "error", "message": str(e) or type(e).__name__})}\n\n'
            return
        with open(act_path, "w") as f:
            f.write(full_text)
        yield f'data: {json.dumps({"type": "done"})}\n\n'

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── Tier 4 — per-chapter scene lists ──────────────────────────────────────────

def _tier4_dir(book_id: str) -> str:
    return os.path.join(db.data_dir(book_id), "tier4")


def _tier4_chapter_path(book_id: str, chapter: int) -> str:
    return os.path.join(_tier4_dir(book_id), f"chapter_{chapter:02d}.md")


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
    return status


class RunChapterBody(BaseModel):
    chapter: int


@router.post("/books/{book_id}/phase1/tier4/run-chapter")
def run_tier4_chapter(book_id: str, body: RunChapterBody, user: str = Depends(current_user)):
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

    instruction = prompt_store.get("tier_scenes", TIER_INSTRUCTIONS[3])
    messages = [{"role": "user", "content": f"{context}\n\n---\n\n{instruction}"}]

    provider = db.get_setting("agent_bible_agent_provider")
    model = db.get_setting("agent_bible_agent_model")
    system = prompt_store.get("bible_agent", BIBLE_AGENT_SYSTEM)

    async def generate():
        if not provider or not model:
            yield f'data: {json.dumps({"type": "error", "message": "Bible Agent has no model assigned — go to Settings."})}\n\n'
            return
        full_text = ""
        try:
            async for token in llm.provider_tokens(provider, model, messages, system, user):
                full_text += token
                yield f'data: {json.dumps({"type": "token", "content": token})}\n\n'
        except Exception as e:
            yield f'data: {json.dumps({"type": "error", "message": str(e) or type(e).__name__})}\n\n'
            return
        os.makedirs(_tier4_dir(book_id), exist_ok=True)
        with open(_tier4_chapter_path(book_id, body.chapter), "w") as f:
            f.write(full_text)
        yield f'data: {json.dumps({"type": "done"})}\n\n'

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class ApproveChapterBody(BaseModel):
    chapter: int
    content: str


@router.post("/books/{book_id}/phase1/tier4/approve-chapter")
def approve_tier4_chapter(book_id: str, body: ApproveChapterBody):
    os.makedirs(_tier4_dir(book_id), exist_ok=True)
    with open(_tier4_chapter_path(book_id, body.chapter), "w") as f:
        f.write(body.content)

    status = _read_tier4_status(book_id)
    for ch in status.get("chapters", []):
        if ch["number"] == body.chapter:
            ch["approved"] = True
            break

    _save_tier4_status(book_id, status)

    book_dir = db.data_dir(book_id)
    repo = Repo(book_dir)
    rel_chapter = os.path.relpath(_tier4_chapter_path(book_id, body.chapter), book_dir)
    rel_status = os.path.relpath(_tier4_status_path(book_id), book_dir)
    repo.index.add([rel_chapter, rel_status])
    repo.index.commit(f"Approve Tier 4 Chapter {body.chapter} scenes")

    return {"ok": True}


class EditChapterBody(BaseModel):
    chapter: int
    directive: str


@router.post("/books/{book_id}/phase1/tier4/edit-chapter")
def edit_tier4_chapter(book_id: str, body: EditChapterBody, user: str = Depends(current_user)):
    chapter_path = _tier4_chapter_path(book_id, body.chapter)
    if not os.path.exists(chapter_path):
        from fastapi import HTTPException
        raise HTTPException(400, "No content for this chapter — run the agent first")

    current = open(chapter_path).read()
    provider = db.get_setting("agent_bible_agent_provider")
    model = db.get_setting("agent_bible_agent_model")
    system = prompt_store.get("tier_editor", TIER_EDITOR_SYSTEM)
    messages = [{"role": "user", "content": (
        f"Make only this change to the document below: {body.directive}\n\n"
        f"Copy everything else verbatim.\n\n"
        f"## Document\n\n{current}"
    )}]

    async def generate():
        if not provider or not model:
            yield f'data: {json.dumps({"type": "error", "message": "Bible Agent has no model assigned — go to Settings."})}\n\n'
            return
        full_text = ""
        try:
            async for token in llm.provider_tokens(provider, model, messages, system, user):
                full_text += token
                yield f'data: {json.dumps({"type": "token", "content": token})}\n\n'
        except Exception as e:
            yield f'data: {json.dumps({"type": "error", "message": str(e) or type(e).__name__})}\n\n'
            return
        with open(chapter_path, "w") as f:
            f.write(full_text)
        yield f'data: {json.dumps({"type": "done"})}\n\n'

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
