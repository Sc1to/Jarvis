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
from ..validators import HARD, Finding, accepted
from ..validators.findings import soft as _soft
from ..validators import ledger as ledger_checks
from ..validators import store as findings_store
from .. import steering
from .direction import _ledger_text
from .document import prompt_values
from . import audit as audit_mod
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


def soft_finding(code: str, message: str) -> Finding:
    return _soft("ledger", code, message)


def attempt_path(project):
    return project.book_dir / "validation" / "ledger_attempt.json"


def load_attempt_events(project) -> list[dict]:
    """The events of the last ledger attempt that failed its checks (nothing is saved to ledger.yaml then), for the Inbox's suggestions."""
    import json
    try:
        return json.loads(attempt_path(project).read_text(encoding="utf-8")).get("events", [])
    except (OSError, ValueError):
        return []


def _remember_attempt(project, plain: list[dict] | None) -> None:
    import json
    path = attempt_path(project)
    if plain is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"events": plain}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def parse_ledger(text: str, synopsis: str, project, prior: Ledger | None = None) -> tuple[Ledger | None, list[str], list[Finding]]:
    """(ledger, hard problems, all findings). With `prior`, this is a revision: its synopsis events must come back unchanged."""
    data, error = load_reply_yaml(text)
    if error:
        return None, [error], []
    problems: list[str] = []
    if not isinstance(data, dict) or not isinstance(data.get("events"), list):
        return None, ["the top level must be a mapping with an 'events:' list"], []
    ledger_checks.resolve_references(data["events"])  # an event's text written where its id belongs is mapped back to the id
    from ..bible import repair as plan_repair
    repairs = plan_repair.repair_unknown_after(data["events"])  # a dependency on an event that does not exist is dropped
    repairs += plan_repair.repair_event_order(data["events"])  # an event listed before one it must follow is moved after it
    repairs += ledger_checks.repair_setups(data["events"])  # reversed or unmarked setup/payoff pairs are put right
    repairs += ledger_checks.repair_excerpts(data["events"], synopsis)  # an excerpt that is not a quotation points at the sentence it came from
    from .. import answers as answers_mod, resolve
    decided = answers_mod.load(project)
    if decided["mode"] in ("assist", "auto") or decided["accepted"]:  # housekeeping: a sentence an event already tells, or elaborates, is attached to it (in shadow mode only what you accepted)
        repairs += resolve.repair_coverage(data["events"], synopsis, decided, set(resolve.demoted(project)) if decided["mode"] != "shadow" else set())
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
    links, unresolved = ledger_checks.link_payoffs_by_meaning(plain)  # a payoff the extraction left unlinked is linked by meaning, not asked about
    if links:
        events = [StoryEvent.model_validate(p) for p in plain]
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
    waived = [{"quote": str(q.get("quote", "")).strip(), "reason": str(q.get("reason", "")).strip()} for q in (data.get("no_event_needed") or []) if isinstance(q, dict) and str(q.get("quote", "")).strip()]
    waived += [w for w in decided["waived"] if not any(w["quote"] == x["quote"] for x in waived)]  # what the tool waived and you did not take back
    findings = ledger_checks.check_ledger(plain, synopsis, no_event_needed=waived)
    problems += accepted.hard_lines(project, findings, "ledger")
    findings += [soft_finding("auto_repaired", note) for note in repairs + links]
    # A setup nothing pays off is the author's call, not a failure: it becomes a question (once per setup).
    known = [q.question for q in questions] + ([q.question for q in prior.questions] if prior else [])
    next_n = 1 + max([int(q.id[1:]) for q in questions + (prior.questions if prior else [])] or [0])
    for f in findings:
        if f.code == "setup_without_payoff":
            event = next(e for e in plain if e["id"] == f.items[0])
            if not any(q.startswith(f"Setup {event['id']} ") for q in known):
                questions.append(AuthorQuestion(id=f"q{next_n}", **ledger_checks.unpaid_setup_question(event, unresolved.get(event["id"]))))
                next_n += 1

    cfg = project.config.ledger
    cap = capacity(plain, cfg.weight_per_chapter, cfg.min_chapters)
    open_q = [q for q in questions if q.status == "open"] + ([q for q in prior.questions if q.status == "open"] if prior else [])
    if cap["thin"] and not open_q:
        problems.append(f"the synopsis carries about {cap['estimated_chapters']} chapters of story ({cap['formula']}; minimum {cap['minimum_chapters']}). "
                        "Do not pad: add `questions` saying what is missing, each with proposed complications for the author to choose from")
    _remember_attempt(project, plain if problems else None)
    if problems:
        return None, problems, findings
    ledger = Ledger(events=events, questions=questions, thin=cap["thin"], capacity=cap, revision=prior.revision if prior else 1, no_event_needed=waived or (prior.no_event_needed if prior else []))
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


