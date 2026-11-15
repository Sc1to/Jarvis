"""The Inbox: everything that stops a stage and waits for you, in one shape.

Two kinds of item, built from what each stage already saves:
- a question (`ledger.yaml`): the synopsis audit's findings and the ledger's own questions, with the quoted sentences and suggested answers;
- a finding (`validation/<stage>.json`): a hard check of any stage (ledger, acts, chapters, scenes, prose) that you have not accepted.
The dashboard shows one list for all of them, blocking items first; answering and dismissing go through bookforge/ops.py, the same code the
command line uses. Nothing here changes a file.
"""

from .bible import store
from .layers import audit as audit_mod
from .validators import accepted, store as findings_store

STAGES = ("ledger", "acts", "chapters", "scenes", "prose")
# the stages whose open items a checkpoint's approval would skip
CHECKPOINT_STAGES = {"direction": (), "ledger": ("ledger",), "structure": ("acts", "chapters", "scenes"), "voice": ("prose",), "final": ("prose",)}


def _question_status(q) -> str:
    if q.status == "answered":
        if q.decided_by == "tool" and not q.applied:
            return "resolved"  # answered by the tool itself (auto mode): shown with its decision and an undo
        return "applied" if q.applied else "answered"
    return q.status  # open | dismissed


def _question_item(project, q) -> dict:
    return {"id": f"question:{q.id}", "kind": "question", "series": project.root.name, "book": project.book, "stage": "ledger",
            "blocking": audit_mod.is_blocking(q) and q.status == "open", "type": q.type or "ledger", "title": q.question, "why": q.why,
            "quotes": list(q.quotes), "options": list(q.options), "status": _question_status(q), "answer": q.answer, "dismiss_reason": q.dismiss_reason,
            "items": [], "fingerprint": ""}


def _finding_item(project, stage: str, f: dict, known: dict, status: str) -> dict:  # noqa: C901
    fp = accepted.fingerprint(stage, f["code"], f.get("items", []))
    rec = known.get(fp, {})
    return {"id": f"finding:{fp}", "kind": "finding", "series": project.root.name, "book": project.book, "stage": stage, "blocking": status == "open",
            "type": f["code"], "title": f["message"], "why": "", "quotes": list(f.get("evidence", [])), "options": [], "status": status, "answer": "",
            "dismiss_reason": rec.get("message", "") if status == "dismissed" else "", "items": list(f.get("items", [])), "fingerprint": fp,
            "code": f["code"]}


def collect(project, include_done: bool = True) -> list[dict]:
    """Every item, blocking first, then by stage order, then by id. `include_done` keeps answered, applied and dismissed ones (their status says so)."""
    items: list[dict] = []
    ledger = store.load_ledger(project)
    for q in (ledger.questions if ledger else []):
        item = _question_item(project, q)
        if item["status"] == "open" or include_done:
            items.append(item)
    known = accepted.load(project)
    for stage in STAGES:
        seen: set[str] = set()
        for f in findings_store.load(project, stage).get("findings", []):
            if f.get("severity") != "hard" and not f.get("accepted"):
                continue
            fp = accepted.fingerprint(stage, f["code"], f.get("items", []))
            if fp in seen:
                continue
            seen.add(fp)
            status = "dismissed" if fp in known else "open"
            if status == "open" or include_done:
                items.append(_finding_item(project, stage, f, known, status))
    from . import resolve
    suggestions = resolve.load(project)
    told = load_answered(project)
    for it in items:
        it["proposal"] = suggestions.get(it["id"])
        if it["kind"] == "finding" and it["status"] == "open" and it["proposal"] and it["proposal"].get("applied"):
            if it["proposal"].get("decided_by") == "you":
                it["status"], it["blocking"], it["answer"] = "answered", False, it["proposal"].get("answer", "")  # you accepted the suggestion: it waits for the next run
            else:
                it["status"], it["blocking"] = "resolved", False  # settled by the tool: shown with its decision and an undo, not asked
        elif it["kind"] == "finding" and it["status"] == "open" and it["id"] in told:
            it["status"], it["blocking"], it["answer"] = "answered", False, told[it["id"]]["text"]  # your instruction waits for the next run
    if not include_done:
        items = [it for it in items if it["status"] == "open"]
    order = {s: i for i, s in enumerate(STAGES)}
    items.sort(key=lambda it: (not it["blocking"], it["status"] != "open", order.get(it["stage"], 9), it["id"]))
    return items


