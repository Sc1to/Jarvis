import json
import os
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import db
from deps import current_user
import llm
import prompt_store

router = APIRouter()

# ── Prompts ────────────────────────────────────────────────────────────────────

SCENE_PLANNER_SYSTEM = """Extract the scene plan for a specific chapter from a novel's scene bible.

Return ONLY valid JSON — a list of scene objects. No preamble, no fences:
[
  {
    "scene": 1,
    "brief": "one-sentence scene summary",
    "entry_state": "what must be true when the scene begins",
    "exit_state": "what must be true when the scene ends"
  }
]

Extract ONLY the scenes belonging to the requested chapter number."""

WRITER_SYSTEM = """You are a literary novelist. Write scene prose that is:
- Concrete and sensory — show, don't tell
- Consistent with all entity facts in the ledger
- Faithful to the narrative voice established in the North Star
- Precisely meeting the exit state contract by scene end

Write ONLY prose. No headers, no scene numbers, no formatting markers. Begin the scene directly.
Target length: 600-900 words."""

QA_SYSTEM = """You are a novel quality assurance agent. Review the scene for consistency.

Check:
1. Entity consistency — names, appearances, relationships match the ledger exactly
2. Exit state contract — specified conditions are established by scene end
3. Continuity — no contradictions with prior scenes in this chapter
4. Voice — dialogue and behaviour consistent with character coreFacts

Return ONLY valid JSON — no preamble, no fences:
{"pass": true, "issues": [{"type": "entity|continuity|contract|voice", "description": "...", "severity": "warning|error"}], "notes": "brief overall assessment"}

pass = true when there are zero error-severity issues. Warnings alone do not fail."""

BIBLE_UPDATER_SYSTEM = """You are the Bible Updater. Update the entity ledger with facts that emerged in this approved chapter.

Rules:
- ADD only — never delete or contradict existing coreFacts or eventLog entries
- New named characters → add with next available CHAR_XXX id
- New named locations → LOC_XXX, factions → FRAC_XXX, significant objects → OBJ_XXX
- eventLog: add one entry per significant scene event, including the chapter number
- lifecycle: extend the act list if an entity appears in a new act
- Direct contradictions with existing coreFacts → add to that entity's "flags" list

Return the COMPLETE updated ledger as valid JSON. No preamble, no fences. Same structure as input."""

# ── Helpers ────────────────────────────────────────────────────────────────────

def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"

def _chapter_path(book_id: str, chapter: int) -> str:
    return os.path.join(db.data_dir(book_id), f"chapter_{chapter:02d}.md")

def _chapter_meta_path(book_id: str, chapter: int) -> str:
    return os.path.join(db.data_dir(book_id), f"chapter_{chapter:02d}_meta.json")

def _chapter_plan_path(book_id: str, chapter: int) -> str:
    return os.path.join(db.data_dir(book_id), f"chapter_{chapter:02d}_plan.json")

def _read_meta(book_id: str, chapter: int) -> dict | None:
    p = _chapter_meta_path(book_id, chapter)
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)

def _read_tiers(book_id: str) -> list[dict]:
    p = os.path.join(db.data_dir(book_id), "tiers.json")
    return json.load(open(p)) if os.path.exists(p) else []

def _read_north_star(book_id: str) -> str:
    p = os.path.join(db.data_dir(book_id), "north_star.md")
    return open(p).read() if os.path.exists(p) else ""

def _read_bible(book_id: str) -> dict:
    p = os.path.join(db.data_dir(book_id), "bible.json")
    return json.load(open(p)) if os.path.exists(p) else {"ledger": {}}

def _extract_json(text: str) -> dict:
    text = text.strip()
    if "```json" in text:
        text = text[text.index("```json") + 7:]
        text = text[:text.index("```")]
    elif "```" in text:
        text = text[text.index("```") + 3:]
        text = text[:text.rindex("```")]
    s, e = text.find("{"), text.rfind("}") + 1
    if s == -1 or e == 0:
        raise ValueError("No JSON object found")
    return json.loads(text[s:e])

def _extract_json_list(text: str) -> list:
    text = text.strip()
    if "```json" in text:
        text = text[text.index("```json") + 7:]
        text = text[:text.index("```")]
    elif "```" in text:
        text = text[text.index("```") + 3:]
        text = text[:text.rindex("```")]
    s, e = text.find("["), text.rfind("]") + 1
    if s == -1 or e == 0:
        raise ValueError("No JSON array found")
    return json.loads(text[s:e])

