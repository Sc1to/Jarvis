"""`research-eval`: run every need of a story through the real research code and judge the outcome. Stores nothing.

Where `research-test` shows one question in detail, this answers the question that matters for a book: of what the story
needs, what share comes back as usable, period-appropriate facts, and are the claims honest. The needs are either proposed
now from a document (the premise, a north star, the synopsis: no layer has to have run) or taken from those already
recorded. Each lookup is run exactly as the pipeline runs it; every kept fact is then audited by a separate model call that
sees only the claim and its quote, so a claim that says more than its quote is caught even if the pipeline's own check missed it.
Run it on premises from different eras and places: tuning against one setting proves little.
"""

from dataclasses import dataclass, field

from ..errors import BookforgeError
from ..realism import realism_setting
from .notes import LOOKUP_STANCES, stores_for
from .step import Attempt, Question, answer_question, audit_claims, generate_questions

BAR = 0.5  # the share of lookups that should come back answered (the author's stated bar)
EVAL_FOCUS = "Everything this story needs to know about the real world or decide about its own world, before planning begins."


@dataclass
class Row:
    question: Question
    attempt: Attempt | None = None  # None for an invention: nothing is looked up
    unsupported: list[dict] = field(default_factory=list)  # KEPT facts that the separate audit says go beyond their quote, with why
    caught: list[dict] = field(default_factory=list)  # facts the pipeline's own audit dropped for going beyond their quote, with why
    audit_error: str = ""

    @property
    def lookup(self) -> bool:
        return self.question.stance in LOOKUP_STANCES

    @property
    def answered(self) -> bool:
        return bool(self.attempt and self.attempt.facts)


def recorded_questions(project) -> list[Question]:
    """The lookup needs already recorded for the series and the open book, as questions to run again."""
    out = []
    for store in stores_for(project).values():
        for n in store.needs():
            if n.stance in LOOKUP_STANCES and n.query:
                out.append(Question(n.question, n.query, n.sensitive, n.context, n.stance, n.reason, n.rule))
    return out


def propose(ctx, document: str, max_questions: int, realism: str | None = None) -> list[Question]:
    """The needs the model proposes for a story, optionally under a realism setting you give instead of the series' own."""
    return generate_questions(ctx, set(), EVAL_FOCUS, document, max_questions, realism)


def evaluate(ctx, web, questions: list[Question], document: str, audit: bool = True) -> list[Row]:
    seen_urls: set[str] = set()
    rows = []
    for q in questions:
        row = Row(q)
        if row.lookup:
            row.attempt = answer_question(ctx, web, q, document, seen_urls)
            row.caught = [d for p in row.attempt.pages for d in p.dropped if d.get("kind") == "support"]
            # The pipeline's own audit has already dropped what it found. A second audit here is only independent when that one is off.
            if audit and row.attempt.facts and not ctx.project.config.research.check_support:
                try:
                    row.unsupported = audit_claims(ctx, [f for _, f in row.attempt.facts])
                except BookforgeError as e:
                    row.audit_error = str(e)
        rows.append(row)
    return rows


def summarize(rows: list[Row]) -> dict:
    lookups = [r for r in rows if r.lookup]
    answered = sum(1 for r in lookups if r.answered)
    facts = sum(len(r.attempt.facts) for r in lookups if r.attempt)
    unsupported = sum(len(r.unsupported) for r in lookups)
    caught = sum(len(r.caught) for r in lookups)
    stances: dict[str, int] = {}
    for r in rows:
        stances[r.question.stance] = stances.get(r.question.stance, 0) + 1
    return {"needs": len(rows), "stances": stances, "lookups": len(lookups), "answered": answered, "facts": facts,
            "unsupported": unsupported, "caught": caught, "audit_errors": sum(1 for r in lookups if r.audit_error),
            "share": (answered / len(lookups)) if lookups else None,
            "decisions": sum(1 for r in rows if r.question.stance != "ground" and r.question.rule)}


def describe(rows: list[Row], source: str, realism: str, document_name: str) -> list[str]:
    lines = [f"source: {source}", f"needs from: {document_name}", f"realism: {realism or 'not stated'}", ""]
    if not rows:
        return lines + ["no needs were proposed"]
    lines.append(f"{'stance':<12} {'result':<18} question")
    for r in rows:
        q = r.question
        if not r.lookup:
            result = "to decide"
        elif r.answered:
            result = f"{len(r.attempt.facts)} fact(s)" + (f", {len(r.unsupported)} bad" if r.unsupported else "")
        else:
            result = "no answer"
        lines.append(f"{q.stance:<12} {result:<18} {q.question}")
        if q.reason:
            lines.append(f"{'':<12} {'':<18} why: {q.reason}")
        if q.rule:
            lines.append(f"{'':<12} {'':<18} proposed: {q.rule}")
        if r.lookup and r.attempt and not r.answered:
            lines.append(f"{'':<12} {'':<18} reason: {r.attempt.reason}")
        for hit, f in (r.attempt.facts if r.attempt else []):
            lines.append(f"{'':<12} {'':<18} + {f['claim']}  [{hit.url}]")
        for bad in r.caught:
            lines.append(f"{'':<12} {'':<18} x dropped by the audit: {bad['claim']}\n{'':<12} {'':<18}   {bad['why']}")
        for bad in r.unsupported:
            lines.append(f"{'':<12} {'':<18} ! UNSUPPORTED: {bad['claim']}\n{'':<12} {'':<18}   {bad['why']}")
        if r.audit_error:
            lines.append(f"{'':<12} {'':<18} (audit failed: {r.audit_error})")
    s = summarize(rows)
    lines += ["", "SUMMARY",
              f"  needs: {s['needs']} (" + ", ".join(f"{n} {k}" for k, n in sorted(s['stances'].items())) + ")",
              f"  decisions waiting for the author: {s['decisions']}"]
    if s["lookups"]:
        lines.append(f"  lookups answered: {s['answered']}/{s['lookups']} ({s['share']:.0%}); the bar is {BAR:.0%}: "
                     + ("MET" if s["share"] >= BAR else "MISSED"))
        lines.append(f"  facts kept: {s['facts']}; claims their quote does not support: {s['unsupported']} kept, {s['caught']} caught and dropped"
                     + (f" ({s['audit_errors']} audit(s) failed)" if s["audit_errors"] else ""))
    else:
        lines.append("  no lookups proposed")
    return lines


def bar_met(rows: list[Row]) -> bool:
    s = summarize(rows)
    return s["share"] is None or s["share"] >= BAR
