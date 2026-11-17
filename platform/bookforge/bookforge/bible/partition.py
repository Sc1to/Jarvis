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

from .positions import act_id


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
        continued = c.get("events_continued") or c.get("continues") or []
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


def assign_scenes(raw: list, covered: list[str], continued: list[str]) -> list[str]:
    """The same cut for the scenes of one chapter: each scene names the event it STARTS with (`starts_with`, one of the chapter's own events); the
    tool fills in `events` (the chapter's events from that one up to the next scene's). A scene with no `starts_with` carries on what the scene before it
    tells and lists none; the first scene starts with the chapter's first event; an event the chapter only continues is the first scene's. Returns the
    problems to hand back to the model (a start the chapter does not own, or one that goes backwards). A reply with no `starts_with` at all is left as it is."""
    scenes = [s for s in raw if isinstance(s, dict)]
    if len(scenes) != len(raw) or not any("starts_with" in s for s in scenes):
        return []
    index = {x: i for i, x in enumerate(covered)}
    problems: list[str] = []
    starts: list[int | None] = []
    last_at = -1
    for k, sc in enumerate(scenes):
        label = f"scenes[{k}]"
        sw = sc.pop("starts_with", None)
        sc.pop("events", None)  # the tool's to fill in, whatever the model wrote
        if sw in (None, "", []):
            starts.append(None)
            continue
        sw = str(sw).strip()
        if sw not in index:
            problems.append(f"{label}.starts_with is '{sw}', which is not an event of this chapter. The chapter's events are, in order: {', '.join(covered) or 'none'}")
            starts.append(None)
            continue
        if index[sw] <= last_at:
            problems.append(f"{label}.starts_with is {sw}, but an earlier scene already starts at {covered[last_at]} or later: scenes start at later and later events, in order")
            starts.append(None)
            continue
        last_at = index[sw]
        starts.append(index[sw])
    if problems:
        return problems
    if covered and (starts[0] is None or starts[0] > 0):
        starts[0] = 0  # the chapter's first event is the first scene's
    for k, sc in enumerate(scenes):
        events: list[str] = []
        if starts[k] is not None:
            later = [x for x in starts[k + 1:] if x is not None]
            events = covered[starts[k]:later[0] if later else len(covered)]
        if k == 0:
            events = [x for x in continued if x not in events] + events
        sc["events"] = events
    return []


def assign_acts(raw: list, event_ids: list[str], ending_ids: list[str], book: str) -> tuple[list[str], list[str]]:
    """The same cut for the acts of the book: each act names the event it STARTS with (`starts_with`), the tool fills in `events` (the book's own events,
    in ledger order, from that one up to the next act's) and the act's id. The first act starts with the first event whatever was written, and an act that
    would start after the ending is pulled back so the resolution is always in the last act (an act left with no event of its own is merged into the one
    before). Returns (problems, notes): a problem is a start that is not an event or that goes backwards, and goes back to the model alone. What is
    derived from the events (turning point, chapter count, sizing) is `normalize.derive_act_numbers`. A reply with no `starts_with` is left as it is."""
    acts = [a for a in raw if isinstance(a, dict)]
    if len(acts) != len(raw) or not any("starts_with" in a for a in acts):
        return [], []
    index = {x: i for i, x in enumerate(event_ids)}
    problems: list[str] = []
    notes: list[str] = []
    starts: list[int] = []
    last_at = -1
    for k, a in enumerate(acts):
        label = f"acts[{k}]"
        sw = a.pop("starts_with", None)
        for key in ("events", "turning_point_event", "chapter_count", "sizing_reason"):
            a.pop(key, None)  # the tool's to fill in, whatever the model wrote
        a["id"] = act_id(book, k + 1)
        if sw in (None, "", []):
            problems.append(f"{label} needs `starts_with`: the id of the first event of the act")
            continue
        sw = str(sw).strip()
        if sw not in index:
            problems.append(f"{label}.starts_with is '{sw}', which is not an event of the book. The events are, in order: {', '.join(event_ids)}")
        elif index[sw] <= last_at:
            problems.append(f"{label}.starts_with is {sw}, but an earlier act already starts at {event_ids[last_at]} or later: acts start at later and later events, in order")
        else:
            last_at = index[sw]
            starts.append(index[sw])
    if problems:
        return problems, notes
    if starts[0] != 0:
        notes.append(f"the first act starts with {event_ids[0]}, the first event of the book (it named {event_ids[starts[0]]})")
        starts[0] = 0
    ends = [index[e] for e in ending_ids if e in index]
    while ends and len(starts) > 1 and starts[-1] > min(ends):
        if min(ends) > starts[-2]:
            notes.append(f"the last act starts with {event_ids[min(ends)]} so that it holds the resolution (it named {event_ids[starts[-1]]})")
            starts[-1] = min(ends)
            break
        notes.append(f"{act_id(book, len(starts))} would start after the resolution and is merged into the act before it")
        acts.pop()
        starts.pop()
    raw[:] = acts
    for k, a in enumerate(acts):
        a["events"] = event_ids[starts[k]:starts[k + 1] if k + 1 < len(starts) else len(event_ids)]
    return [], notes


def apply_continues(raw: list, weights: dict[str, int], previous_last: str | None, previous_continued: list[str] | None = None) -> tuple[list[str], list[str]]:
    """`continues: true` on a chapter means it carries on the heavy event the chapter before ended with: the tool fills in `events_continued` from that
    chapter's last event (for the first chapter of an act, `previous_last`, the last event of the act before). Only a weight 3 event not already carried
    on can continue; anything else goes back to the model as the one problem. Returns (problems, notes). A chapter with `events_continued` of its own is
    left as written (older replies)."""
    chapters = [c for c in raw if isinstance(c, dict)]
    problems: list[str] = []
    notes: list[str] = []
    for k, c in enumerate(chapters):
        flag = c.pop("continues", None)
        if not flag or c.get("events_continued"):
            continue
        if k > 0:
            prev = chapters[k - 1]
            last = (prev.get("events_covered") or prev.get("events_continued") or [None])[-1]
            carried = list(prev.get("events_continued") or [])
        else:
            last, carried = previous_last, list(previous_continued or [])
        if not last:
            problems.append(f"chapters[{k}] says it continues the chapter before, but there is none: remove `continues`")
        elif weights.get(last, 1) < 3 or last in carried:
            problems.append(f"chapters[{k}] says it continues the chapter before, but that chapter ends with {last}, which is not a heavy (weight 3) event "
                            "that began there: give this chapter its own `starts_with` instead of `continues`")
        else:
            c["events_continued"] = [last]
            notes.append(f"chapters[{k}] carries on {last} from the chapter before")
    return problems, notes
