"""Mechanical slips in a model's plan, put right instead of asked about.

A model asked to assign ledger events to acts and chapters often gets the bookkeeping slightly wrong while the story it plans is fine: two neighbouring
chapters swapped, an event listed but left out of every chapter, the events of a chapter written in the wrong order, an id that is the wrong number. Each
of those has one right answer that follows from what the ledger says, so it is corrected here, before the checks, and reported as a note. What needs
judgement (an event that fits nowhere, an order that cannot be put right without splitting a chapter) is left alone for the checks to report.

All functions work on the raw dicts of a parsed reply and change them in place; each returns the notes on what it did.
"""

import re

from ..validators.text import content_stems
from .positions import chapter_id


def _order(events: list[dict]) -> dict[str, int]:
    return {e["id"]: i for i, e in enumerate(events) if isinstance(e, dict) and e.get("id")}


def _words(text: str) -> set[str]:
    return set(content_stems(text))


# ── the ledger ──────────────────────────────────────────────────────────────

def repair_event_order(raw_events: list) -> list[str]:
    """Events listed before an event they must follow (`after`) are moved after it: a stable topological sort that keeps the model's order wherever it was
    already right. A cycle, or a flashback (told out of story order on purpose), is left alone."""
    events = [e for e in raw_events if isinstance(e, dict) and e.get("id")]
    if len(events) != len(raw_events):
        return []
    pos = {e["id"]: i for i, e in enumerate(events)}
    flashback = {e["id"] for e in events if e.get("kind") == "flashback"}
    deps = {e["id"]: [a for a in (e.get("after") or []) if a in pos and a != e["id"] and a not in flashback and e["id"] not in flashback] for e in events}
    if all(pos[a] < pos[i] for i, d in deps.items() for a in d):
        return []
    placed: list[str] = []
    done: set[str] = set()
    left = [e["id"] for e in events]
    while left:
        nxt = next((i for i in left if all(a in done for a in deps[i])), None)
        if nxt is None:
            return []  # events wait on each other: not a slip, the check reports the cycle
        placed.append(nxt)
        done.add(nxt)
        left.remove(nxt)
    by_id = {e["id"]: e for e in events}
    changed = [i for k, i in enumerate(placed) if i != events[k]["id"]]
    raw_events[:] = [by_id[i] for i in placed]
    return [f"events put in the order they must happen ({len(changed)} moved: {', '.join(changed[:6])})"]


# ── the acts ────────────────────────────────────────────────────────────────

def repair_acts(raw_acts: list, ledger_events: list[dict]) -> list[str]:
    """Each act's events in ledger order, an event given to two acts kept in the first, and an event in no act given to the act its neighbours in the
    ledger belong to (between two acts: the one whose summary shares most words with it, else the earlier). Acts that interleave are left for the check."""
    order = _order([e for e in ledger_events if not e.get("carried_in") and e.get("source", "synopsis") != "derived"])
    acts = [a for a in raw_acts if isinstance(a, dict)]
    if not acts or len(acts) != len(raw_acts) or not order:
        return []
    notes: list[str] = []
    seen: set[str] = set()
    for a in acts:
        mine = []
        for x in a.get("events") or []:
            if x not in order:
                mine.append(x)  # unknown to the ledger: the check says so
            elif x in seen:
                notes.append(f"{x} was in two acts; kept in the first")
            else:
                seen.add(x)
                mine.append(x)
        a["events"] = sorted(mine, key=lambda x: order.get(x, 10 ** 6))
    owner = {x: i for i, a in enumerate(acts) for x in a["events"]}
    texts = {e["id"]: e.get("text", "") for e in ledger_events}
    ids = list(order)
    for k, x in enumerate(ids):
        if x in owner:
            continue
        prev = next((owner[y] for y in reversed(ids[:k]) if y in owner), None)
        nxt = next((owner[y] for y in ids[k + 1:] if y in owner), None)
        if prev is None and nxt is None:
            continue
        if prev is None or nxt is None or prev == nxt:
            target = nxt if prev is None else prev
        else:
            w = _words(texts.get(x, ""))
            score = lambda i: len(w & _words(f"{acts[i].get('summary', '')} {acts[i].get('purpose', '')}"))  # noqa: E731
            target = nxt if score(nxt) > score(prev) else prev
        acts[target]["events"] = sorted(acts[target]["events"] + [x], key=lambda y: order.get(y, 10 ** 6))
        owner[x] = target
        notes.append(f"{x} was in no act; it belongs to {acts[target].get('id', 'act ' + str(target + 1))}, where its neighbours in the ledger are")
    return notes


