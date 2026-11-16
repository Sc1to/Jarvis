"""A chapter that reports the outcome of an event a later chapter tells is corrected in its wording, once, instead of being sent back to you.

The whole-book check finds a chapter whose summary or end_state says an event's outcome is already done (a chapter about deciding to do something
that ends with it done), and a model has confirmed it (qc/repeat_confirm.py). Planning the whole act again tends to repeat the slip, and the fix is
small: the chapter's own summary and end_state are rewritten, nothing else. The rewrite is kept only if the check no longer finds the overreach in
that chapter. A chapter that cannot be fixed this way stays a finding.
"""

import logging

from ..ask import word_count
from ..validators import HARD
from ..validators import state_claims
from .support import ask_json

log = logging.getLogger("platform_bookforge.qc")
MAX_FIXES = 8


def _check(original: tuple[str, str]):
    def check(data: dict) -> list[str]:
        s, e = data.get("summary"), data.get("end_state")
        if not isinstance(s, str) or not isinstance(e, str) or not s.strip() or not e.strip():
            return ['the reply must be {"summary": "...", "end_state": "..."}, both non-empty']
        out = []
        for name, new, old in (("summary", s, original[0]), ("end_state", e, original[1])):
            n, n_old = word_count(new), max(1, word_count(old))
            if n < 0.4 * n_old or n > 2.0 * n_old + 10:
                out.append(f"the {name} has {n} words; keep it close to the original {n_old}")
        return out
    return check


def fix(ctx, chapters: list, events: list[dict], findings: list) -> list[str]:
    """Rewrite the summary and end_state of each chapter a confirmed hard end_state_overreach points to. Returns one note per chapter fixed."""
    project = ctx.project
    if ctx.llm is None or not project.config.qc.fix_overreach:
        return []
    by_id = {c.id: c for c in chapters}
    by_event = {e["id"]: e for e in events}
    notes: list[str] = []
    done: set[str] = set()
    for f in findings[:MAX_FIXES]:
        if f.severity != HARD or f.accepted or f.code != "end_state_overreach" or len(f.items) < 2:
            continue
        cid, ev_id = f.items[0], f.items[1]
        ch, ev = by_id.get(cid), by_event.get(ev_id)
        if ch is None or ev is None or cid in done:
            continue
        old = (ch.summary, ch.end_state)
        claim = next((t for t in f.evidence if t.startswith("chapter:")), "")[len("chapter:"):].strip()
        try:
            data = ask_json(ctx, f"fix overreach {cid}", project.config.layers["chapters"].model, "overreach_fix", _check(old), max_tokens=900,
                            title=ch.title, summary=ch.summary, end_state=ch.end_state, event=f"{ev_id}: {ev['text']}", quote=claim)
        except Exception as e:  # no rewrite is no change: the finding stays
            log.info("%s: overreach not fixed (%s)", cid, e)
            continue
        ch.summary, ch.end_state = data["summary"].strip(), data["end_state"].strip()
        still = [x for x in state_claims.end_state_overreach([c.model_dump() for c in chapters], events) if x.items[:2] == [cid, ev_id]]
        if still:
            ch.summary, ch.end_state = old  # the rewrite did not take the claim out: the saved wording stands
            log.info("%s: overreach not fixed (the check still finds it)", cid)
            continue
        done.add(cid)
        notes.append(f"{cid}: its summary and end_state reported the outcome of {ev_id}, which a later chapter tells; the wording was rewritten and the check passes")
    return notes
