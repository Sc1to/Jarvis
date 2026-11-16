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


def normalize_acts(project, raw: list, ledger) -> list[str]:
    """Each act's events in ledger order, an event in two acts kept in the first, an event in no act given to its neighbours' act."""
    if ledger is None or not raw:
        return []
    notes = repair.repair_acts(raw, [e.model_dump() for e in ledger.events])
    _note(project, "acts", "acts", notes)
    return notes


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


def normalize_scenes(project, data, raw: list, chapter, ledger) -> list[str]:
    """Scene ids by position, events another chapter tells taken out, an event shown twice kept once, one shown nowhere added."""
    if ledger is None or not raw:
        return []
    notes = repair.repair_scenes(raw, data.get("tracks") if isinstance(data, dict) else None, list(chapter.events_covered),
                                 list(chapter.events_covered) + list(chapter.events_continued), [e.model_dump() for e in ledger.events], project.book,
                                 parse_position(chapter.id).chapter)
    _note(project, "scenes", chapter.id, notes)
    return notes