# ── the chapters of one act ─────────────────────────────────────────────────

def _remap(value, mapping: dict[str, str]):
    """A chapter or scene id (or a position like b2.ch11.s2) rewritten through the chapter-id mapping."""
    if not isinstance(value, str):
        return value
    for old, new in mapping.items():
        if value == old or value.startswith(old + "."):
            return new + value[len(old):]
    return value


def _remap_tracks(raw_tracks, mapping: dict[str, str]) -> None:
    for t in raw_tracks or []:
        if isinstance(t, dict):
            for entry in t.get("plan") or []:
                if isinstance(entry, dict) and "from" in entry:
                    entry["from"] = _remap(entry["from"], mapping)


def repair_chapters(raw: list, raw_tracks: list | None, ledger_events: list[dict], act_events: list[str], book: str, first: int) -> list[str]:
    """For the chapters of one act: ids that are the wrong number become the right one (tracks follow); each chapter's events in ledger order; chapters that
    are in the wrong order swapped back when their events do not overlap; an act event no chapter lists attached to the chapter next to it in the ledger.
    Anything that would need a chapter split or merged is left for the checks."""
    chapters = [c for c in raw if isinstance(c, dict)]
    if not chapters or len(chapters) != len(raw):
        return []
    order = _order(ledger_events)
    notes: list[str] = []
    expected = [chapter_id(book, first + i) for i in range(len(chapters))]
    mapping = {str(c["id"]): expected[i] for i, c in enumerate(chapters) if c.get("id") and str(c["id"]) != expected[i]}
    for i, c in enumerate(chapters):
        if mapping.get(str(c.get("id"))):
            notes.append(f"chapter {c['id']} is numbered {expected[i]} (by its place in the act)")
        c["id"] = expected[i]
    if mapping:
        _remap_tracks(raw_tracks, mapping)
    for c in chapters:
        covered = [x for x in c.get("events_covered") or [] if isinstance(x, str)]
        ordered = sorted(covered, key=lambda x: order.get(x, 10 ** 6))
        if ordered != covered:
            c["events_covered"] = ordered
            notes.append(f"{c['id']}: its events put in the order they happen ({', '.join(ordered)})")
    if not any(c.get("events_continued") for c in chapters):
        notes += _swap_chapters(chapters, raw_tracks, order, expected)
        raw[:] = chapters  # the reply's own list, in the new order
    notes += _attach_uncovered(chapters, act_events, ledger_events, order)
    return notes


def _swap_chapters(chapters: list[dict], raw_tracks, order: dict[str, int], expected: list[str]) -> list[str]:
    spans = []
    for c in chapters:
        idx = [order[x] for x in c.get("events_covered") or [] if x in order]
        if not idx:
            return []
        spans.append((min(idx), max(idx)))
    ranked = sorted(range(len(chapters)), key=lambda i: spans[i][0])
    if ranked == list(range(len(chapters))):
        return []
    if any(spans[ranked[k]][1] >= spans[ranked[k + 1]][0] for k in range(len(ranked) - 1)):
        return []  # events interleave: swapping chapters would split one, which takes judgement
    mapping = {expected[old]: expected[new] for new, old in enumerate(ranked) if old != new}
    chapters_before = list(chapters)
    chapters[:] = [chapters_before[old] for old in ranked]
    for new, c in enumerate(chapters):
        c["id"] = expected[new]
    _remap_tracks(raw_tracks, mapping)
    return [f"chapters put in story order: {', '.join(f'{o} is now {n}' for o, n in mapping.items())}"]


