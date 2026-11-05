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
    for attempt in range(1, rounds + 1):
        problems = hard or soft
        if not problems:
            break
        log.info("%s: reply has %d problem(s); correction round %d/%d", label, len(problems), attempt, rounds)
        messages = messages + [
            {"role": "assistant", "content": text},
            {"role": "user", "content": render("correct", ctx.project.root, problems="\n".join(f"- {p}" for p in problems))},
        ]
        text = clean_reply(ctx.llm.complete(role, messages, **options), strip_preamble)
        hard = validate(text)
        soft = [] if hard or soft_validate is None else soft_validate(text)
    if hard:
        raise LayerError(f"{label} still has problems after {rounds} correction round(s): " + "; ".join(hard))
    if soft and soft_sink is not None:
        soft_sink.append((label, soft))
    return text
