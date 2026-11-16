"""Self-healing: slips of the planner that the tool put right during a run, and findings that go away on their own at the next run.

Nothing here needs your attention. The Inbox shows these in their own grey groups ("Fixed automatically", "Will clear on its own") that never
count towards what is open, never block a stage and never trigger a notification.

- `validation/healed.json` keeps, per stage, what the last run corrected (bible/repair.py notes). A stage's entry is replaced each time that stage
  runs; the notes of every piece (an act's chapters, a chapter's scenes) are collected in memory while the layer runs and saved when it succeeds.
- A fix that is needed again by the next run (the same note comes again) is not trusted: it is shown as an open, non-blocking item, because the
  model keeps making the slip or the repair is not holding (`repeated`). Nothing blocks on it.
"""

import json
from datetime import datetime, timezone

STAGES = ("ledger", "acts", "chapters", "scenes")
_pending: dict[tuple[str, str], dict[str, list[str]]] = {}


def path(project):
    return project.book_dir / "validation" / "healed.json"


def load(project) -> dict:
    try:
        data = json.loads(path(project).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def begin(project, stage: str) -> None:
    """A layer starts: forget the notes of an earlier attempt."""
    _pending[(str(project.book_dir), stage)] = {}


def note(project, stage: str, key: str, notes: list[str]) -> None:
    """The notes of one piece (a retry of the same piece replaces its earlier notes, so a failed attempt leaves nothing behind)."""
    _pending.setdefault((str(project.book_dir), stage), {})[key] = list(notes)


def commit(project, stage: str, extra: list[str] | None = None) -> list[str]:
    """The layer succeeded: save what it corrected, remembering what the run before corrected (to spot a slip that comes back)."""
    notes = [n for ns in _pending.pop((str(project.book_dir), stage), {}).values() for n in ns] + list(extra or [])
    data = load(project)
    before = {n for n in (data.get(stage) or {}).get("notes", [])}
    if notes or stage in data:
        data[stage] = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "notes": notes, "previous": sorted(before)}
        path(project).parent.mkdir(parents=True, exist_ok=True)
        path(project).write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return notes


def clear(project, stage: str) -> None:
    data = load(project)
    if data.pop(stage, None) is not None:
        path(project).write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def _kind(note_text: str) -> str:
    return note_text.split(" ")[0] if note_text else ""


def items(project) -> list[dict]:
    """Inbox items for what was corrected: kind 'healed', never blocking. A note that the run before also had is marked `repeated`."""
    out = []
    from .validators import store as findings_store
    for i, f in enumerate(f for f in findings_store.load(project, "ledger").get("findings", []) if f.get("code") == "auto_repaired"):
        out.append({"id": f"healed:ledger:{i}", "kind": "healed", "series": project.root.name, "book": project.book, "stage": "ledger", "blocking": False,
                    "type": "auto_repaired", "title": f["message"], "why": "Corrected by the tool during the last run; the checks passed with the corrected version. Nothing to do.",
                    "quotes": [], "options": [], "status": "healed", "answer": "", "dismiss_reason": "", "items": [], "fingerprint": "", "code": "auto_repaired",
                    "repeated": False, "proposal": None})
    for stage, rec in load(project).items():
        previous = set(rec.get("previous", []))
        for i, text in enumerate(rec.get("notes", [])):
            out.append({"id": f"healed:{stage}:{i}", "kind": "healed", "series": project.root.name, "book": project.book, "stage": stage, "blocking": False,
                        "type": "auto_repaired", "title": text, "why": "Corrected by the tool during the last run; the checks passed with the corrected version. Nothing to do.",
                        "quotes": [], "options": [], "status": "open" if text in previous else "healed", "answer": "", "dismiss_reason": "", "items": [], "fingerprint": "",
                        "code": "auto_repaired", "repeated": text in previous, "proposal": None})
    return out
