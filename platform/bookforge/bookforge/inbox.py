"""The Inbox: everything that stops a stage and waits for you, in one shape.

Two kinds of item, built from what each stage already saves:
- a question (`ledger.yaml`): the synopsis audit's findings and the ledger's own questions, with the quoted sentences and suggested answers;
- a finding (`validation/<stage>.json`): a hard check of any stage (ledger, acts, chapters, scenes, prose) that you have not accepted.
The dashboard shows one list for all of them, blocking items first; answering and dismissing go through bookforge/ops.py, the same code the
command line uses. Nothing here changes a file.
"""

from .bible import store
from .remedies import registry
from .layers import audit as audit_mod
from .validators import accepted, store as findings_store

STAGES = ("ledger", "acts", "chapters", "scenes", "prose")
# the stages whose open items a checkpoint's approval would skip
CHECKPOINT_STAGES = {"direction": (), "ledger": ("ledger",), "structure": ("acts", "chapters", "scenes"), "voice": ("prose",), "final": ("prose",)}


def _older(saved: dict) -> bool:
    """Were these findings saved by an older version of the checks (or before findings carried a version)?"""
    try:
        return int(saved.get("checks_version", 0)) < registry.CHECKS_VERSION
    except (TypeError, ValueError):
        return True


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


# findings of the acts stage that one cause produces together: acts planned for a ledger that has since changed
STALE_ACTS_CODES = ("event_in_no_act", "resolution_not_in_last_act", "acts_differ_from_capacity", "final_turning_point_is_transition", "sizing_reason_mismatch",
                    "unknown_event", "turning_point_not_in_act", "event_in_two_acts", "acts_out_of_order", "turning_point_without_event")


def stale_acts(project) -> dict | None:
    """When the acts were planned for an earlier ledger: {"missing": events in no act, "unknown": act events the ledger no longer has}. None when they match
    (or there is no ledger with events, or no acts)."""
    if project.state.layers["acts"].status == "pending":
        return None  # already being planned again
    ledger = store.load_ledger(project)
    try:
        acts = store.load_acts(project) if store.acts_path(project).exists() else []
    except Exception:
        return None
    if ledger is None or not ledger.events or not acts:
        return None
    ids = [e.id for e in ledger.events if not e.carried_in and e.source != "derived"]
    in_acts = {x for a in acts for x in a.events}
    missing, unknown = [i for i in ids if i not in in_acts], sorted(x for x in in_acts if x not in {e.id for e in ledger.events})
    return {"missing": missing, "unknown": unknown} if missing or unknown else None


def _stale_acts_item(project, stale: dict, hidden: list[dict]) -> dict:
    parts = []
    if stale["missing"]:
        parts.append(f"{len(stale['missing'])} event(s) are in no act ({', '.join(stale['missing'][:6])}{'...' if len(stale['missing']) > 6 else ''})")
    if stale["unknown"]:
        parts.append(f"{len(stale['unknown'])} event(s) the acts use are not in the ledger any more ({', '.join(stale['unknown'][:6])})")
    return {"id": "finding:acts:acts_stale", "kind": "finding", "series": project.root.name, "book": project.book, "stage": "acts", "blocking": True, "type": "acts_stale",
            "title": "These acts were planned for an earlier version of the ledger: " + "; ".join(parts) + ".",
            "why": f"Planning the acts again from the current ledger settles all {len(hidden)} checks that failed because of this at once. Add your decisions below (which act an event belongs to, what the last act turns on): they steer the new plan.",
            "quotes": [h["title"][:160] for h in hidden[:5]], "options": [], "status": "open", "answer": "", "dismiss_reason": "", "items": stale["missing"][:8] + stale["unknown"][:8],
            "fingerprint": "", "code": "acts_stale", "actions": ["redo_acts"], "proposal": None}


