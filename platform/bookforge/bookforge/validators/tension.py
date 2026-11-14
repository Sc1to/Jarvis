"""Tension curve: long flat stretches."""

import math

from .findings import Finding, hard, soft


def flat_stretches(chapters: list[dict], stage: str = "chapters", spread: int = 2) -> list[Finding]:
    """Runs of consecutive chapters whose tension stays within `spread` points. Long means at least 5 chapters and 15% of the book."""
    n = len(chapters)
    if n < 6:
        return []
    need = max(5, math.ceil(0.15 * n))
    out: list[Finding] = []
    i = 0
    while i < n:
        lo = hi = int(chapters[i]["tension"])
        j = i + 1
        while j < n and max(hi, int(chapters[j]["tension"])) - min(lo, int(chapters[j]["tension"])) <= spread:
            lo, hi = min(lo, int(chapters[j]["tension"])), max(hi, int(chapters[j]["tension"]))
            j += 1
        run = j - i
        if run >= need:
            ids = [c["id"] for c in chapters[i:j]]
            make = hard if run >= math.ceil(0.3 * n) else soft
            out.append(make(stage, "flat_tension", f"tension stays between {lo} and {hi} for {run} chapters in a row ({ids[0]} to {ids[-1]}): "
                            "vary it so the story builds, releases and builds again", ids))
            i = j
        else:
            i += 1
    return out