async def _call(provider: str, model: str, messages: list[dict], system: str, user_id: str = "local") -> str:
    result = ""
    async for token in llm.provider_tokens(provider, model, messages, system, user_id):
        result += token
    return result

# ── Status ─────────────────────────────────────────────────────────────────────

@router.get("/books/{book_id}/phase3/status")
def phase3_status(book_id: str):
    book_dir = db.data_dir(book_id)
    bible_path = os.path.join(book_dir, "bible.json")
    phase2_approved = False
    if os.path.exists(bible_path):
        with open(bible_path) as f:
            phase2_approved = json.load(f).get("metadata", {}).get("phase2_approved", False)

    chapters = []
    i = 1
    while True:
        meta = _read_meta(book_id, i)
        if meta is None and not os.path.exists(_chapter_path(book_id, i)):
            break
        chapters.append({
            "chapter": i,
            "status": meta.get("status", "written") if meta else "unknown",
            "scene_count": meta.get("scene_count", 0) if meta else 0,
            "approved": (meta or {}).get("status") == "approved",
            "bible_updated": (meta or {}).get("bible_updated", False),
        })
        i += 1

    last_approved = not chapters or chapters[-1]["approved"]
    next_chapter = len(chapters) + 1 if (phase2_approved and last_approved) else None

    return {
        "phase2_approved": phase2_approved,
        "chapters": chapters,
        "next_chapter": next_chapter,
    }

# ── Write Chapter ──────────────────────────────────────────────────────────────

class WriteChapterBody(BaseModel):
    chapter: int

