"""One normalisation entry point per layer.

A model reply is put into its right shape here and nowhere else: what has exactly one right answer is derived (which events a chapter tells, from its
`starts_with`: bible/partition.py) or corrected (ids by position, events in ledger order, an event in two acts: bible/repair.py), and every correction is
noted for the "Fixed automatically" list (healing.py). The `parse_*` functions in bible/validate.py call these and then only validate content; they
no longer carry repair calls of their own.

What comes out is checked once more by the validators. A structural finding at that point is a bug of the tool, not something to ask the model or you
about (diagnostics.py).
"""

import logging

from .. import healing
from . import partition, repair
from .positions import parse_position

log = logging.getLogger("platform_bookforge.normalize")


def drop_empty_tail(raw: list) -> list:
    """Chapters at the end of an act that only repeat events earlier chapters of the act already tell, and continue nothing: the act's events ran
    out and the model filled the ceiling. Nothing new is lost by leaving them out, so they are dropped instead of failing the act."""
    items = list(raw)
    while len(items) > 1:
        last = items[-1]
        if not isinstance(last, dict) or last.get("events_continued"):
            break
        covered = last.get("events_covered")
        told = {e for c in items[:-1] if isinstance(c, dict) for e in (c.get("events_covered") or []) if isinstance(e, str)}
        if not isinstance(covered, list) or not covered or not all(isinstance(e, str) and e in told for e in covered):
            break
        items.pop()
    return items


def _note(project, layer: str, key: str, notes: list[str]) -> None:
    for note in notes:
        log.info("%s %s: %s", layer, key, note)
    healing.note(project, layer, key, notes)


def derive_act_numbers(raw: list, ledger, weight_per_chapter: float) -> None:
    """What follows from an act's events, written by the tool (the model never states it, so it cannot disagree with the ledger):
    `chapter_count` from the ledger's weights (about one chapter per `weight_per_chapter`, the total as the ledger's own estimate, shared out by largest
    remainder and never above what the act's events can supply), `sizing_reason` as the computed note, and `turning_point_event`: the act's last event;
    for the last act the central decision when it sits in the second half of the act, else the resolution."""
    from ..validators import ledger as ledger_checks

    plain = [e.model_dump() for e in ledger.events]
    acts = [a for a in raw if isinstance(a, dict)]
    if not acts:
        return
    weights = [ledger_checks.act_weight(a, plain)[0] for a in acts]
    exact = [w / weight_per_chapter for w in weights]
    target = max(len(acts), round(sum(exact)))
    counts = [max(1, int(x)) for x in exact]
    left = target - sum(counts)
    for i in sorted(range(len(counts)), key=lambda i: -(exact[i] - int(exact[i]))):
        if left <= 0:
            break
        counts[i] += 1
        left -= 1
    decisions = [e.id for e in ledger.events if getattr(e, "decision", False)]
    endings = [e.id for e in ledger.events if getattr(e, "ending", False)]
    for k, a in enumerate(acts):
        a["chapter_count"] = max(1, min(counts[k], ledger_checks.act_capacity(a, plain)[0]))
        a["sizing_reason"] = ledger_checks.sizing_note(a, plain, weight_per_chapter)
        mine = a.get("events") or []
        tp = mine[-1] if mine else ""
        if k == len(acts) - 1 and mine:
            late = [x for x in mine if x in decisions and mine.index(x) >= (len(mine) - 1) / 2]
            tp = late[-1] if late else next((x for x in reversed(mine) if x in endings), mine[-1])
        a["turning_point_event"] = tp


def normalize_acts(project, raw: list, ledger) -> tuple[list[str], list[str]]:
    """(notes, problems). With `starts_with` the tool cuts the book's events into acts and derives the rest (ids, events, turning point, chapter count,
    sizing: `bible/partition.py::assign_acts`, `derive_act_numbers`); a bad start is the only problem and goes back to the model alone. Without it (an
    older file) each act's events in ledger order, an event in two acts kept in the first, an event in no act given to its neighbours' act."""
    if ledger is None or not raw:
        return [], []
    own = [e for e in ledger.events if not e.carried_in and e.source != "derived"]
    new_shape = any(isinstance(a, dict) and "starts_with" in a for a in raw)
    problems, notes = partition.assign_acts(raw, [e.id for e in own], [e.id for e in own if e.ending], project.book)
    if problems:
        return [], problems
    if new_shape:
        derive_act_numbers(raw, ledger, project.config.ledger.weight_per_chapter)
    else:
        notes += repair.repair_acts(raw, [e.model_dump() for e in ledger.events])
    _note(project, "acts", "acts", notes)
    return notes, []