def answered_path(project):
    return project.book_dir / "validation" / "answered.json"


def load_answered(project) -> dict:
    import json
    try:
        data = json.loads(answered_path(project).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def mark_answered(project, item_id: str, text: str) -> None:
    """Your instruction for a finding: kept until the next run reads it (then it is consumed, and the finding is open again if it still holds)."""
    import json
    from datetime import datetime, timezone
    data = load_answered(project)
    data[item_id] = {"text": text, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    answered_path(project).parent.mkdir(parents=True, exist_ok=True)
    answered_path(project).write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def clear_answered(project) -> None:
    answered_path(project).unlink(missing_ok=True)


def summary(project) -> dict:
    items = collect(project, include_done=False)
    ledger = store.load_ledger(project)
    everything = collect(project)
    waiting = sum(1 for it in everything if it["status"] == "answered")  # questions and findings you answered that the next run has not read yet
    resolved = sum(1 for it in everything if it["status"] == "resolved")
    blocking = sum(it["blocking"] for it in items)
    flagged = [n for n in ("ledger", "acts", "chapters", "scenes") if project.state.layers[n].status in ("flagged", "failed")]
    empty_ledger = bool(ledger is not None and not ledger.events and project.state.layers["ledger"].status != "accepted")
    needs_run = blocking == 0 and bool(waiting or flagged or empty_ledger)  # a stage that failed, or an audit that is now answered, has to run again
    return {"open": len(items), "blocking": blocking, "answered_waiting": waiting, "resolved": resolved, "needs_run": needs_run,
            "by_stage": {s: sum(it["stage"] == s for it in items) for s in STAGES if any(it["stage"] == s for it in items)}}


def blocking_for_checkpoint(project, checkpoint: str) -> list[dict]:
    """The open items that approving this checkpoint as it is would skip."""
    stages = CHECKPOINT_STAGES.get(checkpoint, ())
    return [it for it in collect(project, include_done=False) if it["stage"] in stages]


def dismissal_stats(project) -> dict[str, dict]:
    """Per type: raised, answered, dismissed (and the reasons given), from the ledger's questions and the findings you accepted."""
    out: dict[str, dict] = {}

    def row(kind: str) -> dict:
        return out.setdefault(kind, {"raised": 0, "answered": 0, "dismissed": 0, "reasons": []})

    ledger = store.load_ledger(project)
    for q in (ledger.questions if ledger else []):
        r = row(q.type or "ledger")
        r["raised"] += 1
        if q.status == "answered":
            r["answered"] += 1
        elif q.status == "dismissed":
            r["dismissed"] += 1
            if q.dismiss_reason:
                r["reasons"].append(q.dismiss_reason)
    for rec in accepted.load(project).values():
        r = row(rec.get("code", "finding"))
        r["raised"] += 1
        r["dismissed"] += 1
        if rec.get("message"):
            r["reasons"].append(rec["message"])
    for r in out.values():
        decided = r["answered"] + r["dismissed"]
        r["dismissal_rate"] = round(r["dismissed"] / decided, 2) if decided else None
    return out


def last_run(project) -> dict:
    ledger = store.load_ledger(project)
    return dict(ledger.last_run) if ledger and ledger.last_run else {}


def find_finding(project, fingerprint: str) -> tuple[str, dict] | None:
    """(stage, finding) for a fingerprint, looked up in the saved findings (a fingerprint's items can hold any characters, so it is never taken apart)."""
    for stage in STAGES:
        for f in findings_store.load(project, stage).get("findings", []):
            if accepted.fingerprint(stage, f["code"], f.get("items", [])) == fingerprint:
                return stage, f
    return None


def skip_text(items: list[dict]) -> str:
    """What approving as it is would skip, for the refusal and the confirmation."""
    return "; ".join(f"{it['stage']}: {it['type']} ({it['title'][:90]})" for it in items[:8]) + (f"; and {len(items) - 8} more" if len(items) > 8 else "")
