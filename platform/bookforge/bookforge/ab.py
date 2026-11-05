"""Prompt A/B tests on the benchmark scenes.

Variant A is the template as it is now (your override, or the shipped one); variant B is a candidate text.
Both are run on every benchmark brief (same brief, same model, first draft temperature). Each pair gets the
mechanical numbers and the pairwise judge's verdict (run twice with the order swapped). You can also vote
blind: the two texts are shown in a random order without saying which is which, and the mapping is revealed
for a benchmark only after your vote on it. An experiment is a folder `workbench/experiments/ab-<stamp>/`
(texts, both prompts, the diff, `results.json`), versioned with the series. A winning candidate is promoted
to the series' override with `promote`.
"""

import json
import random
import re
from datetime import datetime, timezone

from . import bench, studio, vcs
from .errors import BookforgeError
from .layers.runner import StepContext
from .project import Project
from .qc.judge import judge_pair

TESTABLE = ("prose", "prose_system")  # the templates the benchmark drafts are written with


class ABError(BookforgeError):
    pass


def _dir(project: Project, name: str):
    if not re.fullmatch(r"ab-[0-9]{8}-[0-9]{6}(-[0-9]+)?", name):
        raise ABError(f"no experiment '{name}'")
    d = bench.experiments_dir(project) / name
    if not d.is_dir():
        raise ABError(f"no experiment '{name}'")
    return d


def run_ab(ctx: StepContext, template: str, candidate: str, only: list[str] | None = None, judge: bool = True) -> dict:
    project = ctx.project
    if template not in TESTABLE:
        raise ABError(f"only {', '.join(TESTABLE)} can be tested on the benchmarks")
    check = studio.check_candidate(template, candidate)
    if check["errors"]:
        raise ABError("; ".join(check["errors"]))
    current = studio.effective_text(project, template)
    if candidate.strip() == current.strip():
        raise ABError("the candidate is the same as the current prompt")
    stamp = "ab-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    name, n = stamp, 1
    while (bench.experiments_dir(project) / name).exists():
        n += 1
        name = f"{stamp}-{n}"
    d = bench.experiments_dir(project) / name
    d.mkdir(parents=True)
    (d / "variant-a.md").write_text(current, encoding="utf-8")
    (d / "variant-b.md").write_text(candidate, encoding="utf-8")
    (d / "diff.patch").write_text(studio.unified_diff(current, candidate, "a (current)", "b (candidate)"), encoding="utf-8")
    rng = random.Random(name)
    results: dict = {}
    order: dict = {}
    for b in bench.load_benchmarks(project, only):
        ta = bench.generate(ctx, b)
        tb = bench.generate(ctx, b, {template: candidate})
        (d / f"{b.id}.a.md").write_text(ta + "\n", encoding="utf-8")
        (d / f"{b.id}.b.md").write_text(tb + "\n", encoding="utf-8")
        row = {"a": bench.stats_for(ta, b, project), "b": bench.stats_for(tb, b, project), "judge": "not judged"}
        if judge:
            try:
                winner, _ = judge_pair(ctx, b.scene(), "a", ta, "b", tb)
                row["judge"] = {"a": "a", "b": "b", None: "tie"}[winner]
            except BookforgeError as e:
                row["judge"], row["error"] = "unknown", str(e)
        results[b.id] = row
        order[b.id] = rng.sample(["a", "b"], 2)
    record = {"name": name, "template": template, "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "warnings": check["warnings"], "results": results, "order": order, "votes": {}, "promoted": False}
    _save(d, record)
    if project.config.git.commit_each_step:
        vcs.commit(project.root, f"experiment {name}: {template} candidate", [str(d.relative_to(project.root))])
    return summary(record)


def _save(d, record: dict) -> None:
    (d / "results.json").write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")


def _load(project: Project, name: str) -> tuple:
    d = _dir(project, name)
    return d, json.loads((d / "results.json").read_text(encoding="utf-8"))


def summary(record: dict) -> dict:
    judged = [r["judge"] for r in record["results"].values()]
    mine = list(record["votes"].values())
    return {"name": record["name"], "template": record["template"], "created": record["created"], "promoted": record["promoted"],
            "judge": {"a": judged.count("a"), "b": judged.count("b"), "tie": judged.count("tie")},
            "yours": {"a": mine.count("a"), "b": mine.count("b"), "tie": mine.count("tie"), "of": len(record["results"])},
            "benchmarks": len(record["results"])}


def list_experiments(project: Project) -> list[dict]:
    out = []
    for p in sorted(bench.experiments_dir(project).glob("ab-*"), reverse=True) if bench.experiments_dir(project).is_dir() else []:
        try:
            out.append(summary(json.loads((p / "results.json").read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            continue
    return out


def view(project: Project, name: str) -> dict:
    """The experiment for reading: texts in blind order; which is which only for benchmarks you have voted on."""
    d, rec = _load(project, name)
    pairs = []
    for bid, row in rec["results"].items():
        first, second = rec["order"][bid]
        voted = bid in rec["votes"]
        item = {"id": bid, "first": (d / f"{bid}.{first}.md").read_text(encoding="utf-8"), "second": (d / f"{bid}.{second}.md").read_text(encoding="utf-8"),
                "voted": voted, "vote": None}
        if voted:  # revealed after the vote
            v = rec["votes"][bid]
            item.update(vote=v, first_is=first, second_is=second, judge=row["judge"], stats=row)
        pairs.append(item)
    head = summary(rec)
    if len(rec["votes"]) < len(rec["results"]):
        head["judge"] = None  # the judge's totals would give the answer away: shown once every pair has your vote
    return {**head, "diff": (d / "diff.patch").read_text(encoding="utf-8"), "warnings": rec["warnings"], "pairs": pairs}


def vote(project: Project, name: str, bench_id: str, choice: str) -> dict:
    """choice: 'first', 'second' or 'tie', as shown to you. Stored as the variant it was."""
    d, rec = _load(project, name)
    if bench_id not in rec["results"]:
        raise ABError(f"no benchmark '{bench_id}' in {name}")
    if choice not in ("first", "second", "tie"):
        raise ABError("choice must be first, second or tie")
    first, second = rec["order"][bench_id]
    rec["votes"][bench_id] = {"first": first, "second": second, "tie": "tie"}[choice]
    _save(d, rec)
    if project.config.git.commit_each_step:
        vcs.commit(project.root, f"experiment {name}: vote on {bench_id}", [str(d.relative_to(project.root))])
    return view(project, name)


def promote(project: Project, name: str) -> dict:
    d, rec = _load(project, name)
    result = studio.save_override(project, rec["template"], (d / "variant-b.md").read_text(encoding="utf-8"))
    rec["promoted"] = True
    _save(d, rec)
    if project.config.git.commit_each_step:
        vcs.commit(project.root, f"prompt {rec['template']}: candidate from {name} adopted", [str(d.relative_to(project.root)), f"workbench/prompts/{rec['template']}.md"])
    return result
