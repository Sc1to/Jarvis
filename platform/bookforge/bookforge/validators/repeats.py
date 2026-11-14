"""Repeated events and repeated ways of solving things, found by meaning rather than by exact text.

Two separate patterns:
- event repeats: the same thing happens again in a later chapter (units are chapter-summary sentences and scene beats);
- action patterns: the same obstacle met the same way over and over (a verb + its object recurring across many chapters).
"""

import math
from collections import defaultdict
from itertools import combinations

from .findings import Finding, hard, soft
from .text import Unit, canon, content_stems, similar, sentences, dice, proper_nouns, WORD, STOP


def _units(chapters: list[dict], scenes: list[dict], names: set[str]) -> list[Unit]:
    units: list[Unit] = []
    for c in chapters:
        for i, s in enumerate(sentences(str(c.get("summary", ""))), 1):
            units.append(Unit(f"{c['id']}#{i}", c["id"], s, names, kind="summary"))
    for sc in scenes:
        for i, b in enumerate(sc.get("beats", []) or [], 1):
            units.append(Unit(f"{sc['id']}.b{i}", sc.get("chapter") or sc["id"].rsplit(".s", 1)[0], str(b), names))
    return units


def _clusters(units: list[Unit], threshold: float, min_shared: int) -> list[list[Unit]]:
    parent = list(range(len(units)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, j in combinations(range(len(units)), 2):
        a, b = units[i], units[j]
        if a.chapter != b.chapter and similar(a, b, threshold, min_shared):
            parent[find(i)] = find(j)
    groups: dict[int, list[Unit]] = defaultdict(list)
    for i, u in enumerate(units):
        groups[find(i)].append(u)
    return [g for g in groups.values() if len({u.chapter for u in g}) >= 2]


def repeated_events(chapters: list[dict], scenes: list[dict], names: set[str] = frozenset(), ledger_events: list[dict] | None = None,
                    stage: str = "chapters") -> list[Finding]:
    """The same event planned in more than one chapter.

    Hard when it recurs in 3+ chapters, or when two chapters' summaries tell it with almost the same words, or when the ledger
    says it is once_only. Otherwise soft: it may be a deliberate echo.
    """
    out: list[Finding] = []
    once = {e["id"] for e in (ledger_events or []) if e.get("once_only", True)}
    units = _units(chapters, scenes, set(names))
    for g in _clusters(units, threshold=0.5, min_shared=3):
        chs = sorted({u.chapter for u in g})
        summaries = [u for u in g if u.kind == "summary"]
        strong = len({u.chapter for u in summaries}) >= 2 and max(
            (dice(a.stems, b.stems) for a, b in combinations(summaries, 2) if a.chapter != b.chapter), default=0) >= 0.7
        severity_hard = len(chs) >= 3 or strong
        text = f"the same event is planned in {len(chs)} chapters ({', '.join(chs[:8])}): each chapter must move the story on, not retell it"
        f = (hard if severity_hard else soft)(stage, "event_repeated", text, chs, [u.text[:140] for u in g[:4]])
        out.append(f)
    # whole chapters that replan another chapter
    chs_units = {c["id"]: Unit(c["id"], c["id"], str(c.get("summary", "")), set(names), "summary") for c in chapters}
    for (a, ua), (b, ub) in combinations(chs_units.items(), 2):
        if dice(ua.stems, ub.stems) >= 0.45 and len(ua.stems & ub.stems) >= 5 and not (ua.names and ub.names and not (ua.names & ub.names)):
            out.append(hard(stage, "chapter_replans_chapter", f"{b} describes nearly the same events as {a}; replace it with new events",
                            [a, b], [ua.text[:140], ub.text[:140]]))
    return out


def action_patterns(scenes: list[dict], chapters: list[dict], names: set[str] = frozenset(), stage: str = "scenes") -> list[Finding]:
    """The same verb + object recurring in many chapters (forcing a lock, fooling a sensor, ...), regardless of the story's events."""
    n_chapters = len({c["id"] for c in chapters}) or len({s.get("chapter") for s in scenes})
    if n_chapters < 6:
        return []
    drop = set(names)
    pair_chapters: dict[tuple, set] = defaultdict(set)
    word_chapters: dict[str, set] = defaultdict(set)
    example: dict[tuple, str] = {}
    for sc in scenes:
        ch = sc.get("chapter") or sc["id"].rsplit(".s", 1)[0]
        for beat in sc.get("beats", []) or []:
            toks = content_stems(str(beat), drop=drop | proper_nouns(str(beat)))
            seen = set()
            for i, a in enumerate(toks):
                word_chapters[a].add(ch)
                for b in toks[i + 1:i + 3]:
                    if a != b:
                        pair = tuple(sorted((a, b)))
                        seen.add(pair)
                        example.setdefault(pair, str(beat)[:140])
            for pair in seen:
                pair_chapters[pair].add(ch)
    out: list[Finding] = []
    need = max(4, math.ceil(0.2 * n_chapters))
    hard_at = math.ceil(0.3 * n_chapters)
    reported: list[set] = []
    for pair, chs in sorted(pair_chapters.items(), key=lambda kv: -len(kv[1])):
        if len(chs) < need:
            continue
        dfs = (len(word_chapters[pair[0]]), len(word_chapters[pair[1]]))
        if max(dfs) > 0.9 * n_chapters or len(chs) < 0.6 * min(dfs):
            continue  # a word that is everywhere says nothing; the pair must mostly travel together
        if any(set(pair) & r for r in reported):  # one finding per cluster of related words
            continue
        reported.append(set(pair))
        make = hard if len(chs) >= hard_at else soft
        out.append(make(stage, "action_pattern_repeated",
                        f"the same action ('{pair[0]}' + '{pair[1]}') recurs in {len(chs)} of {n_chapters} chapters: "
                        "give later chapters a different obstacle or a different way through",
                        sorted(chs), [example[pair]]))
    return out
