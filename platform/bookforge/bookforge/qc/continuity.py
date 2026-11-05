"""Layer 2 of quality control: does the scene agree with the story state, the cast and the world?

One yes/no question per relevant fact, as the design says: every tracked state at the scene, the
fixed facts of the people and places in it, the rules of the world, and the research facts it cites.
Changes marked must_show get a "shown" question: does the change actually happen on the page?

A "yes" to a contradiction question is a flag only if the quoted evidence really is in the text;
otherwise it is only an "unsure". P(contradiction) is the confidence for a yes and 1 - confidence for
a no; above `qc.continuity_flag_threshold` a no is reported as unsure, never revised. A must_show
change that is not shown cannot be repaired by rewriting one passage, so it is not fixable: the
scene is left for the author.
"""

from dataclasses import dataclass, field

from .. import rules
from ..bible import store
from ..bible.lookup import scene_entities, state_at
from ..bible.models import Scene
from ..errors import BookforgeError
from ..research.notes import stores_for
from .decide import Answer, Question, ask_questions


@dataclass
class Flag:
    kind: str  # "contradiction" | "obligation"
    question: str
    evidence: str
    confidence: float
    p: float
    fixable: bool
    rule: str | None = None  # a hard_constraint rule from the rules panel

    def message(self) -> str:
        if self.kind == "obligation":
            return f"the scene does not show this on the page: {self.question}"
        return f"the scene contradicts a fixed fact: {self.question}"


@dataclass
class ContinuityReport:
    questions: int = 0
    flags: list[Flag] = field(default_factory=list)
    unsure: list[dict] = field(default_factory=list)
    error: str | None = None  # the check could not be completed; it does not block the scene

    def to_dict(self) -> dict:
        return {"questions": self.questions, "error": self.error, "flags": [vars(f) for f in self.flags], "unsure": self.unsure}


def build_questions(project, scene: Scene, scenes: list[Scene]) -> tuple[list[Question], dict[str, str]]:
    """The questions for a scene, and a map from question id to the plain fact it asks about."""
    constants = store.load_constants(project)
    tracks = store.load_tracks(project)
    names = {e.id: e.name for e in constants.entities}
    ids = scene_entities(scenes, scene.id)
    items: list[tuple[str, str, object]] = []  # (kind, text, the rule it comes from, if any)
    for s in state_at(tracks, scene.id, ids):
        fact = f"{names.get(s.entity, s.entity)} ({s.kind}): {s.value}"
        items.append(("contradiction", fact, None))
        if s.must_show:
            items.append(("shown", f"{names.get(s.entity, s.entity)}: {s.value}", None))
    for e in constants.entities:
        if e.id in ids:
            items += [("contradiction", f"{e.name}: {fact}", None) for fact in e.facts]
    items += [("contradiction", f"World rule: {r.text}", None) for r in constants.rules]
    items += [("contradiction", f"Author's rule {r.id}: {r.text}", r) for r in rules.rules_for(project, scene, ("hard_constraint",))]
    facts = {f.id: f for st in stores_for(project).values() for f in st.facts()}
    for fid in dict.fromkeys(scene.research):
        if fid in facts:
            items.append(("contradiction", f"Real-world fact: {facts[fid].claim}", None))
    cap = project.config.qc.continuity_max_questions
    questions = [Question(f"q{i}", kind, text, rule.severity if rule else "block", rule.id if rule else None)
                 for i, (kind, text, rule) in enumerate(items[:cap], 1)]
    return questions, {q.id: q.text for q in questions}


def _judge(q: Question, a: Answer, threshold: float) -> tuple[Flag | None, dict | None]:
    if q.kind == "shown":
        p_fail = a.confidence if not a.yes else 1 - a.confidence
        if p_fail > threshold:
            return Flag("obligation", q.text, "", a.confidence, round(p_fail, 2), fixable=False), None
        return None, None
    p = a.confidence if a.yes else 1 - a.confidence
    if a.yes and a.verified and p > threshold and q.severity == "block":
        return Flag("contradiction", q.text, a.evidence, a.confidence, round(p, 2), fixable=True, rule=q.rule), None
    if p > threshold:  # a "yes" without quotable evidence, or a hesitant "no": reported, not acted on
        return None, {"question": q.text, "answer": "yes" if a.yes else "no", "confidence": a.confidence, "evidence": a.evidence, "rule": q.rule}
    return None, None


def check_continuity(ctx, scene: Scene, scenes: list[Scene], text: str, what: str = "scene") -> ContinuityReport:
    project = ctx.project
    questions, _ = build_questions(project, scene, scenes)
    report = ContinuityReport(questions=len(questions))
    if not questions:
        return report
    cfg = project.config.qc
    try:
        answers = ask_questions(ctx, f"{scene.id} continuity", what, text, questions, cfg.continuity_batch_size)
    except BookforgeError as e:
        report.error = str(e)
        return report
    for q, a in zip(questions, answers):
        flag, unsure = _judge(q, a, cfg.continuity_flag_threshold)
        if flag:
            report.flags.append(flag)
        if unsure:
            report.unsure.append(unsure)
    return report