def generate(ctx: StepContext, synopsis: str, notes: str = "none") -> tuple[Ledger, list[Finding]]:
    project = ctx.project
    if ctx.llm is None:
        raise LayerError("no model client available")
    stars = {"series_north_star": (project.root / "north-star.md").read_text(encoding="utf-8").strip(),
             "book_north_star": (project.book_dir / "north-star.md").read_text(encoding="utf-8").strip()}
    messages = _messages(project, "ledger", synopsis=synopsis, carried=_ledger_text_for(ctx), notes=notes, **stars)
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
    if ledger.audit:
        lines.append(f"\nSynopsis audit: {sum((ledger.audit.get('findings') or {}).values())} finding(s) {ledger.audit.get('findings') or {}}; {ledger.audit.get('dropped', 0)} dropped (no exact quote)")
    if ledger.questions:
        lines.append("\nQuestions for the author:")
        for q in ledger.questions:
            lines.append(f"  {q.id} [{q.status}{', ' + q.type if q.type else ''}] {q.question}\n      why: {q.why}" + "".join(f"\n      - {o}" for o in q.options)
                         + (f"\n      answer: {q.answer}" if q.answer else ""))
    if findings:
        lines.append("\nChecks:")
        lines += [f"  [{f.severity}] {f.line()}" for f in findings]
    return "\n".join(lines)


def _question(project, question_id: str):
    from ..errors import BookforgeError
    ledger = store.load_ledger(project)
    if ledger is None:
        raise BookforgeError("this book has no ledger yet")
    q = next((x for x in ledger.questions if x.id == question_id), None)
    if q is None:
        raise BookforgeError(f"no question {question_id} (have: {', '.join(x.id for x in ledger.questions) or 'none'})")
    return ledger, q


def answer_question(project, question_id: str, answer: str) -> Ledger:
    """Record the author's answer to a ledger question (or change an answer the next run has not applied yet). The next run works it in.
    The one function behind `ledger-answer`, the Inbox and the workbench: nothing else writes an answer."""
    from ..errors import BookforgeError
    ledger, q = _question(project, question_id)
    if not answer.strip():
        raise BookforgeError("the answer is empty")
    if q.applied:
        raise BookforgeError(f"{question_id} was already worked into the ledger by a run; it can no longer be changed here (edit ledger.yaml, or answer a new question)")
    q.answer, q.status, q.applied, q.dismiss_reason, q.decided_by = answer.strip(), "answered", False, "", ""
    store.save_ledger(project, ledger)
    return ledger


def dismiss_question(project, question_id: str, reason: str = "") -> Ledger:
    """Dismiss a question: a false alarm, or one not worth an answer. The reason (optional) is kept and the dismissal counts toward its type's rate."""
    from ..errors import BookforgeError
    ledger, q = _question(project, question_id)
    if q.applied:
        raise BookforgeError(f"{question_id} was already worked into the ledger by a run; it can no longer be dismissed")
    q.status, q.answer, q.dismiss_reason = "dismissed", "", " ".join(reason.split())[:300]
    store.save_ledger(project, ledger)
    return ledger


def diff_events(before: list[StoryEvent], after: list[StoryEvent]) -> tuple[list[dict], list[dict]]:
    """(events that are new, events whose text changed) between two versions of the ledger."""
    old = {e.id: e for e in before}
    added = [{"id": e.id, "text": e.text, "source": e.source} for e in after if e.id not in old]
    revised = [{"id": e.id, "before": old[e.id].text, "after": e.text} for e in after if e.id in old and old[e.id].text != e.text]
    return added, revised


def _last_run(kind: str, before: Ledger | None, after: Ledger, applied: list[str]) -> dict:
    """What this run changed, for the Inbox: the answers it applied, the events it added or revised, the questions it raised."""
    from datetime import datetime, timezone
    added, revised = diff_events(before.events if before else [], after.events)
    known = {q.id for q in before.questions} if before else set()
    return {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "kind": kind, "revision": after.revision, "applied": applied, "added": added, "revised": revised,
            "new_questions": [q.id for q in after.questions if q.id not in known], "events": len(after.events)}


def _reset_downstream(project) -> list[str]:
    """The ledger has new events, so the acts, chapters and scenes planned from the old ones are no longer the plan: they are put back to pending (to be
    planned again from this ledger in the same run), after a copy of each file is kept. Written prose is never touched: with scenes written, nothing is reset
    and the Inbox says so. Returns the layers reset."""
    from .. import steering, versions
    from ..constants import LAYER_CHECKPOINTS, REDO_NOTE
    from ..state import Checkpoint
    from .structure import _clean_work
    stale = [l for l in ("acts", "chapters", "scenes") if project.state.layers[l].status != "pending"]
    if not stale or any(project.book_dir.glob("scenes/*/*/final.md")) or any(project.book_dir.glob("scenes/*/*/revised.md")):
        return []
    versions.keep(project, [f for l in stale for f in versions.layer_files(project, l)], "before-reset-by-new-ledger")
    for l in stale:
        project.state.set_layer_status(l, "pending", REDO_NOTE)
        _clean_work(project, l)
        steering.clear(project, l)
    project.state.items = {}
    for cp in LAYER_CHECKPOINTS:
        if cp != "ledger" and any(project.config.layers[l].checkpoint == cp for l in stale):
            project.state.checkpoints[cp] = Checkpoint()
    return stale


