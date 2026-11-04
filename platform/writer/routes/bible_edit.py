"""Manual editing of Bible Workshop output (book, acts, chapters, scene plans, scene briefs).

Downstream stages parse these documents with regexes (chapter headers, scene headers,
Plants:/Resolves: seed IDs, scene-brief sections), so a hand edit that breaks the
structure would silently degrade everything after it. Every manual edit therefore goes
through two steps:

  1. POST .../edit/validate  — dry run. Returns what was detected (counts + item list)
     plus errors/warnings. Nothing is written.
  2. POST .../edit/save      — requires confirmed=true (the author has seen the detected
     counts). Re-validates server-side and refuses on errors. Writes the draft to the
     same file the agent writes to; approval is still a separate step.

Only unapproved documents can be edited this way. Approved/locked ones go through
Re-run, as before.
"""
import logging
import os
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import db
import foreshadowing
from deps import current_user
from routes import phase1

router = APIRouter()
log = logging.getLogger(__name__)

ERROR_PREFIX = "⚠"
SCENE_BEAT_RANGE = (12, 18)

# (heading as written by SCENE_WRITER_SYSTEM, severity if missing)
BRIEF_SECTIONS = [
    ("location", "error"),
    ("mood", "warning"),
    ("pov character", "error"),
    ("characters present", "error"),
    ("scene beats", "error"),
    ("key dialogue points", "warning"),
    ("sensory & atmosphere notes", "warning"),
    ("entry / exit state", "error"),
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def normalise_text(text: str) -> str:
    """Line endings and trailing whitespace only — never touches wording."""
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return "\n".join(lines).strip("\n") + "\n"


def _report(counts: dict, items: list[str]) -> dict:
    return {"counts": counts, "items": items, "errors": [], "warnings": []}


def _finish(report: dict) -> dict:
    report["ok"] = not report["errors"]
    return report


def _check_sequence(numbers: list[int], label: str, report: dict) -> None:
    dupes = sorted({n for n in numbers if numbers.count(n) > 1})
    if dupes:
        report["errors"].append(f"Duplicate {label} numbers: {', '.join(map(str, dupes))}.")
        return
    if numbers and numbers != list(range(numbers[0], numbers[0] + len(numbers))):
        report["errors"].append(
            f"{label.capitalize()} numbers must be consecutive and in order; found {', '.join(map(str, numbers))}."
        )


def _unrecognised_headers(text: str, word: str, recognised: int, report: dict) -> None:
    """Flag header-like lines the downstream parser would not recognise."""
    loose = re.findall(rf'^#{{1,6}}\s*{word}\b.*$', text, re.MULTILINE | re.IGNORECASE)
    if len(loose) > recognised:
        report["errors"].append(
            f"{len(loose)} '{word}' headings found but only {recognised} are in the required "
            f"'### {word.capitalize()} N — Title' format."
        )


def _start_expected(prior_counts: list[int | None]) -> int | None:
    """First number this document must start at, or None if an earlier one isn't planned yet."""
    if any(c is None for c in prior_counts):
        return None
    return 1 + sum(c for c in prior_counts if c is not None)


# ── Validators (pure — no I/O) ────────────────────────────────────────────────

def validate_tier(tier: int, text: str) -> dict:
    words = len(text.split())
    if tier == 2:
        acts = [(int(m.group(1)), m.group(2).strip())
                for m in re.finditer(r'^###\s*Act\s+(\d+)\s*[—–:\-]+\s*(.+)$', text, re.MULTILINE)]
        r = _report({"acts": len(acts), "words": words}, [f"Act {n} — {t}" for n, t in acts])
        if not acts:
            r["errors"].append("No acts detected. Use '### Act N — Title' headings.")
        else:
            _check_sequence([n for n, _ in acts], "act", r)
            if acts[0][0] != 1:
                r["errors"].append("Acts must start at Act 1.")
            _unrecognised_headers(text, "act", len(acts), r)
        return _finish(r)
    r = _report({"words": words}, [])
    if words < 50:
        r["warnings"].append("Very short for a book synopsis.")
    if not re.search(r'^##\s*Book Synopsis', text, re.MULTILINE):
        r["warnings"].append("No '## Book Synopsis' heading — downstream agents don't require it, but the agent normally writes one.")
    return _finish(r)


def validate_act(text: str, *, expected_start: int | None) -> dict:
    chapters = phase1._parse_chapters(text)
    r = _report({"chapters": len(chapters)}, [f"Ch {c['number']} — {c['title']}" for c in chapters])
    if not chapters:
        r["errors"].append("No chapters detected. Use '### Chapter N — Title' headings (this is how the chapter list is built).")
        return _finish(r)
    nums = [c["number"] for c in chapters]
    _check_sequence(nums, "chapter", r)
    _unrecognised_headers(text, "chapter", len(chapters), r)
    if expected_start is not None and nums[0] != expected_start:
        r["errors"].append(
            f"This act must start at Chapter {expected_start} (chapters are numbered continuously across acts); found Chapter {nums[0]}."
        )
    elif expected_start is None:
        r["warnings"].append("Earlier acts aren't approved yet, so the starting chapter number can't be checked.")
    blocks = re.split(r'^### Chapter \d+', text, flags=re.MULTILINE)[1:]
    missing = [str(nums[i]) for i, b in enumerate(blocks[:len(nums)])
               if "**Entry:**" not in b or "**Exit:**" not in b]
    if missing:
        r["warnings"].append(f"Chapter(s) {', '.join(missing)} are missing an **Entry:** or **Exit:** line (used as QA contracts).")
    return _finish(r)


def _split_scenes(text: str) -> list[tuple[int, str, str]]:
    headers = list(re.finditer(r'^### Scene (\d+)\s*[—–:\-]+\s*(.+)', text, re.MULTILINE))
    out = []
    for i, m in enumerate(headers):
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        out.append((int(m.group(1)), m.group(2).strip(), text[m.end():end]))
    return out


def validate_chapter_plan(
    text: str, *, chapter: int, expected_start: int | None, next_chapter_start: int | None,
    seed_ids: set[str], entity_names: set[str],
) -> dict:
    scenes = _split_scenes(text)
    r = _report({"scenes": len(scenes)}, [f"Scene {n} — {t}" for n, t, _ in scenes])
    if not scenes:
        r["errors"].append("No scenes detected. Use '### Scene N — Title' headings (this is how scenes are locked).")
        return _finish(r)
    nums = [n for n, _, _ in scenes]
    _check_sequence(nums, "scene", r)
    _unrecognised_headers(text, "scene", len(scenes), r)
    if expected_start is not None and nums[0] != expected_start:
        r["errors"].append(
            f"This chapter's first scene must be Scene {expected_start} (scenes are numbered continuously across the novel); found Scene {nums[0]}."
        )
    elif expected_start is None:
        r["warnings"].append("Earlier chapters aren't all planned yet, so the starting scene number can't be checked.")
    if next_chapter_start is not None and nums[-1] + 1 != next_chapter_start:
        r["errors"].append(
            f"Chapter {chapter + 1} is already locked starting at Scene {next_chapter_start}; "
            f"this chapter must end at Scene {next_chapter_start - 1} (found Scene {nums[-1]})."
        )

    lower_entities = {e.lower() for e in entity_names}
    for n, title, block in scenes:
        for field in ("Plants", "Resolves"):
            m = re.search(rf'\*\*{field}:\*\*[ \t]*(.+)', block)
            if not m:
                continue
            value = m.group(1).strip()
            if not value or value.lower() in ("none", "n/a", "-"):
                continue
            for tok in [t.strip() for t in re.split(r'[,\s]+', value) if t.strip()]:
                if tok not in seed_ids:
                    r["errors"].append(
                        f"Scene {n} {field}: '{tok}' is not a known foreshadowing seed ID"
                        + (f" (known: {', '.join(sorted(seed_ids))})." if seed_ids else " (no seeds exist yet).")
                    )
        if "**Entry:**" not in block or "**Exit:**" not in block:
            r["warnings"].append(f"Scene {n} is missing an **Entry:** or **Exit:** line (scene QA contracts).")
        else:
            entry = re.search(r'\*\*Entry:\*\*\s*(.+)', block)
            exit_ = re.search(r'\*\*Exit:\*\*\s*(.+)', block)
            if entry and exit_ and entry.group(1).strip() == exit_.group(1).strip():
                r["warnings"].append(f"Scene {n}: Entry and Exit are identical.")
        for field in ("Setting", "POV"):
            m = re.search(rf'\*\*{field}:\*\*\s*([^|\n]+)', block)
            if not m:
                r["warnings"].append(f"Scene {n} has no **{field}:** field.")
            elif lower_entities and m.group(1).strip().strip('[]').lower() not in lower_entities:
                r["warnings"].append(
                    f"Scene {n} {field} '{m.group(1).strip()}' isn't in the entity ledger "
                    f"(names/aliases) — add it in the Consolidate stage or check the spelling."
                )
        ch = re.search(r'\*\*Chapter:\*\*\s*(\d+)', block)
        if ch and int(ch.group(1)) != chapter:
            r["warnings"].append(f"Scene {n} says Chapter {ch.group(1)} but this is Chapter {chapter}.")
    return _finish(r)


def validate_scene_brief(text: str) -> dict:
    found: dict[str, str] = {}
    headers = list(re.finditer(r'^##\s+(.+?)\s*$', text, re.MULTILINE))
    for i, m in enumerate(headers):
        key = m.group(1).strip().lower()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        if key in found:
            found[key] += "\n" + text[m.end():end]
        else:
            found[key] = text[m.end():end]
    names = [k for k, _ in BRIEF_SECTIONS]
    present = [k for k in names if k in found]
    beats_body = found.get("scene beats", "")
    beats = len(re.findall(r'^\s*\d+[.)]\s+\S', beats_body, re.MULTILINE))
    r = _report({"sections": len(present), "of_sections": len(names), "beats": beats},
                [k.title() for k in present])
    for key, severity in BRIEF_SECTIONS:
        if key not in found:
            r["errors" if severity == "error" else "warnings"].append(f"Missing section '## {key.title()}'.")
        elif not found[key].strip():
            r["errors" if severity == "error" else "warnings"].append(f"Section '## {key.title()}' is empty.")
    unknown = [h.group(1).strip() for h in headers if h.group(1).strip().lower() not in names]
    if unknown:
        r["warnings"].append(f"Unrecognised section(s): {', '.join(unknown)}. The brief should use only the 8 standard sections.")
    ee = found.get("entry / exit state", "")
    if "entry / exit state" in found:
        if not re.search(r'entry\s*:', ee, re.IGNORECASE):
            r["errors"].append("'Entry / Exit State' has no 'Entry:' line.")
        if not re.search(r'exit\s*:', ee, re.IGNORECASE):
            r["errors"].append("'Entry / Exit State' has no 'Exit:' line (it is the QA contract).")
    if "scene beats" in found and not (SCENE_BEAT_RANGE[0] <= beats <= SCENE_BEAT_RANGE[1]):
        r["warnings"].append(f"{beats} numbered beats found; the brief format asks for {SCENE_BEAT_RANGE[0]}–{SCENE_BEAT_RANGE[1]}.")
    return _finish(r)


# ── Context-aware dispatch ────────────────────────────────────────────────────

class EditTarget(BaseModel):
    kind: Literal["tier", "act", "chapter", "scene"]
    tier: int | None = None      # kind == "tier": 1 or 2
    act: int | None = None       # kind == "act"
    chapter: int | None = None   # kind == "chapter" / "scene"
    scene: int | None = None     # kind == "scene"
    content: str


class SaveBody(EditTarget):
    confirmed: bool = False


def _entity_names(book_id: str) -> set[str]:
    names: set[str] = set()
    for e in phase1._read_skeleton(book_id).get("entities", []):
        if e.get("name"):
            names.add(e["name"])
        names.update(a for a in e.get("aliases", []) if a)
    return names


def _prepare(book_id: str, body: EditTarget) -> tuple[str, dict, str]:
    """Normalise, check the document is editable, validate. Returns (text, report, target_path)."""
    text = normalise_text(body.content)
    if not text.strip():
        raise HTTPException(422, "Content is empty.")
    if text.lstrip().startswith(ERROR_PREFIX):
        raise HTTPException(422, "Content looks like an error message, not a document.")

    if body.kind == "tier":
        if body.tier not in (1, 2):
            raise HTTPException(422, "tier must be 1 or 2.")
        tiers = phase1._read_tiers(book_id)
        if tiers[body.tier - 1].get("approved"):
            raise HTTPException(409, f"Tier {body.tier} is already approved and can't be edited here.")
        if body.tier == 2 and not tiers[0].get("approved"):
            raise HTTPException(409, "Approve Tier 1 first.")
        return text, validate_tier(body.tier, text), phase1._draft_path(book_id, body.tier)

    if body.kind == "act":
        if body.act is None:
            raise HTTPException(422, "act is required.")
        status = phase1._read_tier3_status(book_id)
        acts = status.get("acts", [])
        info = next((a for a in acts if a["act"] == body.act), None)
        if info is None:
            raise HTTPException(404, f"Act {body.act} not found.")
        if info.get("approved"):
            raise HTTPException(409, f"Act {body.act} is approved — use Re-run to change it.")
        prior = [len(a.get("chapters", [])) if a.get("approved") else None for a in acts if a["act"] < body.act]
        return text, validate_act(text, expected_start=_start_expected(prior)), phase1._tier3_act_path(book_id, body.act)

    if body.chapter is None:
        raise HTTPException(422, "chapter is required.")
    status = phase1._read_tier4_status(book_id)
    chapters = sorted(status.get("chapters", []), key=lambda c: c["number"])
    ch = next((c for c in chapters if c["number"] == body.chapter), None)
    if ch is None:
        raise HTTPException(404, f"Chapter {body.chapter} not found.")

    if body.kind == "chapter":
        if ch.get("scenes"):
            raise HTTPException(409, f"Chapter {body.chapter}'s plan is locked — use Re-plan to change it.")
        prior = [len(c["scenes"]) if c.get("scenes") else None for c in chapters if c["number"] < body.chapter]
        nxt = next((c for c in chapters if c["number"] == body.chapter + 1), None)
        next_start = nxt["scenes"][0]["number"] if nxt and nxt.get("scenes") else None
        seed_ids = {s["id"] for s in foreshadowing.read(book_id).get("seeds", [])}
        report = validate_chapter_plan(
            text, chapter=body.chapter, expected_start=_start_expected(prior), next_chapter_start=next_start,
            seed_ids=seed_ids, entity_names=_entity_names(book_id),
        )
        return text, report, phase1._tier4_chapter_path(book_id, body.chapter)

    # scene brief
    if body.scene is None:
        raise HTTPException(422, "scene is required.")
    sc = next((s for s in ch.get("scenes", []) if s["number"] == body.scene), None)
    if sc is None:
        raise HTTPException(404, f"Scene {body.scene} not found in Chapter {body.chapter}.")
    if sc.get("approved"):
        raise HTTPException(409, f"Scene {body.scene} is approved — use Re-run to change it.")
    return text, validate_scene_brief(text), phase1._tier4_scene_path(book_id, body.chapter, body.scene)


@router.post("/books/{book_id}/phase1/edit/validate")
def validate_edit(book_id: str, body: EditTarget):
    """Dry run: report what would be detected. Writes nothing."""
    try:
        _, report, _ = _prepare(book_id, body)
        return report
    except HTTPException:
        raise
    except Exception as e:
        log.exception("edit/validate failed")
        raise HTTPException(500, f"Validation failed: {e}")


@router.post("/books/{book_id}/phase1/edit/save")
def save_edit(book_id: str, body: SaveBody):
    """Save an edited draft. Requires the author's confirmation of the detected counts."""
    if not body.confirmed:
        raise HTTPException(400, "Confirmation required — validate first and confirm the detected counts.")
    try:
        text, report, path = _prepare(book_id, body)
        if not report["ok"]:
            raise HTTPException(422, {"message": "Edit has structural errors; nothing was saved.", "report": report})
        db.ensure_data_dir(book_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
        if body.kind == "scene":
            qa = phase1._tier4_scene_qa_path(book_id, body.chapter, body.scene)
            if os.path.exists(qa):
                os.remove(qa)  # QA result described the previous text
        return {"ok": True, "content": text, "report": report}
    except HTTPException:
        raise
    except Exception as e:
        log.exception("edit/save failed")
        raise HTTPException(500, f"Save failed: {e}")


class SceneQaBody(BaseModel):
    chapter: int
    scene: int
    content: str


@router.post("/books/{book_id}/phase1/edit/scene-qa")
async def scene_brief_qa(book_id: str, body: SceneQaBody, user: str = Depends(current_user)):
    """Run the same brief QA that generated briefs get, on a hand-edited brief."""
    text = normalise_text(body.content)
    qa = await phase1._run_brief_qa(text, user, book_id=book_id)
    path = phase1._tier4_scene_path(book_id, body.chapter, body.scene)
    # Only persist when it describes the text currently on disk.
    if os.path.exists(path) and open(path).read() == text:
        import json
        with open(phase1._tier4_scene_qa_path(book_id, body.chapter, body.scene), "w") as f:
            json.dump(qa, f, indent=2)
    return qa
