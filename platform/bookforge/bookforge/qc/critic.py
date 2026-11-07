"""Layer 3 of quality control: the critic scores the scene against a fixed rubric.

The big model scores six criteria from 1 to 5 and must quote the three weakest lines. A quote that
is not in the scene is rejected and asked for again, so the critique always points at real text.
The rubric is a prompt file (prompts/critic_rubric.md): to calibrate the critic against your own
reading, copy it to <series>/workbench/prompts/ and reword it.
"""

import re
from dataclasses import dataclass, field

from .. import rules
from ..bible.models import Scene
from ..errors import BookforgeError
from ..prompts import render
from .revise import Flag
from .support import ask_json, qc_options, qc_role, quote_in_page, scene_brief, voice_excerpt

CRITERIA = ("stakes", "voice", "show_dont_tell", "pacing", "dialogue", "beats_covered")
# About the scene as a whole: three patched lines cannot fix a missing beat or uneven pacing, only writing the scene again can.
WHOLE_SCENE = ("beats_covered", "pacing")
MIN_QUOTE_WORDS = 6


@dataclass
class Weak:
    criterion: str
    quote: str
    issue: str


@dataclass
class CriticReport:
    scores: dict[str, int] = field(default_factory=dict)
    weakest: list[Weak] = field(default_factory=list)
    error: str | None = None  # the critique could not be obtained; it does not block the scene

    @property
    def lowest(self) -> int:
        return min(self.scores.values()) if self.scores else 5

    def needs_work(self, minimum: int) -> bool:
        return bool(self.scores) and self.lowest < minimum

    def to_dict(self) -> dict:
        return {"scores": self.scores, "lowest": self.lowest if self.scores else None, "error": self.error,
                "weakest": [vars(w) for w in self.weakest]}


def rubric_line(project, criterion: str) -> str:
    text = render("critic_rubric", project.root)
    m = re.search(rf"^- {re.escape(criterion)}: (.+)$", text, re.MULTILINE)
    return m.group(1) if m else ""


def _check(scene_text: str):
    def check(data: dict) -> list[str]:
        problems = []
        scores = data.get("scores")
        if not isinstance(scores, dict):
            return ["'scores' must be an object with one whole-number score per criterion"]
        for c in CRITERIA:
            v = scores.get(c)
            if isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 5:
                problems.append(f"scores.{c} must be a whole number from 1 to 5")
        weakest = data.get("weakest")
        if not isinstance(weakest, list) or len(weakest) != 3:
            problems.append("'weakest' must list exactly three items")
            return problems
        for i, w in enumerate(weakest):
            if not isinstance(w, dict) or w.get("criterion") not in CRITERIA:
                problems.append(f"weakest[{i}].criterion must be one of: {', '.join(CRITERIA)}")
                continue
            quote = " ".join(str(w.get("quote", "")).split())
            if len(quote.split()) < MIN_QUOTE_WORDS:
                problems.append(f"weakest[{i}].quote must be at least {MIN_QUOTE_WORDS} words")
            elif not quote_in_page(quote, scene_text):
                problems.append(f"weakest[{i}].quote is not in the scene; copy the words exactly")
            if not str(w.get("issue", "")).strip():
                problems.append(f"weakest[{i}].issue must say what is wrong")
        return problems

    return check


def run_critic(ctx, scene: Scene, text: str) -> CriticReport:
    project = ctx.project
    try:
        data = ask_json(ctx, f"{scene.id} critic", qc_role(project), "critic", _check(text), max_tokens=900,
                        call_options=qc_options(project),
                        rubric=render("critic_rubric", project.root).strip(), brief=scene_brief(project, scene),
                        voice=voice_excerpt(project), text=text, rules=rules.prose_rules_text(project, scene) or "(none)")
    except BookforgeError as e:
        return CriticReport(error=str(e))
    weakest = [Weak(w["criterion"], " ".join(w["quote"].split()), str(w["issue"]).strip()) for w in data["weakest"]]
    return CriticReport(scores={c: data["scores"][c] for c in CRITERIA}, weakest=weakest)


def critic_flags(project, report: CriticReport) -> list[Flag]:
    """The critic's three weakest lines as revision flags, each with the rubric line it falls under."""
    return [Flag(source="critic", code=f"critic:{w.criterion}", criterion=w.criterion, quote=w.quote,
                 message=f"{w.issue} (criterion {w.criterion}: {rubric_line(project, w.criterion)})")
            for w in report.weakest]
