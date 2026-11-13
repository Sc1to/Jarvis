"""Research is for accuracy and texture. These checks find research that has become part of the plot."""

import re
from collections import defaultdict

from .findings import Finding, hard, soft
from .text import WORD, content_stems, shingles, STOP

_ODD = re.compile(r"\d|^[A-Z]{3,}$")


def _vocab(texts: list[str]) -> set[str]:
    return {w.lower() for t in texts for w in WORD.findall(t)}


def rare_terms(note_claims: list[str], story_texts: list[str]) -> set[str]:
    """Terms that occur in research notes but nowhere in the story's own material (synopsis, north stars, cast, ledger):
    long words, acronyms and anything with digits. They are technical vocabulary the story did not ask for."""
    story = _vocab(story_texts)
    out = set()
    for claim in note_claims:
        for w in WORD.findall(claim):
            low = w.lower()
            if low in story or low in STOP:
                continue
            if len(low) >= 10 or _ODD.search(w):
                out.add(low)
    return out


def research_in_beats(scenes: list[dict], note_claims: list[str], story_texts: list[str], stage: str = "scenes") -> list[Finding]:
    """Beats that use a research term the story never introduced, or copy three-word phrases from a note.

    Soft for one beat; hard when the same term or phrase turns up in three or more scenes (a note has become a recurring device).
    """
    terms = rare_terms(note_claims, story_texts)
    note_shingles: dict[tuple, str] = {}
    for c in note_claims:
        for sh in shingles(c, 3):
            if not all(w in STOP for w in sh):
                note_shingles.setdefault(sh, c)
    hits: dict[str, set[str]] = defaultdict(set)
    shown: dict[str, str] = {}
    for s in scenes:
        for beat in s.get("beats", []) or []:
            low = {w.lower() for w in WORD.findall(str(beat))}
            for t in terms & low:
                hits[t].add(s["id"])
                shown.setdefault(t, str(beat)[:140])
            for sh in shingles(str(beat), 3):
                if sh in note_shingles and sum(w not in STOP for w in sh) >= 2:
                    key = " ".join(sh)
                    hits[key].add(s["id"])
                    shown.setdefault(key, str(beat)[:140])
    out = []
    for term, ids in sorted(hits.items(), key=lambda kv: -len(kv[1])):
        make = hard if len(ids) >= 3 else soft
        out.append(make(stage, "research_in_beats", f"research term '{term}' appears in the beats of {len(ids)} scene(s): reference material informs accuracy and texture, "
                        "it must not become a beat or a plot device", sorted(ids)[:10], [shown[term]]))
    return out
