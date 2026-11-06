"""Yes/no questions about a text, with a confidence, answered by a model.

This is the stand-in for the "System One" endpoint of the original design. Its request shape could
not be verified, so the planner model answers the questions instead. Its confidence is self-reported,
which is less reliable than a probability read from the model, so the thresholds are applied
conservatively (see continuity.py). Questions are sent in batches to keep the number of calls down.
"""

from dataclasses import dataclass

from .support import ask_json, quote_in_page


@dataclass
class Question:
    id: str
    kind: str  # "contradiction" (yes = the text clashes with the fact) or "shown" (yes = the change happens on the page)
    text: str
    severity: str = "block"  # for a rule from the rules panel: block | warn | note (warn and note are recorded, not revised)
    rule: str | None = None


# What the model may say about each kind of question. "yes" below (Answer.yes) means the outcome the question looks for: the scene
# contradicts the fact, or shows the change. Asking yes/no was the problem: a model answered "yes" meaning "the scene shows this fact"
# and quoted the words that CONFIRM it, so scenes that agreed with their facts were flagged. A relation has an explicit place for "agrees".
RELATIONS = {"contradiction": ("contradicts", "agrees", "silent"), "shown": ("shown", "not_shown")}
YES = {"contradicts", "shown"}


@dataclass
class Answer:
    id: str
    yes: bool
    confidence: float
    evidence: str = ""
    verified: bool = False  # the evidence really appears in the text
    relation: str = ""  # contradicts | agrees | silent (contradiction questions); shown | not_shown (shown questions)


def _check(questions: list[Question]):
    ids = {q.id for q in questions}
    kinds = {q.id: q.kind for q in questions}

    def check(data: dict) -> list[str]:
        answers = data.get("answers")
        if not isinstance(answers, list):
            return ["'answers' must be a list"]
        problems, seen = [], set()
        for i, a in enumerate(answers):
            if not isinstance(a, dict) or a.get("id") not in ids:
                problems.append(f"answers[{i}] does not name one of the questions ({', '.join(sorted(ids))})")
                continue
            seen.add(a["id"])
            allowed = RELATIONS[kinds[a["id"]]]
            if a.get("relation") not in allowed:
                problems.append(f"{a['id']}: 'relation' must be one of: {', '.join(allowed)}")
            c = a.get("confidence")
            if isinstance(c, bool) or not isinstance(c, (int, float)) or not 0 <= c <= 1:
                problems.append(f"{a['id']}: 'confidence' must be a number from 0.0 to 1.0")
        problems += [f"no answer for {q}" for q in sorted(ids - seen)]
        return problems

    return check


def ask_questions(ctx, label: str, what: str, text: str, questions: list[Question], batch_size: int) -> list[Answer]:
    """Answer every question about `text`, in batches. Raises LayerError if a batch cannot be answered properly."""
    out: list[Answer] = []
    for start in range(0, len(questions), batch_size):
        batch = questions[start: start + batch_size]
        listing = "\n".join(f"{q.id} [{q.kind}] {q.text}" for q in batch)
        data = ask_json(ctx, f"{label} questions {start + 1}-{start + len(batch)}", "critic", "continuity", _check(batch),
                        max_tokens=300 + 120 * len(batch), what=what, text=text, questions=listing)
        by_id = {a["id"]: a for a in data["answers"] if isinstance(a, dict) and "id" in a}
        for q in batch:
            a = by_id[q.id]
            evidence = " ".join(str(a.get("evidence") or "").split())
            out.append(Answer(q.id, a["relation"] in YES, float(a["confidence"]), evidence,
                              bool(evidence) and quote_in_page(evidence, text), a["relation"]))
    return out


@dataclass
class Confirmation:
    conflict: bool
    fact_says: str
    text_says: str
    confidence: float


def _passage_around(text: str, quote: str) -> str:
    """The paragraph of `text` that holds the quoted words (the quote itself if no paragraph does)."""
    for para in text.split("\n\n"):
        if quote and quote_in_page(quote, para):
            return para.strip()
    return quote


def _check_confirmation(data: dict) -> list[str]:
    problems = []
    if not isinstance(data.get("conflict"), bool):
        problems.append("'conflict' must be true or false")
    c = data.get("confidence")
    if isinstance(c, bool) or not isinstance(c, (int, float)) or not 0 <= c <= 1:
        problems.append("'confidence' must be a number from 0.0 to 1.0")
    return problems


def confirm_contradiction(ctx, label: str, what: str, fact: str, evidence: str, text: str) -> Confirmation:
    """Second opinion on one flagged contradiction: only the fact and the paragraph with the quoted words go to the model."""
    data = ask_json(ctx, f"{label} confirm", "critic", "continuity_confirm", _check_confirmation, max_tokens=400,
                    what=what, fact=fact, passage=_passage_around(text, evidence), quote=evidence)
    return Confirmation(bool(data["conflict"]), " ".join(str(data.get("fact_says") or "").split()),
                        " ".join(str(data.get("text_says") or "").split()), float(data["confidence"]))