def ledger(ctx: StepContext) -> StepResult:
    project = ctx.project
    path = store.ledger_path(project)
    rel = store.rel(project, path)
    synopsis = project.resolve(f"books/{project.book}/synopsis.md").read_text(encoding="utf-8").strip()
    redoing = project.state.layers["ledger"].note == REDO_NOTE
    changed = False  # this run made new events: what was planned from the old ones is stale
    try:
        existing = None if redoing else store.load_ledger(project)
    except store.BibleError as e:
        raise LayerError(f"{e} (fix the file, or delete it to have it regenerated)") from e

    if existing is None or not existing.events:
        # The synopsis audit comes first. Contradictions, missing prerequisites and cast conflicts stop here, at the checkpoint, until answered.
        prior = existing.questions if existing else []
        if prior and project.state.checkpoints["ledger"].status == "approved":
            prior = [q.model_copy(update={"status": "dismissed"}) if q.status == "open" else q for q in prior]  # approving means: go on as it is
        new_q, summary = audit_mod.audit(ctx, synopsis, prior)
        questions = prior + new_q
        blockers = audit_mod.blocking(questions)
        if blockers:
            questions = [q.model_copy(update={"applied": True}) if q.status == "answered" else q for q in questions]  # their notes went into this audit
            led = Ledger(events=[], questions=questions, last_run=_last_run("audit", existing, Ledger(events=[], questions=questions), [q.id for q in prior if q.status == "answered" and not q.applied]), audit={**summary, "revision": 1 + int((existing.audit if existing else {}).get("revision", 0))})
            store.save_ledger(project, led)
            files = [rel, findings_store.save(project, "ledger", [soft_finding("synopsis_audit", f"{q.id} ({q.type}): {q.question}") for q in blockers])]
            return StepResult(files=files, outcome="partial", checkpoint="ledger",
                              note=f"the synopsis audit found {len(blockers)} problem(s) in the synopsis itself: answer them in the Inbox (or with `ledger-answer`), then run again "
                                   f"(or approve the ledger checkpoint to go on as it is): " + "; ".join(f"{q.id} {q.type}" for q in blockers))
        applied_now = [q.id for q in questions if q.status == "answered" and not q.applied]
        answered = [q.model_copy(update={"applied": True}) if q.status == "answered" else q for q in questions]
        led, findings = generate(ctx, synopsis, audit_mod.notes_text(answered))
        base = audit_mod.next_question_id(answered)
        renumbered = [q.model_copy(update={"id": f"q{base + i}", "type": q.type or "thin"}) for i, q in enumerate(led.questions)]  # the extraction's own questions continue the numbering
        led.questions = answered + renumbered
        led.audit = {**summary, "revision": 1 + int((existing.audit if existing else {}).get("revision", 0))}
        led.last_run = _last_run("extract", existing, led, applied_now)
        note = "extracted from the synopsis"
        changed = True
    elif any(q.status == "answered" and not q.applied for q in existing.questions):
        applied_now = [q.id for q in existing.questions if q.status == "answered" and not q.applied]
        led, findings = revise(ctx, synopsis, existing)
        led.last_run = _last_run("revise", existing, led, applied_now)
        note = f"revised from your answers (revision {led.revision})"
        changed = True
    else:
        led = existing
        if any(q.status == "open" for q in led.questions) and project.state.checkpoints["ledger"].status == "approved":
            for q in led.questions:
                if q.status == "open":
                    q.status = "dismissed"
        plain = [to_plain(e) for e in led.events]
        findings = ledger_checks.check_ledger(plain, synopsis, no_event_needed=led.no_event_needed)
        problems = [f.line() for f in findings if f.severity == HARD]
        if problems:
            raise LayerError("the existing ledger.yaml is not acceptable: " + "; ".join(problems[:6]) + " (fix the file, or delete it to have it regenerated)")
        led.capacity = capacity(plain, project.config.ledger.weight_per_chapter, project.config.ledger.min_chapters)
        led.thin = led.capacity["thin"]
        note = "adopted existing file"

    if existing is None or (existing is not None and [e.id for e in existing.events] != [e.id for e in led.events]):
        from .. import versions
        versions.keep(project, [store.ledger_path(project)], "ledger-before-new-version")  # the ledger as it was before this run replaced it
    store.save_ledger(project, led)
    files = [rel, findings_store.save(project, "ledger", findings, {"capacity": led.capacity})]
    if changed and led.events:
        reset = _reset_downstream(project)
        if reset:
            note += f"; {', '.join(reset)} were planned from the earlier ledger and will be planned again from this one (the earlier files are kept under previous/)"
    open_q = [q for q in led.questions if q.status == "open"]
    if open_q:
        return StepResult(files=files, outcome="partial", checkpoint="ledger",
                          note=f"{len(led.events)} events; {len(open_q)} question(s) for you in {rel}. Answer them with `ledger-answer`, then run again "
                               f"(or approve the ledger checkpoint to go on without)")
    cap = led.capacity
    return StepResult(files=files, note=f"{len(led.events)} events, about {cap.get('estimated_chapters')} chapters of story ({note})")