def _attach_uncovered(chapters: list[dict], act_events: list[str], ledger_events: list[dict], order: dict[str, int]) -> list[str]:
    told = {x for c in chapters for x in (c.get("events_covered") or []) + (c.get("events_continued") or [])}
    texts = {e["id"]: e.get("text", "") for e in ledger_events}
    notes = []
    for x in sorted((x for x in act_events if x in order and x not in told), key=lambda y: order[y]):
        owner = {y: i for i, c in enumerate(chapters) for y in c.get("events_covered") or [] if y in order}
        before = next((owner[y] for y in sorted(owner, key=lambda y: -order[y]) if order[y] < order[x]), None)
        after = next((owner[y] for y in sorted(owner, key=lambda y: order[y]) if order[y] > order[x]), None)
        if before is None and after is None:
            continue
        if before is None or after is None or before == after:
            target = after if before is None else before
        else:
            w = _words(texts.get(x, ""))
            text = lambda i: " ".join(str(chapters[i].get(k, "")) for k in ("title", "purpose", "summary", "end_state"))  # noqa: E731
            target = after if len(w & _words(text(after))) > len(w & _words(text(before))) else before
        c = chapters[target]
        c["events_covered"] = sorted((c.get("events_covered") or []) + [x], key=lambda y: order.get(y, 10 ** 6))
        notes.append(f"{x} was in no chapter; it is told in {c['id']}, next to its neighbours in the ledger")
        told.add(x)
    return notes


# ── the ledger, once more ───────────────────────────────────────────────────

def repair_unknown_after(raw_events: list) -> list[str]:
    """An `after` that names an event the ledger does not have (a typo, an id the model invented) is dropped: it cannot be a real dependency."""
    ids = {e.get("id") for e in raw_events if isinstance(e, dict)}
    notes = []
    for e in raw_events:
        if isinstance(e, dict) and isinstance(e.get("after"), list):
            unknown = [a for a in e["after"] if a not in ids]
            if unknown:
                e["after"] = [a for a in e["after"] if a in ids]
                notes.append(f"{e.get('id')}: 'after' named {', '.join(map(str, unknown))}, which is not an event; dropped")
    return notes


# ── the scenes of one chapter ───────────────────────────────────────────────

def repair_scenes(raw: list, raw_tracks: list | None, begun: list[str], allowed: list[str], ledger_events: list[dict], book: str, chapter_number: int) -> list[str]:
    """For the scenes of one chapter: ids that are the wrong number become the right one (tracks follow); an event another chapter tells is taken out of a
    scene that lists it; an event of this chapter shown in two scenes is kept in the scene whose words fit it best; one shown in none is added to the scene
    whose words fit it best (else the scene at its place among the chapter's events). What no scene says (an end_state) is for the checks."""
    from .positions import scene_id
    scenes = [s for s in raw if isinstance(s, dict)]
    if not scenes or len(scenes) != len(raw):
        return []
    notes: list[str] = []
    expected = [scene_id(book, chapter_number, i + 1) for i in range(len(scenes))]
    mapping = {str(s["id"]): expected[i] for i, s in enumerate(scenes) if s.get("id") and str(s["id"]) != expected[i]}
    for i, s in enumerate(scenes):
        if str(s.get("id")) in mapping:
            notes.append(f"scene {s['id']} is numbered {expected[i]} (by its place in the chapter)")
        s["id"] = expected[i]
    if mapping:
        for t in raw_tracks or []:
            if isinstance(t, dict):
                for entry in t.get("plan") or []:
                    if isinstance(entry, dict) and isinstance(entry.get("from"), str) and entry["from"] in mapping:
                        entry["from"] = mapping[entry["from"]]
    allowed_set = set(allowed)
    for s in scenes:
        foreign = [x for x in s.get("events") or [] if x not in allowed_set]
        if foreign:
            s["events"] = [x for x in s["events"] if x in allowed_set]
            notes.append(f"{s['id']} listed {', '.join(foreign)}, which {chapter_id(book, chapter_number)} does not tell; taken out")
    texts = {e["id"]: e.get("text", "") for e in ledger_events}
    fit = lambda s, x: len(_words(texts.get(x, "")) & _words(" ".join([str(s.get("purpose", ""))] + [str(b) for b in s.get("beats") or []])))  # noqa: E731
    for k, x in enumerate(begun):
        holders = [s for s in scenes if x in (s.get("events") or [])]
        if len(holders) > 1:
            keep = max(holders, key=lambda s: fit(s, x))
            for s in holders:
                if s is not keep:
                    s["events"] = [y for y in s["events"] if y != x]
            notes.append(f"{x} was shown in {len(holders)} scenes; kept in {keep['id']}, where it fits best")
        elif not holders:
            best = max(scenes, key=lambda s: fit(s, x))
            if fit(best, x) == 0:
                best = scenes[min(len(scenes) - 1, k * len(scenes) // max(1, len(begun)))]
            best["events"] = list(best.get("events") or []) + [x]
            notes.append(f"{x} was shown in no scene; it is shown in {best['id']}, where it fits")
    return notes
