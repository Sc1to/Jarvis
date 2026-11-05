"""Generate one planning document: refine, check, correct.

The shared loop behind layers 1-3. It asks the model for the document, checks the
structure mechanically, and if the check fails asks for a correction, at most
`qc.max_revision_rounds` times. Judging quality is the author's job at the
checkpoint (and the critic's, from milestone 14.7).
"""

import logging
import re
from dataclasses import dataclass
from typing import Callable

from ..errors import LayerError
from ..prompts import render
from ..research.notes import notes_for_prompt, stores_for
from ..research.step import run_research
from .runner import StepContext, StepResult

log = logging.getLogger("platform_bookforge.layers")

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


@dataclass
class DocumentSpec:
    layer: str
    prompt: str  # template name
    out_path: str  # relative to the series root; may contain {book}
    validate: Validator
    max_tokens: int
    strip_preamble: bool
    slots: Callable[[StepContext], dict[str, str]]
    normalize: Callable[[str], str] | None = None  # rewrites a validated reply before saving (YAML layers)
    research_scope: str | None = None  # "series" or "book": where this layer's research notes are kept
    research_focus: str = ""  # what this layer needs researched (docs/BOOKFORGE.md, layer table)


def generate_document(ctx: StepContext, spec: DocumentSpec) -> StepResult:
    project = ctx.project
    out_rel = spec.out_path.format(book=project.book)
    out = project.resolve(out_rel)

    # An existing file is the author's (or an interrupted run's): check it and keep it.
    if out.exists() and out.read_text(encoding="utf-8").strip():
        text = out.read_text(encoding="utf-8")
        problems = spec.validate(text)
        if problems:
            raise LayerError(f"existing {out_rel} is not acceptable: " + "; ".join(problems)
                             + " (fix the file, or delete it to have it regenerated)")
        log.info("%s: adopted existing %s", spec.layer, out_rel)
        note = "adopted existing file"
    else:
        text = _draft(ctx, spec)
        if spec.normalize is not None:
            text = spec.normalize(text)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text.rstrip() + "\n", encoding="utf-8")
        note = f"{word_count(text)} words"

    files = [out_rel]
    outcome = _research(ctx, spec, text)
    if outcome is not None:
        files += outcome.files
        note += "; " + outcome.summary()
    return StepResult(files=files, note=note)


def prompt_values(project) -> dict[str, str]:
    """The slot values every planning prompt can use."""
    cfg = project.config
    return {
        "language": cfg.book.language, "pov": cfg.book.pov, "tense": cfg.book.tense,
        "target_words": str(cfg.book.target_words), "book_id": project.book,
        "research_notes": notes_for_prompt(project, cfg.research.notes_max_chars),
    }


def _research(ctx: StepContext, spec: DocumentSpec, document: str):
    """The layer's research step. None when it does not apply (no scope, disabled, no web client)."""
    if spec.research_scope is None:
        return None
    return research_layer(ctx, spec.research_scope, spec.research_focus, document)


def research_layer(ctx: StepContext, scope: str, focus: str, document: str):
    """Run research for ctx.layer after its output exists. None if research is off or there is no web client."""
    cfg = ctx.project.config.research
    if not cfg.enabled or ctx.web is None:
        return None
    outcome = run_research(ctx, scope, focus, document)
    if cfg.required and stores_for(ctx.project)[scope].answered_count(ctx.layer) == 0:
        raise LayerError("research is required but no question could be answered: "
                         + ("; ".join(outcome.failures) or "no questions were asked"))
    return outcome


def _draft(ctx: StepContext, spec: DocumentSpec) -> str:
    """Refine: ask for the document, check it, and ask for corrections until it passes."""
    project = ctx.project
    if ctx.llm is None:
        raise LayerError("no model client available")

    cfg = project.config
    layer_cfg = cfg.layers[spec.layer]
    options: dict = {"max_tokens": spec.max_tokens}
    if layer_cfg.temperature is not None:
        options["temperature"] = layer_cfg.temperature

    values = {**prompt_values(project), **spec.slots(ctx)}
    messages = [
        {"role": "system", "content": render("system", project.root, **values)},
        {"role": "user", "content": render(spec.prompt, project.root, **values)},
    ]

    return ask_until_valid(ctx, spec.layer, layer_cfg.model, messages, spec.validate, options, spec.strip_preamble)


def ask_until_valid(
    ctx: StepContext, label: str, role: str, messages: list[dict], validate: Validator,
    options: dict, strip_preamble: bool,
) -> str:
    """Ask the model, check the reply, and ask for corrections (at most qc.max_revision_rounds) until it passes."""
    rounds = ctx.project.config.qc.max_revision_rounds
    text = clean_reply(ctx.llm.complete(role, messages, **options), strip_preamble)
    problems = validate(text)
    for attempt in range(1, rounds + 1):
        if not problems:
            break
        log.info("%s: reply has %d problem(s); correction round %d/%d", label, len(problems), attempt, rounds)
        messages = messages + [
            {"role": "assistant", "content": text},
            {"role": "user", "content": render("correct", ctx.project.root, problems="\n".join(f"- {p}" for p in problems))},
        ]
        text = clean_reply(ctx.llm.complete(role, messages, **options), strip_preamble)
        problems = validate(text)
    if problems:
        raise LayerError(f"{label} still has problems after {rounds} correction round(s): " + "; ".join(problems))
    return text
