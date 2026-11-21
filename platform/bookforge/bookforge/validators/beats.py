"""Are the beats of a scene concrete enough that the writer has nothing to invent? Deterministic checks, no model.

A beat that says "she notices something unusual" leaves the writer to invent what, and every later scene then builds on an invention nobody
approved. These checks find the placeholder wording and the scenes whose planning text is too thin for the length asked of them. Both are
advice (soft): the beat review (qc/beat_review.py) and you decide what to do. Nothing here is about one genre.
"""

import re

from .findings import Finding, soft

# Words that stand in for the thing a beat should name. A beat may still use them when it also names the thing (see _names_something).
_PLACEHOLDER = re.compile(
    r"\b(something|someone|somebody|somewhere)\s+(unusual|odd|strange|suspicious|important|significant|interesting|wrong|off|unexpected)\b|"
    r"\b(another|a|the)\s+(clue|revelation|discovery|piece of evidence|key piece of evidence|new piece of information)\b|"
    r"\b(reveals?|discovers?|finds?|notices?|realizes?|realises?|learns?)\s+(something|new information|important information|vital information|crucial information|the truth)\b|"
    r"\b(significant|important|crucial|vital|key)\s+(information|evidence|detail|clue|discovery)\b", re.I)
_MIN_BEAT_WORDS = 7
_THIN_RATIO = 0.05  # planning words per word of the length guide below which the scene is called thin


def _names_something(beat: str) -> bool:
    """A beat that gives specifics after the placeholder (a colon, a dash or 'namely/that/which' and a clause of some length) is not a bare placeholder."""
    m = _PLACEHOLDER.search(beat)
    if not m:
        return True
    tail = beat[m.end():]
    return bool(re.search(r"[:\u2014\-;]|\b(namely|that|which|because|:)\b", tail)) and len(tail.split()) >= 8


def vague_beats(scenes: list[dict], stage: str = "scenes") -> list[Finding]:
    """Beats that stand in for what they should name, or are too short to carry an event."""
    out: list[Finding] = []
    for sc in scenes:
        bad = []
        for i, b in enumerate(sc.get("beats") or [], 1):
            text = str(b)
            if _PLACEHOLDER.search(text) and not _names_something(text):
                bad.append((i, text, "names no actual thing, only a placeholder (\"something unusual\", \"a clue\"); say what it is"))
            elif len(text.split()) < _MIN_BEAT_WORDS:
                bad.append((i, text, "is too short to carry an event, a reason and a consequence"))
        if bad:
            out.append(soft(stage, "beat_vague", f"{sc['id']}: " + "; ".join(f"beat {i} {why}" for i, _, why in bad[:3])
                            + ". The writer would have to invent it, and the invention becomes story", [sc["id"]], [f"beat {i}: {t[:140]}" for i, t, _ in bad[:3]]))
    return out


def thin_for_range(scenes: list[dict], word_range, stage: str = "scenes") -> list[Finding]:
    """A scene whose planning text is a small fraction of the length asked for: the extra words would be filler. `word_range(scene) -> (lo, hi)`."""
    out: list[Finding] = []
    for sc in scenes:
        lo, hi = word_range(sc)
        planned = sum(len(str(x).split()) for x in list(sc.get("beats") or []) + [sc.get("situation", ""), sc.get("learns", "")])
        if lo and planned / lo < _THIN_RATIO:
            out.append(soft(stage, "beats_thin_for_range", f"{sc['id']}: its beats and notes come to {planned} words for a scene of {lo} to {hi} words. "
                            "Either add the concrete moments the scene needs, or accept a shorter scene: nothing is padded to reach the length", [sc["id"]]))
    return out
