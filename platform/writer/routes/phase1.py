import json
import os
from datetime import datetime, timezone

from fastapi import APIRouter
from git import Repo
from pydantic import BaseModel

import db
import llm

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

TIER_LABELS = ["Book", "Acts", "Chapters", "Scenes"]

TIER_INSTRUCTIONS = [
    """Write the Tier 1 Book synopsis for this novel.
3-5 paragraphs of narrative: the full journey from opening to ending, the protagonist's arc, the central turning points, how it resolves. Use the specific names, places, and events from the North Star.
Format: ## Book Synopsis""",

    """Write the Tier 2 act breakdown for this novel.
3-4 acts. For each act: its title and scope, the dramatic question it poses, how it opens and closes (one concrete sentence each), and 2-3 specific key events with named characters and places.
Format: ### Act N — [Title]""",

    """Write the Tier 3 chapter summaries for this novel.
List every chapter across all acts. For each chapter: its number and title, which act it belongs to, a 2-3 sentence summary using specific character names and events, and concrete entry/exit states.
Format: ### Chapter N — [Title]
**Act:** N
**Entry:** [world state]
**Exit:** [world state]
[summary]""",

    """Write the Tier 4 scene list for this novel.
Every scene across all chapters. For each scene: zero-padded number (001, 002…), the chapter it belongs to, setting with specific location name and POV character(s), a 1-2 sentence summary, and exact entry/exit states — these become QA contracts.
Format:
### Scene NNN — [Title]
**Chapter:** N | **Setting:** [specific location] | **POV:** [character name]
**Entry:** [exact world state]
**Exit:** [exact world state]
[summary]""",
]


def _read_tiers(book_id: str) -> list[dict]:
    path = os.path.join(db.data_dir(book_id), "tiers.json")
    if not os.path.exists(path):
        return [{"content": None, "approved": False} for _ in range(4)]
    with open(path) as f:
        return json.load(f)


# ── North Star ─────────────────────────────────────────────────────────────────

@router.get("/books/{book_id}/phase1/north-star")
def get_north_star(book_id: str):
    path = os.path.join(db.data_dir(book_id), "north_star.md")
    if not os.path.exists(path):
        return {"locked": False, "document": None}
    with open(path) as f:
        return {"locked": True, "document": f.read()}


class ReplyBody(BaseModel):
    messages: list[dict]


@router.post("/books/{book_id}/phase1/north-star/reply")
def north_star_reply(book_id: str, body: ReplyBody):
    return llm.stream_chat("story_architect", body.messages, STORY_ARCHITECT_SYSTEM)


class LockBody(BaseModel):
    messages: list[dict]


@router.post("/books/{book_id}/phase1/north-star/lock")
async def north_star_lock(book_id: str, body: LockBody):
    messages = body.messages + [{"role": "user", "content": SYNTHESIS_PROMPT}]
    document = await llm.call_llm("story_architect", messages, STORY_ARCHITECT_SYSTEM)

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
def run_tier(book_id: str, body: RunTierBody):
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

    messages = [{"role": "user", "content": f"{context}\n\n---\n\n{TIER_INSTRUCTIONS[idx]}"}]
    return llm.stream_chat("bible_agent", messages, BIBLE_AGENT_SYSTEM)


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

    repo = Repo(book_dir)
    repo.index.add(["tiers.json"])
    repo.index.commit(f"Approve Bible Tier {body.tier} — {TIER_LABELS[body.tier - 1]}")

    return {"ok": True}


class DirectiveBody(BaseModel):
    directive: str


@router.post("/books/{book_id}/phase1/bible/directive")
def add_directive(book_id: str, body: DirectiveBody):
    path = os.path.join(db.ensure_data_dir(book_id), "directives.md")
    ts = datetime.now(timezone.utc).isoformat()
    with open(path, "a") as f:
        f.write(f"\n- [{ts}] {body.directive}")
    return {"ok": True}
