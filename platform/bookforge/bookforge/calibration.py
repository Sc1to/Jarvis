"""Calibration: your scores against the critic's, per criterion.

At the voice checkpoint you score a few chapter-1 scenes on the same rubric the critic uses; if the critic's ranking
disagrees with yours on more than one pair of scenes, its rubric wording needs adjusting (`workbench/prompts/critic_rubric.md`).
Your scores are kept in `workbench/calibration.yaml`; the critic's come from each scene's `review.json`.
"""

import json
from itertools import combinations

import yaml

from . import scenefiles
from .bible import store
from .errors import BookforgeError
from .project import Project
from .qc.critic import CRITERIA

MAX_DISAGREEMENTS = 1


class CalibrationError(BookforgeError):
    pass


def _path(project: Project):
    return project.root / "workbench" / "calibration.yaml"


def load(project: Project) -> dict[str, dict[str, int]]:
    try:
        data = yaml.safe_load(_path(project).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return {k: v for k, v in (data.get("scores") or {}).items() if isinstance(v, dict)}


def record(project: Project, scene_id: str, scores: dict[str, int]) -> None:
    if scene_id not in {s.id for s in store.load_scenes(project)}:
        raise CalibrationError(f"no scene '{scene_id}'")
    bad = [c for c in CRITERIA if isinstance(scores.get(c), bool) or not isinstance(scores.get(c), int) or not 1 <= scores[c] <= 5]
    if bad:
        raise CalibrationError(f"give a whole number from 1 to 5 for: {', '.join(bad)}")
    data = load(project)
    data[scene_id] = {c: scores[c] for c in CRITERIA}
    p = _path(project)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump({"scores": data}, sort_keys=True), encoding="utf-8")


def critic_scores(project: Project, scene_id: str) -> dict[str, int] | None:
    raw = scenefiles.read(scenefiles.review_path(project, scene_id))
    try:
        scores = ((json.loads(raw).get("critic") or {}).get("scores")) if raw else None
    except ValueError:
        return None
    return scores or None


def report(project: Project) -> dict:
    mine = load(project)
    rows = []
    for sid, yours in mine.items():
        critic = critic_scores(project, sid)
        rows.append({"scene": sid, "yours": yours, "critic": critic})
    both = [r for r in rows if r["critic"]]
    per = {}
    for c in CRITERIA:
        pairs = [(r["yours"][c], r["critic"][c]) for r in both if c in r["critic"]]
        if not pairs:
            per[c] = None
            continue
        diffs = [y - k for y, k in pairs]
        per[c] = {"n": len(pairs), "mean_abs_diff": round(sum(abs(d) for d in diffs) / len(diffs), 2), "bias": round(sum(diffs) / len(diffs), 2),
                  "within_one": round(sum(abs(d) <= 1 for d in diffs) / len(diffs), 2)}
    totals = {r["scene"]: (sum(r["yours"].values()), sum(r["critic"].values())) for r in both}
    disagreements = 0
    for a, b in combinations(totals, 2):
        (ya, ka), (yb, kb) = totals[a], totals[b]
        if ya != yb and ka != kb and (ya > yb) != (ka > kb):  # a strict ranking by each, and they point opposite ways
            disagreements += 1
    return {"scenes": rows, "criteria": per, "compared": len(both), "ranking_disagreements": disagreements,
            "needs_recalibration": len(both) >= 3 and disagreements > MAX_DISAGREEMENTS,
            "advice": ("the critic's ranking disagrees with yours on more than one pair: reword workbench/prompts/critic_rubric.md and re-run the critic"
                       if len(both) >= 3 and disagreements > MAX_DISAGREEMENTS else
                       "score at least 3 scenes the critic has also scored to compare rankings" if len(both) < 3 else "the critic's ranking agrees with yours closely enough")}
