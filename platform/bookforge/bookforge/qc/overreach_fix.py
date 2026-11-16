"""A chapter whose own wording is wrong in a way one narrow call can fix is corrected in that wording, once, instead of being sent back to you.

Two cases: a chapter that reports the outcome of an event a later chapter tells (`fix`), and a chapter whose purpose and summary retell an event an earlier
chapter already told (`fix_retells`, below).

The first case:

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


def _check_retell(original: tuple[str, str]):
    def check(data: dict) -> list[str]:
        p, s = data.get("purpose"), data.get("summary")
        if not isinstance(p, str) or not isinstance(s, str) or not p.strip() or not s.strip():
            return ['the reply must be {"purpose": "...", "summary": "..."}, both non-empty']
        out = []
        for name, new, old in (("purpose", p, original[0]), ("summary", s, original[1])):
            n, n_old = word_count(new), max(1, word_count(old))
            if n < 0.4 * n_old or n > 2.0 * n_old + 10:
                out.append(f"the {name} has {n} words; keep it close to the original {n_old}")
        return out
    return check


def fix_retells(ctx, chapters: list, events: list[dict], findings: list) -> list[str]:
    """Rewrite the purpose and summary of each chapter a hard chapter_retells_event points to, so it describes only its own events. Kept only if the
    check then no longer finds that retelling (and nothing else changes). Returns one note per chapter fixed."""
    from ..validators import ledger as ledger_checks

    project = ctx.project
    if ctx.llm is None or not project.config.qc.fix_retells:
        return []
    by_id = {c.id: c for c in chapters}
    by_event = {e["id"]: e for e in events}
    notes: list[str] = []
    for f in findings[:MAX_FIXES]:
        if f.severity != HARD or f.accepted or f.code != "chapter_retells_event" or len(f.items) < 2:
            continue
        cid, ev_id = f.items[0], f.items[1]
        ch, ev = by_id.get(cid), by_event.get(ev_id)
        if ch is None or ev is None:
            continue
        told_in = next((c.id for c in chapters if ev_id in c.events_covered and c.id != cid), "an earlier chapter")
        own = [by_event[x] for x in list(ch.events_covered) + list(ch.events_continued) if x in by_event]
        if not own:
            continue  # a chapter with no events of its own cannot be rewritten into one: that takes judgement
        old = (ch.purpose, ch.summary)
        try:
            data = ask_json(ctx, f"fix retold event {cid}", project.config.layers["chapters"].model, "retell_fix", _check_retell(old), max_tokens=900,
                            title=ch.title, purpose=ch.purpose, summary=ch.summary, own_events="\n".join(f"- {e['id']}: {e['text']}" for e in own),
                            forbidden=f"{ev_id}: {ev['text']}", told_in=told_in)
        except Exception as e:  # no rewrite is no change: the finding stays
            log.info("%s: retold event not fixed (%s)", cid, e)
            continue
        ch.purpose, ch.summary = data["purpose"].strip(), data["summary"].strip()
        still = [x for x in ledger_checks.check_chapter_texts([c.model_dump() for c in chapters], events)
                 if x.code == "chapter_retells_event" and x.severity == HARD and x.items[:2] == [cid, ev_id]]
        if still:
            ch.purpose, ch.summary = old  # the rewrite still retells it: the saved wording stands
            log.info("%s: retold event not fixed (the check still finds it)", cid)
            continue
        notes.append(f"{cid}: its purpose and summary retold {ev_id}, which {told_in} already tells; the wording was rewritten and the check passes")
    return notes


def _check_tension(ids: list[str]):
    def check(data: dict) -> list[str]:
        t = data.get("tension")
        if not isinstance(t, dict):
            return ['the reply must be {"tension": {"<chapter id>": <1-10>, ...}}']
        out = [f"{i} has no tension value" for i in ids if i not in t]
        out += [f"{i}: tension must be a whole number from 1 to 10" for i in ids if i in t and not (isinstance(t[i], int) and not isinstance(t[i], bool) and 1 <= t[i] <= 10)]
        return out
    return check


def fix_tension(ctx, chapters: list, findings: list) -> list[str]:
    """Rate the tension of each flat stretch of chapters again, from what happens in them (one narrow call per stretch); kept only if the check then no
    longer finds that stretch flat. Tension is a number the planning model wrote down, not part of the story's facts."""
    from ..validators import tension as tension_checks

    project = ctx.project
    if ctx.llm is None or not project.config.qc.fix_tension:
        return []
    notes: list[str] = []
    for f in findings[:4]:
        if f.severity != HARD or f.accepted or f.code != "flat_tension" or not f.items:
            continue
        ids = list(f.items)
        index = {c.id: i for i, c in enumerate(chapters)}
        picked = [chapters[index[x]] for x in ids if x in index]
        if len(picked) != len(ids):
            continue
        lo, hi = index[ids[0]], index[ids[-1]]
        around = [c for c in chapters[max(0, lo - 2):lo] + chapters[hi + 1:hi + 3]]
        old = {c.id: c.tension for c in picked}
        block = "\n".join(f"- {c.id} \"{c.title}\" (now {c.tension}): {c.purpose} {c.summary} End: {c.end_state}" for c in picked)
        near = "\n".join(f"- {c.id} \"{c.title}\" (tension {c.tension}): {c.summary[:240]}" for c in around) or "none"
        try:
            data = ask_json(ctx, f"fix flat tension {ids[0]}", project.config.layers["chapters"].model, "tension_fix", _check_tension(ids), max_tokens=500, chapters=block, around=near)
        except Exception as e:  # no new ratings is no change: the finding stays
            log.info("%s: flat tension not fixed (%s)", ids[0], e)
            continue
        values = data["tension"]
        if max(values[i] for i in ids) - min(values[i] for i in ids) < 3:
            log.info("%s: flat tension not fixed (the new ratings are still flat)", ids[0])
            continue
        for c in picked:
            c.tension = int(values[c.id])
        still = [x for x in tension_checks.flat_stretches([c.model_dump() for c in chapters]) if x.severity == HARD and set(x.items) & set(ids)]
        if still:
            for c in picked:
                c.tension = old[c.id]  # the new ratings are still a flat stretch: the saved ones stand
            log.info("%s: flat tension not fixed (the check still finds it)", ids[0])
            continue
        notes.append(f"{ids[0]} to {ids[-1]}: the tension stayed between {min(old.values())} and {max(old.values())}; it was rated again from what happens in each chapter and the check passes")
    return notes


UNFIXABLE_WARNINGS = ("end_state_overreach", "flat_tension")  # wording and rating heuristics: a warning when one narrow fix did not clear them, not a stop for the whole book


def demote_unfixable(findings: list) -> list:
    """After the fixes were tried: a hard finding of these kinds that is still there becomes a soft one that says so (it stays in the stage checks, but the
    run goes on). A retold event stays hard: it is a concrete defect in the plan."""
    from dataclasses import replace

    from ..validators import SOFT

    out = []
    for f in findings:
        if f.severity == HARD and not f.accepted and f.code in UNFIXABLE_WARNINGS:
            out.append(replace(f, severity=SOFT, message=f"(the tool tried to fix this and could not; kept as a warning) {f.message}"))
        else:
            out.append(f)
    return out