@router.post("/books/{book_id}/phase3/write-chapter")
def write_chapter(book_id: str, body: WriteChapterBody, user: str = Depends(current_user)):
    async def generate():
        chapter = body.chapter
        book_dir = db.data_dir(book_id)

        writer_provider = db.get_setting("agent_writer_agent_provider")
        writer_model = db.get_setting("agent_writer_agent_model")
        qa_provider = db.get_setting("agent_qa_agent_provider")
        qa_model = db.get_setting("agent_qa_agent_model")
        planner_provider = db.get_setting("agent_bible_agent_provider")
        planner_model = db.get_setting("agent_bible_agent_model")

        missing = [k for k, v in [("writer_agent", writer_provider), ("qa_agent", qa_provider), ("bible_agent", planner_provider)] if not v]
        if missing:
            yield _sse({"type": "error", "message": f"Agents not configured in Settings: {', '.join(missing)}"})
            return

        north_star = _read_north_star(book_id)
        tiers = _read_tiers(book_id)
        tier4_content = tiers[3]["content"] if len(tiers) >= 4 and tiers[3].get("content") else ""
        bible = _read_bible(book_id)
        ledger_json = json.dumps(bible.get("ledger", {}))

        # Extract scene plan from Tier 4
        yield _sse({"type": "plan_start"})
        try:
            plan_text = await _call(
                planner_provider, planner_model,
                [{"role": "user", "content": f"Chapter number: {chapter}\n\nTier 4 (Scenes bible):\n\n{tier4_content}"}],
                prompt_store.get("scene_planner", SCENE_PLANNER_SYSTEM),
                user,
            )
            scene_plan = _extract_json_list(plan_text)
        except Exception as e:
            yield _sse({"type": "error", "message": f"Scene plan extraction failed: {e}"})
            return

        yield _sse({"type": "plan_done", "scene_count": len(scene_plan), "scenes": scene_plan})

        # Prior chapter bridge (last 200 words of each prior chapter for continuity)
        # ponytail: full prior chapters not in context; add chapter summaries if cross-chapter continuity is needed
        prior_bridge = ""
        for prev in range(1, chapter):
            prev_path = _chapter_path(book_id, prev)
            if os.path.exists(prev_path):
                words = open(prev_path).read().split()
                snippet = " ".join(words[-200:]) if len(words) > 200 else " ".join(words)
                prior_bridge += f"\n\n[End of Chapter {prev}]:\n{snippet}"

        completed_scenes: list[str] = []
        scene_results: list[dict] = []

        for scene_def in scene_plan:
            scene_num = scene_def.get("scene", len(completed_scenes) + 1)
            brief = scene_def.get("brief", "")
            entry_state = scene_def.get("entry_state", "")
            exit_state = scene_def.get("exit_state", "")

            scene_text = ""
            qa_result: dict | None = None
            attempt = 0

            while attempt < 3:
                attempt += 1
                yield _sse({
                    "type": "scene_start" if attempt == 1 else "rewrite_start",
                    "scene": scene_num, "total": len(scene_plan), "attempt": attempt, "brief": brief,
                })

                prior_text = "\n\n---\n\n".join(completed_scenes) if completed_scenes else "None yet."
                rewrite_note = ""
                if attempt > 1 and qa_result:
                    errors = [i["description"] for i in qa_result.get("issues", []) if i.get("severity") == "error"]
                    rewrite_note = "\n\nPrevious attempt issues — address in rewrite:\n" + "\n".join(f"- {e}" for e in errors)

                writer_user = (
                    f"## North Star\n\n{north_star}\n\n"
                    f"## Entity Ledger\n\n{ledger_json}\n\n"
                    f"## Prior scenes in this chapter\n\n{prior_text}"
                    + (f"\n\n## Prior chapter context\n\n{prior_bridge}" if prior_bridge else "")
                    + f"\n\n## Scene contract\n\n"
                    f"Chapter: {chapter} | Scene: {scene_num}\n"
                    f"Brief: {brief}\nEntry state: {entry_state}\nExit state: {exit_state}"
                    + rewrite_note
                    + "\n\nWrite this scene now."
                )

                scene_text = ""
                try:
                    async for token in llm.provider_tokens(
                        writer_provider, writer_model,
                        [{"role": "user", "content": writer_user}],
                        prompt_store.get("writer", WRITER_SYSTEM),
                        user,
                    ):
                        scene_text += token
                        yield _sse({"type": "token", "content": token})
                except Exception as e:
                    yield _sse({"type": "error", "message": f"Writer error on scene {scene_num}: {e}"})
                    return

                yield _sse({"type": "scene_written", "scene": scene_num, "word_count": len(scene_text.split())})

                # QA
                yield _sse({"type": "qa_start", "scene": scene_num, "attempt": attempt})
                qa_user = (
                    f"## Entity Ledger\n\n{ledger_json}\n\n"
                    f"## Prior scenes in this chapter\n\n{prior_text}\n\n"
                    f"## Exit state contract\n\n{exit_state}\n\n"
                    f"## Scene to review\n\n{scene_text}"
                )
                try:
                    qa_text = await _call(qa_provider, qa_model, [{"role": "user", "content": qa_user}], prompt_store.get("qa", prompt_store.get("qa", QA_SYSTEM)), user)
                    qa_result = _extract_json(qa_text)
                except Exception as e:
                    qa_result = {"pass": True, "issues": [{"type": "system", "description": str(e), "severity": "warning"}], "notes": "QA skipped"}

                passed = qa_result.get("pass", True)
                yield _sse({
                    "type": "qa_result", "scene": scene_num, "attempt": attempt,
                    "pass": passed, "issues": qa_result.get("issues", []), "notes": qa_result.get("notes", ""),
                })

                if passed or attempt >= 3:
                    break

            completed_scenes.append(scene_text)
            scene_results.append({
                "scene": scene_num, "brief": brief,
                "entry_state": entry_state, "exit_state": exit_state,
                "attempts": attempt,
                "qa_pass": qa_result.get("pass", True) if qa_result else True,
                "qa_notes": qa_result.get("notes", "") if qa_result else "",
                "word_count": len(scene_text.split()),
            })

        # Assemble and save
        chapter_md = f"# Chapter {chapter}\n\n" + "\n\n---\n\n".join(
            f"## Scene {r['scene']}\n\n{prose}"
            for r, prose in zip(scene_results, completed_scenes)
        )
        meta = {
            "chapter": chapter,
            "scene_count": len(scene_plan),
            "scenes": scene_results,
            "status": "written",
            "written_at": datetime.now(timezone.utc).isoformat(),
            "approved_at": None,
            "bible_updated": False,
        }

        with open(_chapter_path(book_id, chapter), "w") as f:
            f.write(chapter_md)
        with open(_chapter_meta_path(book_id, chapter), "w") as f:
            json.dump(meta, f, indent=2)
        with open(_chapter_plan_path(book_id, chapter), "w") as f:
            json.dump(scene_plan, f, indent=2)

        from git import Repo
        repo = Repo(book_dir)
        repo.index.add([f"chapter_{chapter:02d}.md", f"chapter_{chapter:02d}_meta.json", f"chapter_{chapter:02d}_plan.json"])
        repo.index.commit(f"Write Chapter {chapter} — {len(scene_plan)} scenes")

        yield _sse({"type": "chapter_done", "chapter": chapter, "scene_count": len(scene_plan)})

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

