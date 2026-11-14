"""Ask a model, check the reply, and ask for corrections until it passes.

Used by every step that needs a checked reply: planning documents, structured replies (JSON, YAML)
and the quality-control calls. Lives apart from the layers so quality control can use it without
importing them.
"""

import logging
import re
from typing import TYPE_CHECKING, Callable

from .errors import LayerError
from .prompts import render

if TYPE_CHECKING:  # annotations only: importing the runner here would create an import cycle
    from .layers.runner import StepContext

log = logging.getLogger("platform_bookforge.ask")

Validator = Callable[[str], list[str]]

_ITEM_REF = re.compile(r"\[([^\]]{3,120})\]")
MAX_QUOTED_LINES = 6


def _problem_key(problem: str) -> str:
    """What identifies a problem from one round to the next: its start (the code and the items it names), not the wording after."""
    return " ".join(problem.split())[:90]


def _block(lines: list[str], at: int, max_lines: int = 5) -> list[str]:
    """The line `at` and, if it starts a YAML list item or key, the lines of the same item below it (until the next item at its indent)."""
    first = lines[at]
    indent = len(first) - len(first.lstrip())
    out = [first]
    for nxt in lines[at + 1: at + max_lines]:
        pad = len(nxt) - len(nxt.lstrip())
        if nxt.strip() and (pad < indent or (pad == indent and nxt.lstrip().startswith("- "))):
            break
        out.append(nxt)
    return out


def where_in_reply(text: str, problems: list[str]) -> str:
    """The parts of the model's own reply that the problems point at (an id like b2.ch03 in a problem's brackets), so it sees what to change."""
    ids: list[str] = []
    for p in problems:
        for m in _ITEM_REF.finditer(p):
            ids += [x.strip() for x in m.group(1).split(",") if "." in x.strip() and len(x.strip()) >= 4]
    all_lines = text.splitlines()
    out: list[str] = []
    seen: set[str] = set()
    for ref in dict.fromkeys(ids):
        for i, line in enumerate(all_lines):
            if ref in line and line.strip() not in seen:
                for part in _block(all_lines, i):
                    if part.strip() and part.strip() not in seen and len(out) < MAX_QUOTED_LINES:
                        seen.add(part.strip())
                        out.append(f"- {part.strip()[:170]}")
    return ("Where they are in your last reply:\n" + "\n".join(out)) if out else ""


_FENCE = re.compile(r"\A(.*?)```[a-zA-Z]*\n(.*?)\n?```(.*?)\Z", re.DOTALL)
_MAX_CHATTER = 400  # characters of text around a fenced block that we treat as chatter


def word_count(text: str) -> int:
    return len(re.findall(r"[\w'’-]+", text))


def clean_reply(text: str, strip_preamble: bool) -> str:
    """Remove a code fence the model wrapped around the document and, if asked, chatter before the first heading."""
    text = text.strip()
    m = _FENCE.match(text)
    if m and len(m.group(1)) + len(m.group(3)) <= _MAX_CHATTER:
        text = m.group(2).strip()
    if strip_preamble and not text.startswith("#"):
        lines = text.split("\n")
        for i, line in enumerate(lines):
            if line.startswith("#"):
                text = "\n".join(lines[i:]).strip()
                break
    return text


def ask_until_valid(
    ctx: "StepContext", label: str, role: str, messages: list[dict], validate: Validator,
    options: dict, strip_preamble: bool,
    soft_validate: Validator | None = None, soft_sink: list | None = None,
) -> str:
    """Ask, check, and ask for corrections (at most qc.max_revision_rounds) until the reply passes.

    `validate` returns hard problems: if any remain after the last round, LayerError is raised.
    `soft_validate` (a review) only runs once the hard checks pass. Its problems are sent back for
    correction as well, but if they remain after the last round the reply is kept and they are
    appended to `soft_sink` as (label, problems): the author's call, not a failure.
    """
    rounds = ctx.project.config.qc.max_revision_rounds
    text = clean_reply(ctx.llm.complete(role, messages, **options), strip_preamble)
    hard = validate(text)
    soft: list[str] = [] if hard or soft_validate is None else soft_validate(text)
    kept: tuple[str, list[str]] | None = None  # the last reply that passed the hard checks, with the review's complaints about it
    earlier: set[str] = set()  # the problems of the round before: one that comes back is marked, and the message gets firmer
    for attempt in range(1, rounds + 1):
        problems = hard or soft
        if not problems:
            break
        if not hard:
            kept = (text, soft)
        log.info("%s: reply has %d problem(s); correction round %d/%d", label, len(problems), attempt, rounds)
        again = [p for p in problems if _problem_key(p) in earlier]
        if attempt > 1 and again:
            listed = "\n".join(f"- STILL PRESENT: {p}" if _problem_key(p) in earlier else f"- {p}" for p in problems)
            user = render("correct_again", ctx.project.root, round=str(attempt), rounds=str(rounds), problems=listed, where=where_in_reply(text, again))
        else:
            user = render("correct", ctx.project.root, problems="\n".join(f"- {p}" for p in problems))
        earlier = {_problem_key(p) for p in problems}
        messages = messages + [{"role": "assistant", "content": text}, {"role": "user", "content": user}]
        text = clean_reply(ctx.llm.complete(role, messages, **options), strip_preamble)
        hard = validate(text)
        soft = [] if hard or soft_validate is None else soft_validate(text)
    if hard and kept is not None:
        # A correction that only answered the review's complaints broke a reply that was valid (seen: the model answered in the
        # critic's JSON instead of the plan). A valid reply with open review notes is the author's call, not a failure.
        log.info("%s: a correction made a valid reply invalid (%s); keeping the earlier reply", label, hard[0])
        text, soft = kept
        hard = []
    if hard:
        raise LayerError(f"{label} still has problems after {rounds} correction round(s): " + "; ".join(hard))
    if soft and soft_sink is not None:
        soft_sink.append((label, soft))
    return text
