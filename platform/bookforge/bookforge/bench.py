"""Regression benchmarks: a few fixed scene briefs, redrafted after any change and compared with the last accepted run.

`benchmarks/*.yaml` in the tool holds the shipped briefs; `<series>/workbench/benchmarks/*.yaml` adds
series-specific ones (the same id replaces a shipped one). Each is self-contained: no bible, no earlier
scenes, so what changes the result is only the prompt, the model or the settings.

A run writes one draft per brief with the writer model (first draft temperature), checks it mechanically,
and saves everything under `workbench/experiments/bench-<stamp>/`. Compared with the accepted run, each
brief gets the mechanical difference and a pairwise judgment (the same judge as for drafts, run twice with the
order swapped; a split is a tie). A change *ships* if no brief picked up a blocking problem it did not have and
it does not lose more briefs than it wins. `--accept` makes a run the new baseline.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import scenefiles, vcs
from .bible.models import Scene
from .deps import fingerprint
from .errors import BookforgeError
from .layers.document import prompt_values
from .layers.runner import StepContext
from .project import Project
from .prompts import render, render_text, template_path
from .qc.judge import judge_pair
from .qc.mechanical import CheckContext, check_scene, load_banned
from .qc.support import voice_excerpt

log = logging.getLogger("platform_bookforge.bench")

SHIPPED_DIR = Path(__file__).resolve().parent.parent / "benchmarks"


class BenchError(BookforgeError):
    pass


class Character(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    facts: list[str] = []


class Benchmark(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    purpose: str
    pov: str  # a character's name
    setting: str
    characters: list[Character] = Field(min_length=1)
    beats: list[str] = Field(min_length=2, max_length=10)
    words: tuple[int, int] = (300, 600)

    def slug(self, name: str) -> str:
        s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        return s if s[:1].isalpha() else "x" + s

    def scene(self) -> Scene:
        return Scene(id=self.id, purpose=self.purpose, pov=self.slug(self.pov), setting="setting",
                     characters=[self.slug(c.name) for c in self.characters], beats=self.beats)

    def briefing(self, project: Project) -> str:
        banned = load_banned(scenefiles.read(project.root / project.config.qc.banned_phrases) or "")
        cast = "\n".join(f"- {c.name}: " + "; ".join(c.facts) for c in self.characters)
        beats = "\n".join(f"{i}. {b}" for i, b in enumerate(self.beats, 1))
        parts = [("Style guide and sample", voice_excerpt(project))]
        if banned:
            parts.append(("Phrases never to use", "\n".join(f"- {b}" for b in banned[:80])))
        parts += [("Cast", cast), ("This scene", f"Purpose: {self.purpose}\nViewpoint character: {self.pov}\nSetting: {self.setting}\n"
                                                   f"Beats, in order (what happens and why, not how to write it):\n{beats}")]
        return "\n\n".join(f"## {h}\n\n{b}" for h, b in parts)


def load_benchmarks(project: Project, only: list[str] | None = None) -> list[Benchmark]:
    found: dict[str, Benchmark] = {}
    for directory in (SHIPPED_DIR, project.root / "workbench" / "benchmarks"):
        for path in sorted(directory.glob("*.yaml")) if directory.is_dir() else []:
            try:
                b = Benchmark.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
            except (OSError, yaml.YAMLError, ValidationError) as e:
                raise BenchError(f"{path} is not a valid benchmark: {e}") from e
            found[b.id] = b
    if only:
        unknown = set(only) - set(found)
        if unknown:
            raise BenchError(f"no benchmark named {', '.join(sorted(unknown))} (have: {', '.join(sorted(found))})")
        found = {k: v for k, v in found.items() if k in only}
    if not found:
        raise BenchError("there are no benchmark scenes")
    return list(found.values())


def settings_fingerprint(project: Project) -> dict:
    """What a run depended on, so a comparison can say what changed between two runs."""
    cfg = project.config
    w = cfg.models.writer
    return {
        "writer_model": w.model, "writer_temperature": w.temperature if not isinstance(w.temperature, list) else w.temperature[0],
        "prompt:prose": fingerprint(template_path("prose", project.root).read_text(encoding="utf-8")),
        "prompt:prose_system": fingerprint(template_path("prose_system", project.root).read_text(encoding="utf-8")),
        "style": fingerprint(voice_excerpt(project)),
        "banned": fingerprint(scenefiles.read(project.root / cfg.qc.banned_phrases) or ""),
    }


def experiments_dir(project: Project) -> Path:
    return project.root / "workbench" / "experiments"


def _check_context(project: Project, b: Benchmark) -> CheckContext:
    cfg = project.config
    return CheckContext(
        scene_words=b.words, pov=cfg.book.pov, tense=cfg.book.tense, language=cfg.book.language,
        banned=load_banned(scenefiles.read(project.root / cfg.qc.banned_phrases) or ""),
        names={b.slug(c.name): c.name for c in b.characters}, pov_id=b.slug(b.pov), qc=cfg.qc)


def stats_for(text: str, b: Benchmark, project: Project) -> dict:
    return _stats(text, b, project)


def _stats(text: str, b: Benchmark, project: Project) -> dict:
    report = check_scene(text, _check_context(project, b))
    return {"words": report.stats["words"], "score": report.score, "blocking": len(report.blocking), "warnings": len(report.warnings),
            "dialogue_ratio": round(report.stats["dialogue_ratio"], 3), "sentence_variation": report.stats["sentence_variation"],
            "issues": [i.message for i in report.blocking]}


@dataclass
class BenchRun:
    name: str
    directory: Path
    settings: dict
    results: dict[str, dict]
    texts: dict[str, str] = field(default_factory=dict)
    comparison: dict | None = None


def generate(ctx: StepContext, b: Benchmark, templates: dict[str, str] | None = None) -> str:
    """One draft of a benchmark brief. `templates` replaces prompt templates by name with candidate text (A/B tests)."""
    project = ctx.project
    templates = templates or {}
    values = {**prompt_values(project), "scene_id": b.id, "word_min": str(b.words[0]), "word_max": str(b.words[1])}

    def fill(name: str, **extra: str) -> str:
        if name in templates:
            return render_text(templates[name], name, **values, **extra)
        return render(name, project.root, **values, **extra)

    messages = [{"role": "system", "content": fill("prose_system")}, {"role": "user", "content": fill("prose", briefing=b.briefing(project))}]
    return ctx.llm.complete(project.config.layers["prose"].model, messages, draft=0, max_tokens=int(b.words[1] * 1.6) + 300).strip()


def run_bench(ctx: StepContext, only: list[str] | None = None) -> BenchRun:
    project = ctx.project
    if ctx.llm is None:
        raise BenchError("no model client available")
    stamp = "bench-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    name, n = stamp, 1
    while (experiments_dir(project) / name).exists():  # never overwrite an earlier run, the baseline least of all
        n += 1
        name = f"{stamp}-{n}"
    directory = experiments_dir(project) / name
    directory.mkdir(parents=True)
    run = BenchRun(name, directory, settings_fingerprint(project), {})
    for b in load_benchmarks(project, only):
        text = generate(ctx, b)
        (directory / f"{b.id}.md").write_text(text + "\n", encoding="utf-8")
        run.texts[b.id] = text
        run.results[b.id] = _stats(text, b, project)
    _save(run)
    return run


def _save(run: BenchRun) -> None:
    (run.directory / "results.json").write_text(json.dumps(
        {"name": run.name, "settings": run.settings, "results": run.results, "comparison": run.comparison}, indent=2, ensure_ascii=False), encoding="utf-8")


def accepted_run(project: Project) -> BenchRun | None:
    pointer = experiments_dir(project) / "bench-accepted.json"
    try:
        name = json.loads(pointer.read_text(encoding="utf-8"))["run"]
        directory = experiments_dir(project) / name
        data = json.loads((directory / "results.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError):
        return None
    texts = {i: (directory / f"{i}.md").read_text(encoding="utf-8").strip() for i in data["results"] if (directory / f"{i}.md").exists()}
    return BenchRun(name, directory, data.get("settings", {}), data["results"], texts)


def compare(ctx: StepContext, run: BenchRun, baseline: BenchRun, judge: bool = True) -> dict:
    """Per brief: the mechanical change and the judge's verdict (new / old / tie / unknown); then whether the change ships."""
    project = ctx.project
    by_id = {b.id: b for b in load_benchmarks(project)}
    rows, wins, losses, ties, regressions = {}, 0, 0, 0, []
    for bid, new in run.results.items():
        old = baseline.results.get(bid)
        if old is None or bid not in baseline.texts or bid not in by_id:
            rows[bid] = {"verdict": "no baseline"}
            continue
        row = {"score": [old["score"], new["score"]], "words": [old["words"], new["words"]], "blocking": [old["blocking"], new["blocking"]],
               "verdict": "not judged"}
        if new["blocking"] > old["blocking"]:
            regressions.append(f"{bid}: {new['blocking']} blocking problem(s), was {old['blocking']} ({'; '.join(new['issues'])[:120]})")
        if judge:
            try:
                winner, record = judge_pair(ctx, by_id[bid].scene(), "new", run.texts[bid], "old", baseline.texts[bid])
                row["verdict"] = {"new": "win", "old": "loss", None: "tie"}[winner]
                row["judge"] = record
            except BookforgeError as e:
                row["verdict"] = "unknown"
                row["error"] = str(e)
        wins += row["verdict"] == "win"
        losses += row["verdict"] == "loss"
        ties += row["verdict"] == "tie"
        rows[bid] = row
    changed = sorted(k for k in run.settings if run.settings.get(k) != baseline.settings.get(k))
    comparison = {"baseline": baseline.name, "changed": changed, "rows": rows, "wins": wins, "losses": losses, "ties": ties,
                  "regressions": regressions, "ships": not regressions and losses <= wins}
    run.comparison = comparison
    _save(run)
    return comparison


def accept(project: Project, run: BenchRun) -> None:
    pointer = experiments_dir(project) / "bench-accepted.json"
    pointer.write_text(json.dumps({"run": run.name, "accepted": datetime.now(timezone.utc).isoformat(timespec="seconds")}), encoding="utf-8")


def commit(project: Project, run: BenchRun, accepted: bool) -> None:
    if project.config.git.commit_each_step:
        paths = [str(run.directory.relative_to(project.root)), str((experiments_dir(project) / "bench-accepted.json").relative_to(project.root))]
        vcs.commit(project.root, f"bench: {run.name}" + (" accepted as the baseline" if accepted else ""), [p for p in paths if (project.root / p).exists()])