def collect(project, include_done: bool = True) -> list[dict]:
    """Every item, blocking first, then by stage order, then by id. `include_done` keeps answered, applied and dismissed ones (their status says so)."""
    items: list[dict] = []
    ledger = store.load_ledger(project)
    for q in (ledger.questions if ledger else []):
        item = _question_item(project, q)
        if item["status"] == "open" or include_done:
            items.append(item)
    known = accepted.load(project)
    from .constants import REDO_NOTE
    for stage in STAGES:
        layer = project.state.layers[stage]
        if layer.status == "pending" and layer.note == REDO_NOTE:
            continue  # reset to be planned again: its saved findings describe the file that is being replaced
        seen: set[str] = set()
        saved = findings_store.load(project, stage)
        older = _older(saved)  # found by an older version of the checks
        for f in saved.get("findings", []):
            if f.get("severity") != "hard" and not f.get("accepted"):
                continue
            fp = accepted.fingerprint(stage, f["code"], f.get("items", []))
            if fp in seen:
                continue
            seen.add(fp)
            status = "dismissed" if fp in known else "open"
            if status == "open" or include_done:
                item = _finding_item(project, stage, f, known, status)
                if status == "open":
                    if older or registry.retired(f["code"], f.get("items", [])):
                        item["status"], item["blocking"] = "outdated", False
                        item["why"] = ("Found by an older version of the checks, which no longer finds it this way. Run the stage again: this clears, or comes back "
                                       "if it still holds. Nothing to answer.")
                    elif not registry.stops_a_stage(f["code"], stage):
                        item["blocking"], item["warning"] = False, True  # a wording, rating or advisory finding never stops a stage: a warning to read
                items.append(item)
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
    from . import healing
    items += healing.items(project)  # what the tool put right by itself: grey, never blocking (a slip that came back is open, still not blocking)
    stale = stale_acts(project)
    if stale:  # five checks with one cause are one item: plan the acts again
        group = [it for it in items if it["stage"] == "acts" and it["kind"] == "finding" and it["status"] == "open" and it.get("code") in STALE_ACTS_CODES]
        items = [it for it in items if it not in group]
        items.insert(0, _stale_acts_item(project, stale, group))
    items = _group(items)  # one cause is one item, not thirty-six
    if not include_done:
        items = [it for it in items if it["status"] == "open"]
    order = {s: i for i, s in enumerate(STAGES)}
    items.sort(key=lambda it: (not it["blocking"], it["status"] != "open", order.get(it["stage"], 9), it["id"]))
    return items


GROUP_MIN = 3


def _group(items: list[dict]) -> list[dict]:
    """Open findings of one code about one subject (the same scene, track or chapter first in their items) are ONE item: the first stays, carrying
    `group` (how many, and the items of each, so answering or dismissing it settles them all), the others are not listed. Findings that are
    already handled, the stale-acts item and questions are left alone."""
    buckets: dict[tuple, list[dict]] = {}
    for it in items:
        if it["kind"] == "finding" and it["status"] in ("open", "outdated") and it.get("items") and it.get("code") not in ("acts_stale",):
            buckets.setdefault((it["stage"], it["code"], it["items"][0], it["status"]), []).append(it)
    drop: set[int] = set()
    for members in buckets.values():
        if len(members) < GROUP_MIN:
            continue
        lead = members[0]
        lead["group"] = {"count": len(members), "members": [{"id": m["id"], "items": list(m["items"])} for m in members]}
        lead["title"] = f"{lead['title']}  (and {len(members) - 1} more like it, about {lead['items'][0]})"
        lead["blocking"] = any(m["blocking"] for m in members)
        drop |= {id(m) for m in members[1:]}
    return [it for it in items if id(it) not in drop]


def group_members(project, item_id: str) -> list[dict]:
    """Every finding an item stands for: itself, or all the findings of its group (each {id, items})."""
    for it in collect(project, include_done=False):
        if it["id"] == item_id and it.get("group"):
            return list(it["group"]["members"])
    return []


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
    healed = sum(1 for it in everything if it["kind"] == "healed" and it["status"] == "healed")
    outdated = sum(1 for it in everything if it["status"] == "outdated")
    blocking = sum(it["blocking"] for it in items)
    flagged = [n for n in ("ledger", "acts", "chapters", "scenes") if project.state.layers[n].status in ("flagged", "failed")]
    empty_ledger = bool(ledger is not None and not ledger.events and project.state.layers["ledger"].status != "accepted")
    from .constants import REDO_NOTE
    redoing = any(project.state.layers[n].status == "pending" and project.state.layers[n].note == REDO_NOTE for n in ("acts", "chapters", "scenes"))  # reset, waiting to be planned again
    needs_run = blocking == 0 and bool(waiting or outdated or flagged or empty_ledger or redoing)  # a stage that failed, or an audit that is now answered, has to run again
    return {"open": len(items), "blocking": blocking, "answered_waiting": waiting, "resolved": resolved, "healed": healed, "outdated": outdated, "needs_run": needs_run,
            "by_stage": {s: sum(it["stage"] == s for it in items) for s in STAGES if any(it["stage"] == s for it in items)}}


def blocking_for_checkpoint(project, checkpoint: str) -> list[dict]:
    """The open items that approving this checkpoint as it is would skip."""
    stages = CHECKPOINT_STAGES.get(checkpoint, ())
    return [it for it in collect(project, include_done=False) if it["stage"] in stages and it["kind"] != "healed" and not it.get("warning")]  # a warning (a wording or rating finding) never has to be skipped


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
