"""The story-event ledger: layer between the synopsis and the acts (docs/BOOKFORGE.md, "Story-event ledger").

The synopsis is extracted into numbered events (`books/<book>/ledger.yaml`). Every later stage works from these events, and the
validators check each stage against them. The ledger holds only what the synopsis says: a thin synopsis produces author
questions with proposed complications and stops at the `ledger` checkpoint instead of being padded.

How the author's answers revise the ledger:
1. `run` writes ledger.yaml. If the synopsis carries too little for a novel (see `capacity`), the ledger has open `questions`
   and the layer stops at the ledger checkpoint (status drafted, nothing downstream runs).
2. The author answers: `ledger-answer <series> q1 "text"` (or edits `answer:` in ledger.yaml). The question becomes `answered`.
3. The next `run` asks the model to work each answer into new events with `source: author`, keeping every synopsis event
   as it was. The ledger validators run again on the result (a failed check is fed back, at most `qc.max_revision_rounds`
   times, and a hard finding that survives stops the layer). The question is marked `applied`, `revision` goes up, `capacity` is recomputed.
4. Still thin: new questions, back to step 2. Not thin: the layer is accepted and the ledger checkpoint waits for approval.
5. Approving the checkpoint while questions are still open means "go on as it is": they are dismissed and the ledger is accepted.
"""

import logging

from pydantic import ValidationError

from ..ask import ask_until_valid
from ..bible import store
from ..bible.models import AuthorQuestion, Ledger, StoryEvent, problems_from
from ..bible.store import dump_yaml, to_plain
from ..bible.validate import load_reply_yaml
from ..constants import REDO_NOTE
from ..errors import LayerError
from ..prompts import render
from ..validators import HARD, Finding
from ..validators import ledger as ledger_checks
from ..validators import store as findings_store
from .. import steering
from .direction import _ledger_text
from .document import prompt_values
from .runner import StepContext, StepResult

log = logging.getLogger("platform_bookforge.layers")


def capacity(events: list[dict], weight_per_chapter: float, min_chapters: int) -> dict:
    """How much novel the synopsis carries. Only events of the synopsis (and the author's) count: complications the planner
    derives later never rescue a thin synopsis."""
    counted = [e for e in events if e.get("source", "synopsis") != "derived" and not e.get("carried_in")]
    weight = sum(int(e.get("weight", 1)) for e in counted)
    estimated = weight / weight_per_chapter
    return {
        "formula": "estimated_chapters = total_weight / weight_per_chapter; thin when estimated_chapters < minimum_chapters",
        "events": len(counted), "total_weight": weight, "weight_per_chapter": weight_per_chapter,
        "estimated_chapters": round(estimated, 1), "minimum_chapters": min_chapters, "thin": estimated < min_chapters,
    }


