"""The synopsis audit: the first half of the ledger stage (docs/BOOKFORGE.md, "Synopsis audit").

A model reads the whole synopsis with the cast and reports specific findings, each quoting the synopsis. A finding whose quotes are not in the
synopsis word for word is dropped: that is what keeps it from raising template or invented questions. Findings become author questions
(`AuthorQuestion.type` says which check raised them). Every kind of finding blocks: the ledger stage stops at its checkpoint until the author has answered them (BLOCKING_TYPES).

The author's answers are not written into the synopsis: they travel with the questions as notes, fed to the audit and to the extraction
as authoritative over the synopsis. A question whose quotes were already asked (in any state) is never asked again.
"""

import json
import logging

from ..ask import ask_until_valid
from ..bible import store
from ..bible.models import AuthorQuestion, Constants
from ..prompts import render
from ..qc.support import parse_json_object
from ..validators import audit as checks
from ..validators.ledger import _norm
from .document import prompt_values
from .runner import StepContext
from .. import steering

log = logging.getLogger("platform_bookforge.layers")

# Which kinds of finding stop the ledger stage until you have answered them. All of them: a name the cast lacks and a condition or motive
# that does not hold are as wrong as a contradiction, and building a ledger on them builds the problem into every later stage. One table, so
# a kind that turns out to be too noisy is one line to change (the dismissal rate per kind, in the suite report, says which).
BLOCKING_TYPES = ("contradiction", "unestablished_object", "cast_conflict", "unknown_name", "condition_order", "motive_gap")
TYPES = BLOCKING_TYPES


def next_question_id(questions: list[AuthorQuestion]) -> int:
    return 1 + max([int(q.id[1:]) for q in questions] or [0])


def notes_text(questions: list[AuthorQuestion]) -> str:
    """The author's answers so far, as notes."""
    answered = [q for q in questions if q.status == "answered" and q.answer.strip()]
    if not answered:
        return "none"
    return "\n".join(f"- About: {' / '.join(q.quotes) or q.question}\n  Decision: {q.answer.strip()}" for q in answered)


def _cast(project) -> tuple[Constants, str]:
    try:
        constants = store.load_constants(project)
    except Exception:  # a cast that does not load is not the audit's problem
        constants = Constants()
    text = "\n".join(f"- {e.id} ({e.kind}): {e.name}. " + "; ".join(e.facts[:3]) for e in constants.entities) or "none yet"
    return constants, text


def hints_text(synopsis: str, constants: Constants) -> str:
    parts = []
    for c in checks.causal_sentences(synopsis):
        parts.append(f"- condition or cause marker \"{c['marker']}\": {c['sentence']}")
    for n in checks.unknown_names(synopsis, constants):
        parts.append(f"- the name \"{n['name']}\" is in nobody's name in the cast: {n['sentence']}")
    absent = checks.cast_roles_absent(synopsis, constants)
    if absent:
        parts.append("- cast characters never named in this synopsis (maybe another name now fills their role): " + ", ".join(f"{a['name']} ({a['id']})" for a in absent))
    return "\n".join(parts) or "none"


def _validate(text: str) -> list[str]:
    data = parse_json_object(text)
    if data is None or not isinstance(data.get("findings"), list):
        return ['the reply must be one JSON object with a "findings" list (empty when the synopsis is coherent)']
    return []


def parse_findings(data: dict, synopsis: str) -> tuple[list[dict], int]:
    """(findings with exact quotes and a known type, how many were dropped)."""
    haystack, kept, dropped = _norm(synopsis), [], 0
    for f in data.get("findings") or []:
        if not isinstance(f, dict) or f.get("type") not in TYPES:
            dropped += 1
            continue
        quotes = [str(q).strip() for q in (f.get("quotes") or []) if str(q).strip()]
        if not quotes or any(_norm(q) not in haystack for q in quotes):
            dropped += 1  # not a verbatim quotation: not a finding
            continue
        kept.append({"type": f["type"], "quotes": quotes[:3], "why": str(f.get("why", "")).strip(), "fixes": [str(x).strip() for x in (f.get("fixes") or []) if str(x).strip()][:4]})
    return kept, dropped


def _key(quotes: list[str]) -> frozenset:
    return frozenset(_norm(q) for q in quotes)


def audit(ctx: StepContext, synopsis: str, questions: list[AuthorQuestion]) -> tuple[list[AuthorQuestion], dict]:
    """New questions for what the audit finds (never one already asked), and a summary {revision, findings: {type: n}, dropped}."""
    project = ctx.project
    if ctx.llm is None or not project.config.ledger.audit:
        return [], {}
    constants, cast_text = _cast(project)
    values = {**prompt_values(project), "synopsis": synopsis, "cast": cast_text, "carried": _carried(ctx), "notes": notes_text(questions),
              "hints": hints_text(synopsis, constants)}
    messages = [{"role": "system", "content": render("system", project.root, **values)},
                {"role": "user", "content": render("synopsis_audit", project.root, **values) + steering.addendum(project, "ledger")}]
    text = ask_until_valid(ctx, "ledger/audit", project.config.layers["ledger"].model, messages, _validate, {"max_tokens": 3500}, strip_preamble=False)
    found, dropped = parse_findings(json.loads(json.dumps(parse_json_object(text) or {})), synopsis)
    asked = {_key(q.quotes) for q in questions if q.quotes}
    new, n = [], next_question_id(questions)
    counts: dict[str, int] = {}
    for f in found:
        if _key(f["quotes"]) in asked:
            continue
        asked.add(_key(f["quotes"]))
        new.append(AuthorQuestion(id=f"q{n}", question=f"{_label(f['type'])}: " + " / ".join(f'"{q}"' for q in f["quotes"]), why=f["why"] or _label(f["type"]),
                                  options=f["fixes"], type=f["type"], quotes=f["quotes"]))
        counts[f["type"]] = counts.get(f["type"], 0) + 1
        n += 1
    return new, {"findings": counts, "dropped": dropped}


def _label(kind: str) -> str:
    return {"contradiction": "These cannot both be true", "unestablished_object": "Used before it is established", "cast_conflict": "The cast and the synopsis disagree",
            "condition_order": "The condition comes after what it conditions", "unknown_name": "A name that is not in the cast", "motive_gap": "Nothing makes this happen"}[kind]


def _carried(ctx: StepContext) -> str:
    from .direction import _ledger_text
    return _ledger_text(ctx)


def is_blocking(question: AuthorQuestion) -> bool:
    return question.type in BLOCKING_TYPES


def blocking(questions: list[AuthorQuestion]) -> list[AuthorQuestion]:
    """Open questions of a kind that stops the ledger stage until answered."""
    return [q for q in questions if q.status == "open" and is_blocking(q)]
