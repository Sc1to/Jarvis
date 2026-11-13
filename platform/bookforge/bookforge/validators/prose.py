"""Prose checks across scenes: copied sentences, copied chapter openings, wrap-up endings, tic words. Work without a style guide."""

import re
from collections import Counter, defaultdict

from .findings import Finding, hard, soft
from .text import WORD, STOP, norm_sentence, sentences, shingles, stem

MIN_SENTENCE_WORDS = 6
_WRAP = re.compile(r"\b(for now|at last|finally|in the end|all that mattered|and so|somehow|never again|once and for all|would never be the same|"
                   r"had (changed|begun)|was (over|just beginning)|were (free|safe|home))\b", re.I)
_ABSTRACT = frozenset("""hope future truth freedom free peace home together change begin beginning end silence everything nothing always never
 forever whatever together story life world light dark""".split())


def repeated_sentences(scene_texts: list[tuple[str, str]], stage: str = "prose") -> list[Finding]:
    """Sentences (six words or more) that already appeared in an earlier scene, exactly or nearly (shared 5-word shingles)."""
    out: list[Finding] = []
    seen: dict[str, str] = {}
    seen_sh: list[tuple[set, str]] = []
    for sid, text in scene_texts:
        dup: list[tuple[str, str]] = []
        sents = [s for s in sentences(text) if len(WORD.findall(s)) >= MIN_SENTENCE_WORDS]
        for s in sents:
            n = norm_sentence(s)
            if n in seen and seen[n] != sid:
                dup.append((s, seen[n]))
                continue
            sh = shingles(s, 5)
            if sh and any(len(sh & o) / len(sh | o) >= 0.7 for o, osid in seen_sh if osid != sid):
                dup.append((s, "an earlier scene"))
        for s in sents:
            seen.setdefault(norm_sentence(s), sid)
            seen_sh.append((shingles(s, 5), sid))
        if dup:
            share = len(dup) / max(1, len(sents))
            make = hard if len(dup) >= 4 or share >= 0.1 else soft
            out.append(make(stage, "sentences_repeated", f"{sid}: {len(dup)} sentence(s) ({share:.0%}) were already written in earlier scenes",
                            [sid], [d[0][:120] for d in dup[:3]]))
    return out


def chapter_openings_copy(chapters: list[tuple[str, str]], stage: str = "prose", head_words: int = 80, tail_words: int = 150) -> list[Finding]:
    """A chapter that opens with words taken from the previous chapter's last lines."""
    out = []
    for (pid, prev), (cid, cur) in zip(chapters, chapters[1:]):
        tail = " ".join(prev.split()[-tail_words:])
        head = " ".join(cur.split()[:head_words])
        shared = shingles(tail, 6) & shingles(head, 6)
        if shared:
            out.append(hard(stage, "chapter_opens_with_previous_ending", f"{cid} opens with words copied from the end of {pid}: begin with something new",
                            [pid, cid], [" ".join(sorted(shared)[0])]))
    return out


def wrap_up_endings(scene_texts: list[tuple[str, str]], stage: str = "prose") -> list[Finding]:
    """Scenes whose last sentence summarises or states the theme instead of ending on action or an image. Soft: a heuristic."""
    out = []
    for sid, text in scene_texts:
        sents = sentences(text)
        if not sents:
            continue
        last = sents[-1]
        words = [w.lower() for w in WORD.findall(last)]
        if not words or '"' in last or "“" in last:
            continue
        score = (bool(_WRAP.search(last))) + (len(words) <= 14 and sum(w in _ABSTRACT for w in words) >= 1) + (len(words) <= 9)
        if score >= 2:
            out.append(soft(stage, "wrap_up_ending", f"{sid} ends on a summing-up line: end on the moment, not on what it meant", [sid], [last[:140]]))
    return out


def tic_report(scene_texts: list[tuple[str, str]], names: set[str] = frozenset(), min_scene_share: float = 0.5, stage: str = "prose") -> tuple[list[Finding], dict]:
    """Words and two-word phrases that turn up in an unusually large share of scenes (the writer's habits). Reports a frequency table."""
    n = len(scene_texts)
    if n < 6:
        return [], {}
    word_scenes: dict[str, set] = defaultdict(set)
    word_count: Counter = Counter()
    pair_scenes: dict[str, set] = defaultdict(set)
    pair_count: Counter = Counter()
    for sid, text in scene_texts:
        toks = [w.lower() for w in WORD.findall(text)]
        for t in toks:
            if t not in STOP and len(t) > 3 and t not in names:
                word_scenes[t].add(sid)
                word_count[t] += 1
        for a, b in zip(toks, toks[1:]):
            if a not in STOP and b not in STOP and a not in names and b not in names and len(a) > 2 and len(b) > 2:
                k = f"{a} {b}"
                pair_scenes[k].add(sid)
                pair_count[k] += 1
    total_words = sum(len(WORD.findall(t)) for _, t in scene_texts) or 1
    rows = []
    for table, counts in ((word_scenes, word_count), (pair_scenes, pair_count)):
        for k, sc in table.items():
            share = len(sc) / n
            if share >= min_scene_share and counts[k] >= max(8, n):
                rows.append({"term": k, "scenes": len(sc), "share": round(share, 2), "per_1000_words": round(1000 * counts[k] / total_words, 2)})
    rows.sort(key=lambda r: (-r["share"], -r["per_1000_words"]))
    out = [soft(stage, "tic_word", f"'{r['term']}' appears in {r['scenes']} of {n} scenes ({r['per_1000_words']} per 1000 words): vary or cut it", [], [])
           for r in rows[:12]]
    return out, {"scenes": n, "top": rows[:30]}