def parse_ledger(text: str, synopsis: str, project, prior: Ledger | None = None) -> tuple[Ledger | None, list[str], list[Finding]]:
    """(ledger, hard problems, all findings). With `prior`, this is a revision: its synopsis events must come back unchanged."""
    data, error = load_reply_yaml(text)
    if error:
        return None, [error], []
    problems: list[str] = []
    if not isinstance(data, dict) or not isinstance(data.get("events"), list):
        return None, ["the top level must be a mapping with an 'events:' list"], []
    ledger_checks.resolve_references(data["events"])  # an event's text written where its id belongs is mapped back to the id
    events: list[StoryEvent] = []
    for i, raw in enumerate(data["events"]):
        try:
            events.append(StoryEvent.model_validate(raw))
        except ValidationError as e:
            problems += [f"events[{i}].{p}" for p in problems_from(e, limit=3)]
    questions: list[AuthorQuestion] = []
    for i, raw in enumerate(data.get("questions") or []):
        try:
            questions.append(AuthorQuestion.model_validate(raw))
        except ValidationError as e:
            problems += [f"questions[{i}].{p}" for p in problems_from(e, limit=3)]
    if problems:
        return None, problems, []

    plain = [to_plain(e) for e in events]
    if prior is not None:
        now = {e.id: e for e in events}
        for old in prior.events:
            kept = now.get(old.id)
            if kept is None or kept.text != old.text or kept.excerpt != old.excerpt:
                problems.append(f"event {old.id} must stay exactly as it was (same id, text and excerpt); it was {'removed' if kept is None else 'changed'}")
        for e in events:
            if e.id not in {o.id for o in prior.events} and e.source != "author":
                problems.append(f"new event {e.id} must have source: author")
        if any(q.id in {p.id for p in prior.questions} for q in questions):
            problems.append("new questions need new ids (continue the numbering); do not repeat existing questions")
    findings = ledger_checks.check_ledger(plain, synopsis)
    problems += [f.line() for f in findings if f.severity == HARD]

    cfg = project.config.ledger
    cap = capacity(plain, cfg.weight_per_chapter, cfg.min_chapters)
    open_q = [q for q in questions if q.status == "open"] + ([q for q in prior.questions if q.status == "open"] if prior else [])
    if cap["thin"] and not open_q:
        problems.append(f"the synopsis carries about {cap['estimated_chapters']} chapters of story ({cap['formula']}; minimum {cap['minimum_chapters']}). "
                        "Do not pad: add `questions` saying what is missing, each with proposed complications for the author to choose from")
    if problems:
        return None, problems, findings
    ledger = Ledger(events=events, questions=questions, thin=cap["thin"], capacity=cap, revision=prior.revision if prior else 1)
    return ledger, [], findings


def _messages(project, template: str, **slots) -> list[dict]:
    values = {**prompt_values(project), **slots}
    note = steering.addendum(project, "ledger")
    return [{"role": "system", "content": render("system", project.root, **values)},
            {"role": "user", "content": render(template, project.root, **values) + note}]


def _options(ctx: StepContext) -> dict:
    options: dict = {"max_tokens": 7000}
    t = ctx.project.config.layers["ledger"].temperature
    if t is not None:
        options["temperature"] = t
    return options


def generate(ctx: StepContext, synopsis: str) -> tuple[Ledger, list[Finding]]:
    project = ctx.project
    if ctx.llm is None:
        raise LayerError("no model client available")
    stars = {"series_north_star": (project.root / "north-star.md").read_text(encoding="utf-8").strip(),
             "book_north_star": (project.book_dir / "north-star.md").read_text(encoding="utf-8").strip()}
    messages = _messages(project, "ledger", synopsis=synopsis, carried=_ledger_text_for(ctx), **stars)
    box: dict = {}

    def validate(text: str) -> list[str]:
        ledger, problems, findings = parse_ledger(text, synopsis, project)
        box["ledger"], box["findings"] = ledger, findings
        return problems

    ask_until_valid(ctx, "ledger", project.config.layers["ledger"].model, messages, validate, _options(ctx), strip_preamble=False)
    return box["ledger"], box["findings"]


def _ledger_text_for(ctx: StepContext) -> str:
    return _ledger_text(ctx)


def revise(ctx: StepContext, synopsis: str, ledger: Ledger) -> tuple[Ledger, list[Finding]]:
    project = ctx.project
    answered = [q for q in ledger.questions if q.status == "answered" and not q.applied]
    answers = "\n\n".join(f"{q.id}: {q.question}\nAnswer: {q.answer.strip()}" for q in answered)
    messages = _messages(project, "ledger_revise", synopsis=synopsis, ledger=dump_yaml(to_plain(ledger)), answers=answers)
    box: dict = {}

    def validate(text: str) -> list[str]:
        merged, problems, findings = parse_ledger(text, synopsis, project, prior=ledger)
        box["ledger"], box["findings"] = merged, findings
        return problems

    ask_until_valid(ctx, "ledger/revise", project.config.layers["ledger"].model, messages, validate, _options(ctx), strip_preamble=False)
    revised: Ledger = box["ledger"]
    done = [q.model_copy(update={"applied": q.status == "answered" or q.applied}) for q in ledger.questions]
    revised.questions = done + revised.questions
    revised.revision = ledger.revision + 1
    return revised, box["findings"]


