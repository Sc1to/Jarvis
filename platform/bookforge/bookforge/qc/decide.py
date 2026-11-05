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


@dataclass
class Answer:
    id: str
    yes: bool
    confidence: float
    evidence: str = ""
    verified: bool = False  # the evidence really appears in the text


def _check(questions: list[Question]):
    ids = {q.id for q in questions}

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
            if a.get("answer") not in ("yes", "no"):
                problems.append(f"{a['id']}: 'answer' must be \"yes\" or \"no\"")
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
            out.append(Answer(q.id, a["answer"] == "yes", float(a["confidence"]), evidence,
                              bool(evidence) and quote_in_page(evidence, text)))
    return out
