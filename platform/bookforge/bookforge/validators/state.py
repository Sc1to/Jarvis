"""State checks: tracks that flip back, people in two places, story days running backwards."""

import re
from collections import defaultdict

from ..bible.positions import parse_position
from .findings import Finding, hard, soft
from .text import content_stems, dice


_PARTS = (("midnight", ("midnight", "small hours", "witching")), ("night", ("night", "late", "after dark")), ("dawn", ("dawn", "sunrise", "daybreak", "first light")),
          ("morning", ("morning", "forenoon", "breakfast")), ("noon", ("noon", "midday", "lunch")), ("afternoon", ("afternoon",)),
          ("dusk", ("dusk", "sunset", "twilight", "evening", "nightfall", "supper")))


def time_part(text: str) -> str:
    """A time of day as a part of the day, so 'dusk' and 'evening' are the same moment and 'noon' and 'midday' too."""
    low = str(text).strip().lower()
    for part, words in _PARTS:
        if any(w in low for w in words):
            return part
    return low


def _pos(text: str):
    try:
        return parse_position(text).key
    except ValueError:
        return (0, 0)


def returns(plan: list[dict]) -> list[tuple[int, int]]:
    """(k, j) for each entry k of a plan (sorted by position) whose value goes back to the earlier entry j (A, B, A) without a `cause`."""
    stems = [set(content_stems(str(e.get("value", "")))) for e in plan]
    out = []
    for k in range(2, len(plan)):
        if plan[k].get("cause"):
            continue
        for j in range(k - 1):  # an earlier entry that is not the one just before
            if stems[k] and dice(stems[k], stems[j]) >= 0.75 and dice(stems[k], stems[k - 1]) < 0.75:
                out.append((k, j))
                break
    return out


def track_regressions(tracks: list[dict], stage: str = "state") -> list[Finding]:
    """A track returns to an earlier value (A, B, A) without an entry that says what caused the return (`cause:`). The tool writes that cause itself
    (bible/normalize.py::attach_return_causes, from the scene that changes the state), so this only finds one that was left without."""
    out: list[Finding] = []
    for t in tracks:
        plan = sorted(t.get("plan", []) or [], key=lambda e: _pos(str(e.get("from", e.get("from_", "")))))
        for k, j in returns(plan):
            a, b = plan[j], plan[k]
            out.append(hard(stage, "state_regression",
                            f"track {t['id']} goes back to an earlier state at {b.get('from', b.get('from_'))} ('{b['value'][:70]}') "
                            f"after changing at {plan[k - 1].get('from', plan[k - 1].get('from_'))}: say what caused the return (cause:) or keep the later state",
                            [t["id"], str(b.get("from", b.get("from_")))], [str(a["value"])[:100], str(plan[k - 1]["value"])[:100]]))
    return out


def location_conflicts(scenes: list[dict], timeline: list[dict], tracks: list[dict] | None = None, stage: str = "state") -> list[Finding]:
    """Two location tracks of one character that give different places at the same position.

    Two SCENES are never compared: they are a sequence in story order, so the same day and the same part of the day only means one comes after the
    other (a walk from one place to the next), and the plan never says that two scenes are simultaneous. Comparing them could only raise false alarms
    (every pair of scenes of a book whose scenes all said 'day 1, morning' was a conflict)."""
    out: list[Finding] = []
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


def timeline_flat(timeline: list[dict], stage: str = "scenes", share: float = 0.5, minimum: int = 6) -> list[Finding]:
    """More than half of the scenes on one story day: no time passes in the plan (usually the model copied 'days_later: 0' for every scene)."""
    days = [int(t["day"]) for t in timeline if not t.get("flashback") and isinstance(t.get("day"), int)]
    if len(days) < minimum:
        return []
    day, n = max(((d, days.count(d)) for d in set(days)), key=lambda x: x[1])
    if n / len(days) <= share:
        return []
    return [hard(stage, "timeline_flat", f"{n} of {len(days)} scenes are on story day {day}: time barely passes in the plan. Say how many days after the scene before each scene happens",
                 [t["id"] for t in timeline if t.get("day") == day][:12])]


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
