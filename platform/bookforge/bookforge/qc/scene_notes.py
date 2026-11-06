"""What the author decided about a scene's findings: a false alarm to dismiss, or an instruction for the writer.

Stored per scene in `findings.json` next to its text. A finding is identified by the question the continuity check asked
("the scene contradicts a fixed fact: <fact>"), which is the same wording every time for the same fact. A dismissed finding is
not asked about again for that scene; an instruction is added to the problem when that finding is revised.
"""

import json

from .. import scenefiles
from ..project import Project

INSTRUCTION_MAX = 500


def path(project: Project, scene_id: str):
    return scenefiles.scene_dir(project, scene_id) / "findings.json"


def read(project: Project, scene_id: str) -> dict:
    """{"dismissed": [question, ...], "instructions": {question: text}}; empty when the author has said nothing."""
    try:
        data = json.loads(path(project, scene_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    dismissed = data.get("dismissed") if isinstance(data, dict) else None
    instructions = data.get("instructions") if isinstance(data, dict) else None
    return {"dismissed": [str(q) for q in dismissed] if isinstance(dismissed, list) else [],
            "instructions": {str(k): str(v) for k, v in instructions.items()} if isinstance(instructions, dict) else {}}


def _save(project: Project, scene_id: str, notes: dict) -> None:
    p = path(project, scene_id)
    if not notes["dismissed"] and not notes["instructions"]:
        p.unlink(missing_ok=True)
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(notes, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def dismiss(project: Project, scene_id: str, question: str) -> None:
    notes = read(project, scene_id)
    if question not in notes["dismissed"]:
        notes["dismissed"].append(question)
    notes["instructions"].pop(question, None)
    _save(project, scene_id, notes)


def instruct(project: Project, scene_id: str, question: str, text: str) -> None:
    text = " ".join(text.split())[:INSTRUCTION_MAX]
    notes = read(project, scene_id)
    notes["dismissed"] = [q for q in notes["dismissed"] if q != question]
    if text:
        notes["instructions"][question] = text
    else:
        notes["instructions"].pop(question, None)
    _save(project, scene_id, notes)


def clear(project: Project, scene_id: str, question: str) -> None:
    notes = read(project, scene_id)
    notes["dismissed"] = [q for q in notes["dismissed"] if q != question]
    notes["instructions"].pop(question, None)
    _save(project, scene_id, notes)
