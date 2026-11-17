"""Topics for knowledge needs: one topic, one decision, however many chapters ask about it.

Needs used to be matched on their exact wording, so "how does the polymer cure" and "how long until the sealant sets" were two
questions with two approvals. A topic is the set of distinctive word stems of a need's question, query and rule; two needs share
a topic when they overlap enough. Everything here is deterministic (no model call).
"""
from __future__ import annotations

import re

from ..validators.text import content_stems

# Words that make every question look alike in this domain ("how does X work in the story") and say nothing about the topic.
_GENERIC = frozenset("""work works working behave behaves behaviour behavior look looks like happen happens story scene scenes
use used using need needs required require long take takes time process method way ways effect effects work condition conditions
visual indicator indicators sign signs failure failures mode modes verify check difference differences typical standard normal
real world setting world""".split())

MIN_SHARED = 2
OVERLAP = 0.5  # shared / size of the smaller set


def topic_stems(*texts: str) -> frozenset[str]:
    out: set[str] = set()
    for t in texts:
        out |= set(content_stems(t or ""))
    return frozenset(s for s in out if s not in _GENERIC)


def need_stems(need) -> frozenset[str]:
    return topic_stems(need.question, need.query)


def same_topic(a: frozenset[str], b: frozenset[str]) -> bool:
    shared = a & b
    if not a or not b or len(shared) < min(MIN_SHARED, len(a), len(b)):
        return False
    return len(shared) / min(len(a), len(b)) >= OVERLAP


def topic_key(stems: frozenset[str]) -> str:
    """A stable short label from the stems (sorted, at most four)."""
    return "-".join(sorted(stems)[:4])


def find_existing(needs: list, question: str, query: str):
    """The live need (not merged away) on the same topic as this question, or None."""
    wanted = topic_stems(question, query)
    best, best_score = None, 0.0
    for n in needs:
        if getattr(n, "merged_into", ""):
            continue
        stems = need_stems(n)
        if same_topic(wanted, stems):
            score = len(wanted & stems) / max(1, min(len(wanted), len(stems)))
            if score > best_score:
                best, best_score = n, score
    return best


def clusters(needs: list) -> list[list]:
    """Group live needs by topic (single linkage over `same_topic`); clusters in order of first need."""
    live = [n for n in needs if not getattr(n, "merged_into", "")]
    stems = [need_stems(n) for n in live]
    parent = list(range(len(live)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(live)):
        for j in range(i + 1, len(live)):
            if same_topic(stems[i], stems[j]):
                parent[find(j)] = find(i)
    groups: dict[int, list] = {}
    for i, n in enumerate(live):
        groups.setdefault(find(i), []).append(n)
    return list(groups.values())


# ── contradictions: two rules on one topic that state different quantities ───

_UNITS = {"second": "s", "seconds": "s", "sec": "s", "minute": "min", "minutes": "min", "min": "min", "hour": "h", "hours": "h",
          "day": "d", "days": "d", "week": "w", "weeks": "w", "metre": "m", "metres": "m", "meter": "m", "meters": "m",
          "km": "km", "kilometre": "km", "kilometres": "km", "cm": "cm", "kg": "kg", "tonne": "t", "tonnes": "t", "percent": "%", "%": "%"}
_NUM = re.compile(r"(\d+(?:[.,]\d+)?)\s*(%|[a-zA-Z]+)")
_WORD_QTY = re.compile(r"\b(?:within|in|after|under|over)\s+(?:a\s+few\s+|some\s+)?(seconds|minutes|hours|days|weeks)\b", re.I)
_ORDER = {"s": 1, "min": 60, "h": 3600, "d": 86400, "w": 604800}


def quantities(text: str) -> set[tuple[str, float]]:
    """(unit, value) pairs a rule states, time normalised to seconds; a bare 'within minutes' is ('s-scale', magnitude)."""
    out: set[tuple[str, float]] = set()
    for num, unit in _NUM.findall(text or ""):
        u = _UNITS.get(unit.casefold())
        if not u:
            continue
        v = float(num.replace(",", "."))
        if u in _ORDER:
            out.add(("time", v * _ORDER[u]))
        else:
            out.add((u, v))
    for word in _WORD_QTY.findall(text or ""):
        out.add(("scale", float(_ORDER[_UNITS[word.casefold()]])))
    return out


def disagree(a_rule: str, b_rule: str) -> bool:
    """True when the rules state quantities of the same kind that differ by more than a factor of two (or a different order of magnitude word)."""
    qa, qb = quantities(a_rule), quantities(b_rule)
    for kind in {k for k, _ in qa} & {k for k, _ in qb}:
        va = [v for k, v in qa if k == kind]
        vb = [v for k, v in qb if k == kind]
        if kind == "scale":
            if set(va).isdisjoint(vb):
                return True
            continue
        # time/other: disagree unless some pair is within a factor of two
        if not any(min(x, y) > 0 and max(x, y) / min(x, y) <= 2 for x in va for y in vb):
            return True
    return False


def contradictions(needs: list) -> list[tuple]:
    """Pairs of live, rule-bearing needs on one topic whose rules disagree on a quantity."""
    out = []
    for group in clusters(needs):
        ruled = [n for n in group if n.rule and n.status != "rejected"]
        for i, a in enumerate(ruled):
            for b in ruled[i + 1:]:
                if disagree(a.rule, b.rule):
                    out.append((a, b))
    return out


# ── what exists, for the question generator and for scope ───────────────────

EXISTING_CHARS = 1500


def existing_text(needs: list) -> str:
    """A compact list of the live needs (topic and one line of the rule), so the generator asks only about something new."""
    lines, used = [], 0
    for n in needs:
        if n.merged_into or n.status == "rejected" and not n.rule:
            continue
        line = f"- {n.question[:110]} ({n.stance}, {n.status})" + (f": {n.rule[:110]}" if n.rule else "")
        if used + len(line) > EXISTING_CHARS:
            lines.append("- (and more: ask nothing that overlaps these topics)")
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines) or "none yet"


def widen_scope(current: list[str], new: list[str]) -> list[str]:
    """Where a need applies after it is raised again for `new` places: the union, and the whole book ([]) once it covers two chapters."""
    if not current:
        return []  # already the whole book
    if not new:
        return []
    union = list(dict.fromkeys(list(current) + list(new)))
    chapters = {".".join(p.split(".")[:2]) for p in union}
    return [] if len(chapters) >= 2 else union