def report_text(ledger: Ledger, findings: list[Finding]) -> str:
    cap = ledger.capacity or {}
    lines = [f"Ledger: {len(ledger.events)} events, revision {ledger.revision}",
             f"Capacity: {cap.get('formula', '')}",
             f"          total_weight {cap.get('total_weight')} / weight_per_chapter {cap.get('weight_per_chapter')} = "
             f"{cap.get('estimated_chapters')} chapters; minimum {cap.get('minimum_chapters')}; thin: {cap.get('thin')}", ""]
    for e in ledger.events:
        flags = [f for f in (("once" if e.once_only else "repeatable"), e.kind, f"w{e.weight}", "ENDING" if e.ending else "",
                             f"pays {e.pays_off}" if e.pays_off else "", e.source if e.source != "synopsis" else "") if f]
        lines.append(f"  {e.id:<6} {', '.join(flags):<32} {e.text}")
    if ledger.questions:
        lines.append("\nQuestions for the author:")
        for q in ledger.questions:
            lines.append(f"  {q.id} [{q.status}] {q.question}\n      why: {q.why}" + "".join(f"\n      - {o}" for o in q.options)
                         + (f"\n      answer: {q.answer}" if q.answer else ""))
    if findings:
        lines.append("\nChecks:")
        lines += [f"  [{f.severity}] {f.line()}" for f in findings]
    return "\n".join(lines)


def answer_question(project, question_id: str, answer: str) -> Ledger:
    """Record the author's answer to a ledger question. The next run revises the ledger from it."""
    from ..errors import BookforgeError
    ledger = store.load_ledger(project)
    if ledger is None:
        raise BookforgeError("this book has no ledger yet")
    q = next((x for x in ledger.questions if x.id == question_id), None)
    if q is None:
        raise BookforgeError(f"no question {question_id} (have: {', '.join(x.id for x in ledger.questions) or 'none'})")
    if not answer.strip():
        raise BookforgeError("the answer is empty")
    q.answer, q.status, q.applied = answer.strip(), "answered", False
    store.save_ledger(project, ledger)
    return ledger


def ledger(ctx: StepContext) -> StepResult:
    project = ctx.project
    path = store.ledger_path(project)
    rel = store.rel(project, path)
    synopsis = project.resolve(f"books/{project.book}/synopsis.md").read_text(encoding="utf-8").strip()
    redoing = project.state.layers["ledger"].note == REDO_NOTE
    try:
        existing = None if redoing else store.load_ledger(project)
    except store.BibleError as e:
        raise LayerError(f"{e} (fix the file, or delete it to have it regenerated)") from e

    if existing is None:
        led, findings = generate(ctx, synopsis)
        note = "extracted from the synopsis"
    elif any(q.status == "answered" and not q.applied for q in existing.questions):
        led, findings = revise(ctx, synopsis, existing)
        note = f"revised from your answers (revision {led.revision})"
    else:
        led = existing
        if any(q.status == "open" for q in led.questions) and project.state.checkpoints["ledger"].status == "approved":
            for q in led.questions:
                if q.status == "open":
                    q.status = "dismissed"
        plain = [to_plain(e) for e in led.events]
        findings = ledger_checks.check_ledger(plain, synopsis)
        problems = [f.line() for f in findings if f.severity == HARD]
        if problems:
            raise LayerError("the existing ledger.yaml is not acceptable: " + "; ".join(problems[:6]) + " (fix the file, or delete it to have it regenerated)")
        led.capacity = capacity(plain, project.config.ledger.weight_per_chapter, project.config.ledger.min_chapters)
        led.thin = led.capacity["thin"]
        note = "adopted existing file"

    store.save_ledger(project, led)
    files = [rel, findings_store.save(project, "ledger", findings, {"capacity": led.capacity})]
    open_q = [q for q in led.questions if q.status == "open"]
    if open_q:
        return StepResult(files=files, outcome="partial", checkpoint="ledger",
                          note=f"{len(led.events)} events; {len(open_q)} question(s) for you in {rel}. Answer them with `ledger-answer`, then run again "
                               f"(or approve the ledger checkpoint to go on without)")
    cap = led.capacity
    return StepResult(files=files, note=f"{len(led.events)} events, about {cap.get('estimated_chapters')} chapters of story ({note})")
