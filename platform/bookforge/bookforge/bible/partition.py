"""Chapters are stretches of the act's events: the tool works out which events each chapter tells, the model only says where each chapter starts.

The model used to write `events_covered` for every chapter and the tool then checked that list against the ledger: an event in no chapter, in two,
in the wrong act, out of order. Each slip needed its own check and its own repair. Now the model names the event each chapter starts with
(`starts_with`) and the tool cuts the act's events, in ledger order, at those points. A chapter tells everything from its starting event up to (not
including) the next chapter's; the last one runs to the act's last event. What used to go wrong cannot be written down any more:

- every event of the act is told, because the stretches cover the whole list;
- none is told twice, because the stretches do not overlap;
- none comes from another act, because only events of this act can start a chapter;
- the order is the ledger's, because the stretches are cut from the ledger's list.

A chapter that only carries on a heavy event from the chapter before (`events_continued`, nothing new) has no `starts_with`. A reply with no `starts_with` at all (an older file, a hand-edited one) is taken as it is, with the old checks; one that has both is read by its `starts_with`.
"""

import re


def act_order(ledger_events, act_events, declared: list | None = None) -> list[str]:
    """The ids a chapter of this act may start with, in ledger order: the act's events, their derived complications already in the ledger, and the
    complications this reply declares (each right after its parent)."""
    own = set(act_events)
    order = [e.id for e in ledger_events if e.id in own or (getattr(e, "parent", None) and e.parent in own)]
    for d in declared or []:
        if not isinstance(d, dict) or not isinstance(d.get("id"), str) or d.get("parent") not in own or d["id"] in order:
            continue
        parent = d["parent"]
        last = max(i for i, x in enumerate(order) if x == parent or x.startswith(parent + ".")) if any(x == parent or x.startswith(parent + ".") for x in order) else len(order) - 1
        order.insert(last + 1, d["id"])
    return order


def uses_starts(chapters: list[dict]) -> bool:
    """The reply is in the new shape as soon as one chapter has `starts_with`. A reply that has both (a correction round that was told to list events)
    is read by its `starts_with` alone: `events_covered` is the tool's to fill in."""
    return bool(chapters) and any("starts_with" in c for c in chapters)


def assign(raw: list, order: list[str]) -> list[str]:
    """Fill `events_covered` of each chapter of the reply from its `starts_with`. Returns the problems to hand back to the model (empty when fine)."""
    chapters = [c for c in raw if isinstance(c, dict)]
    if len(chapters) != len(raw) or not uses_starts(chapters):
        return []
    index = {x: i for i, x in enumerate(order)}
    problems: list[str] = []
    starts: list[int | None] = []
    last_at = -1
    for k, c in enumerate(chapters):
        label = f"chapters[{k}]"
        sw = c.pop("starts_with", None)
        c.pop("events_covered", None)  # the tool's to fill in, whatever the model wrote
        continued = c.get("events_continued") or []
        if sw in (None, "", []):
            if not continued:
                problems.append(f"{label} has neither `starts_with` (the first event it tells) nor `events_continued`: every chapter has an event of its own")
            starts.append(None)
            continue
        sw = str(sw).strip()
        if sw not in index:
            problems.append(f"{label}.starts_with is '{sw}', which is not an event of this act. The events are, in order: {', '.join(order)}")
            starts.append(None)
            continue
        at = index[sw]
        if at <= last_at:
            problems.append(f"{label}.starts_with is {sw}, but an earlier chapter already starts at {order[last_at]} or later: chapters start at later and later events, "
                            "in ledger order (a heavy event continues in the next chapter through `events_continued`, not by starting there again)")
            starts.append(None)
            continue
        last_at = at
        starts.append(at)
    if problems:
        return problems
    real = [s for s in starts if s is not None]
    if not real:
        return ["no chapter starts with an event: give each chapter a `starts_with`"]
    if starts[0] is not None and starts[0] > 0:
        starts[0] = 0  # the events before the first chapter's start are its too: the act begins at its first event
    for k, c in enumerate(chapters):
        if starts[k] is None:
            c["events_covered"] = []
            continue
        later = [s for s in starts[k + 1:] if s is not None]
        end = later[0] if later else len(order)
        c["events_covered"] = order[starts[k]:end]
    return []