# ── Get Chapter ────────────────────────────────────────────────────────────────

@router.get("/books/{book_id}/phase3/chapter/{chapter}")
def get_chapter(book_id: str, chapter: int):
    content_path = _chapter_path(book_id, chapter)
    if not os.path.exists(content_path):
        return None
    return {
        "chapter": chapter,
        "content": open(content_path).read(),
        "meta": _read_meta(book_id, chapter),
    }

# ── Approve Chapter (runs Bible Updater) ──────────────────────────────────────

@router.post("/books/{book_id}/phase3/chapter/{chapter}/approve")
def approve_chapter(book_id: str, chapter: int, user: str = Depends(current_user)):
    async def generate():
        bu_provider = db.get_setting("agent_bible_updater_provider")
        bu_model = db.get_setting("agent_bible_updater_model")
        if not bu_provider or not bu_model:
            yield _sse({"type": "error", "message": "Bible Updater has no model assigned — go to Settings."})
            return

        book_dir = db.data_dir(book_id)
        chapter_path = _chapter_path(book_id, chapter)
        if not os.path.exists(chapter_path):
            yield _sse({"type": "error", "message": f"Chapter {chapter} not found."})
            return

        chapter_content = open(chapter_path).read()
        bible = _read_bible(book_id)
        ledger_json = json.dumps(bible.get("ledger", {}))

        yield _sse({"type": "status", "message": f"Running Bible Updater for Chapter {chapter}…"})

        bu_user = (
            f"## Current Entity Ledger\n\n{ledger_json}\n\n"
            f"## Chapter {chapter} prose\n\n{chapter_content}\n\n"
            "Update the ledger with facts from this chapter."
        )

        full_text = ""
        try:
            async for token in llm.provider_tokens(bu_provider, bu_model, [{"role": "user", "content": bu_user}], prompt_store.get("bible_updater", BIBLE_UPDATER_SYSTEM), user):
                full_text += token
                yield _sse({"type": "token", "content": token})
        except Exception as e:
            yield _sse({"type": "error", "message": str(e)})
            return

        try:
            updated = _extract_json(full_text)
        except Exception as e:
            yield _sse({"type": "error", "message": f"Could not parse Bible Updater response: {e}"})
            return

        if "ledger" in updated:
            updated = updated["ledger"]

        bible["ledger"] = updated
        bible.setdefault("metadata", {})["last_updated_chapter"] = chapter

        with open(os.path.join(book_dir, "bible.json"), "w") as f:
            json.dump(bible, f, indent=2)

        meta = _read_meta(book_id, chapter) or {}
        meta.update({"status": "approved", "approved_at": datetime.now(timezone.utc).isoformat(), "bible_updated": True})
        with open(_chapter_meta_path(book_id, chapter), "w") as f:
            json.dump(meta, f, indent=2)

        from git import Repo
        repo = Repo(book_dir)
        repo.index.add([f"chapter_{chapter:02d}_meta.json", "bible.json"])
        repo.index.commit(f"Approve Chapter {chapter} — Bible updated")

        yield _sse({"type": "saved", "chapter": chapter, "entity_count": len(updated)})

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

# ── Rewrite Scene ──────────────────────────────────────────────────────────────

class RewriteBody(BaseModel):
    directive: str

