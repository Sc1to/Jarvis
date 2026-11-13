"""State checks: tracks that flip back, people in two places, story days running backwards."""

import re
from collections import defaultdict

from ..bible.positions import parse_position
from .findings import Finding, hard, soft
from .text import content_stems, dice


def _pos(text: str):
    try:
        return parse_position(text).key
    except ValueError:
        return (0, 0)


def track_regressions(tracks: list[dict], stage: str = "state") -> list[Finding]:
    """A track returns to an earlier value (A, B, A) without an entry that says what caused the return (`cause:`)."""
    out: list[Finding] = []
    for t in tracks:
        plan = sorted(t.get("plan", []) or [], key=lambda e: _pos(str(e.get("from", e.get("from_", "")))))
        stems = [set(content_stems(str(e.get("value", "")))) for e in plan]
        for k in range(2, len(plan)):
            if plan[k].get("cause"):
                continue
            for j in range(k - 1):  # an earlier entry that is not the one just before
                if stems[k] and dice(stems[k], stems[j]) >= 0.75 and dice(stems[k], stems[k - 1]) < 0.75:
                    a, b = plan[j], plan[k]
                    out.append(hard(stage, "state_regression",
                                    f"track {t['id']} goes back to an earlier state at {b.get('from', b.get('from_'))} ('{b['value'][:70]}') "
                                    f"after changing at {plan[k - 1].get('from', plan[k - 1].get('from_'))}: say what caused the return (cause:) or keep the later state",
                                    [t["id"], str(b.get("from", b.get("from_")))], [str(a["value"])[:100], str(plan[k - 1]["value"])[:100]]))
                    break
    return out


def location_conflicts(scenes: list[dict], timeline: list[dict], tracks: list[dict] | None = None, stage: str = "state") -> list[Finding]:
    """The same character in two settings at the same story moment (same day and time), or two location tracks that disagree."""
    out: list[Finding] = []
    when = {t["id"]: (t.get("day"), str(t.get("time", "")).strip().lower(), bool(t.get("flashback"))) for t in timeline}
    seen: dict[tuple, tuple[str, str]] = {}
    for s in scenes:
        w = when.get(s["id"])
        if not w or w[2]:
            continue
        for c in s.get("characters") or []:
            key = (c, w[0], w[1])
            if key in seen and seen[key][1] != s.get("setting"):
                out.append(hard(stage, "two_places_at_once",
                                f"{c} is in {seen[key][1]} ({seen[key][0]}) and in {s.get('setting')} ({s['id']}) on day {w[0]}, {w[1]}",
                                [seen[key][0], s["id"]]))
            seen.setdefault(key, (s["id"], s.get("setting")))
    by_owner: dict[str, list[dict]] = defaultdict(list)
    for t in tracks or []:
        if t.get("kind") == "location":
            by_owner[t.get("entity", "")].append(t)
    for owner, ts in by_owner.items():
        if len(ts) < 2:
            continue
        at: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for t in ts:
            for e in t.get("plan", []) or []:
                at[str(e.get("from", e.get("from_")))].append((t["id"], str(e["value"])))
        for pos, vals in at.items():
            if len({v for _, v in vals}) > 1:
                out.append(hard(stage, "two_places_at_once", f"{owner} has {len(vals)} different locations at {pos}: " + "; ".join(f"{i}: {v[:40]}" for i, v in vals), [owner, pos]))
    return out


def day_regressions(scenes: list[dict], timeline: list[dict], stage: str = "state") -> list[Finding]:
    out: list[Finding] = []
    by_id = {t["id"]: t for t in timeline}
    last = None
    for s in scenes:
        t = by_id.get(s["id"])
        if not t or t.get("flashback"):
            continue
        if last is not None and t["day"] < last[1]:
            out.append(hard(stage, "story_day_backwards", f"{s['id']} is on day {t['day']}, after {last[0]} on day {last[1]}: story days never run backwards (use flashback: true)", [last[0], s["id"]]))
        last = (s["id"], max(t["day"], last[1] if last else 0))
    return out