def normalize_chapters(project, data, raw: list, act, ledger, first_number: int) -> tuple[list, list[str], list[str]]:
    """(chapters, notes, problems). `problems` is only ever about `starts_with` (a start the act does not own, or one that goes backwards): that is the
    model's pick and goes back to it alone. With no ledger the reply is left as it is."""
    if ledger is None:
        return raw, [], []
    declared = data.get("derived_events") if isinstance(data, dict) else None
    problems = partition.assign(raw, partition.act_order(ledger.events, act.events, declared if isinstance(declared, list) else None))  # events cut at each starts_with
    if problems:
        return raw, [], problems
    mine = list(act.events) + [e.id for e in ledger.events if e.parent and e.parent in act.events]
    notes = repair.repair_chapters(raw, data.get("tracks") if isinstance(data, dict) else None, [e.model_dump() for e in ledger.events], mine, project.book, first_number)
    _note(project, "chapters", act.id, notes)
    return drop_empty_tail(raw), notes, []


def normalize_scenes(project, data, raw: list, chapter, ledger) -> tuple[list[str], list[str]]:
    """(notes, problems). The tool cuts the chapter's events at each scene's `starts_with` (a bad start is the only problem, and goes back to the model
    alone), then scene ids by position, an event another chapter tells taken out, one shown twice kept once, one shown nowhere added."""
    if ledger is None or not raw:
        return [], []
    problems = partition.assign_scenes(raw, list(chapter.events_covered), list(chapter.events_continued))
    if problems:
        return [], problems
    notes = repair.repair_scenes(raw, data.get("tracks") if isinstance(data, dict) else None, list(chapter.events_covered),
                                 list(chapter.events_covered) + list(chapter.events_continued), [e.model_dump() for e in ledger.events], project.book,
                                 parse_position(chapter.id).chapter)
    _note(project, "scenes", chapter.id, notes)
    return notes, []


def derive_days(raw: list, prev_day: int | None) -> None:
    """Story days by construction: a scene says how many days after the one before it happens (`days_later`, 0 for the same day), the tool adds them up.
    Only a flashback gives an absolute `day`. A scene that gives neither is on the same day. A reply that still gives absolute days is left as it is."""
    day = prev_day
    for item in raw:
        if not isinstance(item, dict):
            continue
        if item.get("flashback"):
            continue  # runs backwards on purpose: its own absolute day (checked as before), and the main line goes on from where it was
        if "days_later" in item:
            try:
                later = max(0, int(item.pop("days_later")))
            except (TypeError, ValueError):
                later = 0
            item["day"] = (day if day is not None else 1) + later
        elif item.get("day") in (None, ""):
            item["day"] = day if day is not None else 1
        try:
            day = int(item["day"])
        except (TypeError, ValueError):
            pass


def first_sentence(text: str, limit: int = 220) -> str:
    text = " ".join(str(text).split())
    for stop in (". ", "; ", "! ", "? "):
        if stop in text:
            text = text.split(stop)[0]
            break
    return text.rstrip(".") [:limit]


def attach_return_causes(tracks: list, scenes: list, chapters: list) -> list[str]:
    """A state that goes back to an earlier value (breached, hardened, breached again) is the story, and its cause is the scene that changes it: the tool
    writes that scene's purpose (its first sentence) as the entry's `cause`, so the track never has to ask you. Returns one note per cause written."""
    from ..validators import state as state_checks

    purposes = {s.id: s.purpose for s in scenes}
    purposes.update({c.id: c.purpose for c in chapters})
    notes: list[str] = []
    for t in tracks:
        plan = sorted(t.plan, key=lambda e: state_checks._pos(str(e.from_)))
        as_dicts = [{"value": e.value, "cause": e.cause, "from": e.from_} for e in plan]
        for k, _ in state_checks.returns(as_dicts):
            why = first_sentence(purposes.get(str(plan[k].from_), ""))
            if why:
                plan[k].cause = why
                notes.append(f"track {t.id} returns to an earlier state at {plan[k].from_}; its cause is the scene's purpose: {why}")
    return notes