@router.post("/books/{book_id}/phase3/chapter/{chapter}/scene/{scene}/rewrite")
def rewrite_scene(book_id: str, chapter: int, scene: int, body: RewriteBody, user: str = Depends(current_user)):
    async def generate():
        writer_provider = db.get_setting("agent_writer_agent_provider")
        writer_model = db.get_setting("agent_writer_agent_model")
        qa_provider = db.get_setting("agent_qa_agent_provider")
        qa_model = db.get_setting("agent_qa_agent_model")
        if not writer_provider or not qa_provider:
            yield _sse({"type": "error", "message": "Writer or QA agent not configured in Settings."})
            return

        book_dir = db.data_dir(book_id)
        chapter_path = _chapter_path(book_id, chapter)
        if not os.path.exists(chapter_path):
            yield _sse({"type": "error", "message": "Chapter not found."})
            return

        north_star = _read_north_star(book_id)
        ledger_json = json.dumps(_read_bible(book_id).get("ledger", {}))

        plan_path = _chapter_plan_path(book_id, chapter)
        scene_plan = json.load(open(plan_path)) if os.path.exists(plan_path) else []
        scene_def = next((s for s in scene_plan if s.get("scene") == scene), {})

        content = open(chapter_path).read()
        parts = content.split("## Scene ")
        prior_scenes = [p.split("\n", 1)[1].strip() for p in parts[1:] if p.split("\n", 1)[0].strip() != str(scene)]
        prior_text = "\n\n---\n\n".join(prior_scenes) if prior_scenes else "None yet."

        exit_state = scene_def.get("exit_state", "")
        brief = scene_def.get("brief", "")

        yield _sse({"type": "rewrite_start", "scene": scene, "attempt": 1, "brief": brief})

        writer_user = (
            f"## North Star\n\n{north_star}\n\n"
            f"## Entity Ledger\n\n{ledger_json}\n\n"
            f"## Prior scenes in this chapter\n\n{prior_text}\n\n"
            f"## Scene contract\n\nChapter: {chapter} | Scene: {scene}\n"
            f"Brief: {brief}\nExit state: {exit_state}\n\n"
            f"## Author directive\n\n{body.directive}\n\n"
            "Rewrite this scene addressing the directive."
        )

        scene_text = ""
        try:
            async for token in llm.provider_tokens(
                writer_provider, writer_model,
                [{"role": "user", "content": writer_user}],
                prompt_store.get("writer", WRITER_SYSTEM),
                user,
            ):
                scene_text += token
                yield _sse({"type": "token", "content": token})
        except Exception as e:
            yield _sse({"type": "error", "message": str(e)})
            return

        yield _sse({"type": "scene_written", "scene": scene, "word_count": len(scene_text.split())})

        yield _sse({"type": "qa_start", "scene": scene, "attempt": 1})
        qa_user = (
            f"## Entity Ledger\n\n{ledger_json}\n\n"
            f"## Prior scenes\n\n{prior_text}\n\n"
            f"## Exit state contract\n\n{exit_state}\n\n"
            f"## Scene to review\n\n{scene_text}"
        )
        try:
            qa_result = _extract_json(await _call(qa_provider, qa_model, [{"role": "user", "content": qa_user}], prompt_store.get("qa", QA_SYSTEM)))
        except Exception as e:
            qa_result = {"pass": True, "issues": [], "notes": f"QA error: {e}"}

        yield _sse({
            "type": "qa_result", "scene": scene, "attempt": 1,
            "pass": qa_result.get("pass", True),
            "issues": qa_result.get("issues", []),
            "notes": qa_result.get("notes", ""),
        })

        # Patch the chapter file — replace just this scene's prose
        new_content = re.sub(
            rf"(## Scene {scene}\n\n)(.*?)(?=\n\n---\n\n## Scene |\Z)",
            f"## Scene {scene}\n\n{scene_text}",
            content,
            flags=re.DOTALL,
        )
        with open(chapter_path, "w") as f:
            f.write(new_content)

        meta = _read_meta(book_id, chapter) or {}
        for s in meta.get("scenes", []):
            if s["scene"] == scene:
                s.update({"qa_pass": qa_result.get("pass", True), "qa_notes": qa_result.get("notes", ""), "word_count": len(scene_text.split())})
        meta["status"] = "written"
        with open(_chapter_meta_path(book_id, chapter), "w") as f:
            json.dump(meta, f, indent=2)

        from git import Repo
        repo = Repo(book_dir)
        repo.index.add([f"chapter_{chapter:02d}.md", f"chapter_{chapter:02d}_meta.json"])
        repo.index.commit(f"Rewrite Chapter {chapter} Scene {scene}")

        yield _sse({"type": "saved", "scene": scene})

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
