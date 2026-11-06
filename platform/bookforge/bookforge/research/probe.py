"""`research-test`: one question, end to end, with everything that happened shown.

It runs the same function the pipeline uses for each question (`answer_question`), against the configured search
source, and stores nothing. Use it to see what was searched, which pages were read, what the model reported, why a fact
was dropped (its quote was not on the page, or it did not fit the setting), and so to tune sources and settings in a
minute instead of rerunning a whole layer.
"""

from .step import Attempt, Question


def source_of(web) -> str:
    return getattr(web, "source_name", type(web).__name__)


def describe(attempt: Attempt, q: Question, source: str, show_pages: bool = False) -> list[str]:
    lines = [f"source: {source}", f"question: {q.question}", f"searched for: {q.query}", f"setting: {q.context or '(none)'}", ""]
    lines.append(f"{len(attempt.hits)} result(s):")
    for h in attempt.hits:
        lines.append(f"  - {h.title or '(no title)'}  {h.url}")
    for s in attempt.skipped:
        lines.append(f"  (not read: {s})")
    if attempt.order:
        lines.append("")
        chosen = f"the first {attempt.picked} chosen by the model from titles and excerpts, the rest" if attempt.picked else "all"
        lines.append(f"reading order ({chosen} by word match; rank = question, era and place words found in the title and excerpt):")
        for h, score in attempt.order:
            lines.append(f"  rank {score}  {h.title or h.url}")
    lines.append("")
    if not attempt.pages:
        lines.append("no page was read")
    for p in attempt.pages:
        if p.error:
            lines.append(f"page {p.url}\n  FAILED: {p.error}")
            continue
        cut = f", the {p.excerpt_chars} most relevant characters shown to the model" if p.excerpt_chars < p.chars else ""
        lines.append(f"page {p.url}\n  {p.chars} characters{cut}")
        lines.append(f"  the model reported {p.model_facts} fact(s): {p.quote_rejected} dropped (quote not on the page), "
                     f"{p.fit_rejected} dropped (does not fit the question and setting), {len(p.kept)} kept")
        for f in p.kept:
            lines.append(f"    + {f['claim']}\n      quote: \"{f['quote']}\"")
        for f in p.dropped:
            lines.append(f"    - dropped: {f['claim']}\n      why: {f['why']}\n      quote: \"{f['quote']}\"")
        if show_pages:
            lines.append("  ---- text shown to the model ----")
            lines.extend("  | " + ln for ln in (p.shown or "(nothing)").splitlines())
            lines.append("  ---- the model's raw reply ----")
            lines.extend("  | " + ln for ln in (p.reply or "(nothing)").splitlines())
            lines.append("  ----")
    lines.append("")
    lines.append(f"RESULT: {len(attempt.facts)} fact(s) kept" if attempt.facts else f"RESULT: no facts. {attempt.reason}")
    return lines
