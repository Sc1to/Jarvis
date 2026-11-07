"""Layers 1-3: series north star, book north star, synopsis (the direction checkpoint)."""

import re

import yaml

from ..books import book_brief

from .document import DocumentSpec, generate_document, word_count
from .runner import StepContext, StepResult

NORTH_STAR_SECTIONS = ("Premise", "Themes", "Emotional promise", "Tone", "Realism", "Ending direction", "What it is not")
NORTH_STAR_MIN_WORDS = 150
NORTH_STAR_MAX_WORDS = 800  # the prompt asks for 350-450; the cap leaves room
SYNOPSIS_MIN_WORDS = 300
SYNOPSIS_MAX_WORDS = 2500

_H2 = re.compile(r"^##\s+(.+?)\s*#*\s*$", re.MULTILINE)


def validate_north_star(text: str) -> list[str]:
    problems = []
    headings = [(m.group(1).strip().casefold(), m.start(), m.end()) for m in _H2.finditer(text)]
    found = {name for name, _, _ in headings}
    for section in NORTH_STAR_SECTIONS:
        if section.casefold() not in found:
            problems.append(f"missing the section '## {section}'")
    for i, (name, _, end) in enumerate(headings):
        if name in {s.casefold() for s in NORTH_STAR_SECTIONS}:
            stop = headings[i + 1][1] if i + 1 < len(headings) else len(text)
            if word_count(text[end:stop]) < (2 if name == "realism" else 4):
                problems.append(f"the section '{name}' is empty")
    n = word_count(text)
    if n > NORTH_STAR_MAX_WORDS:
        problems.append(f"too long: {n} words, a north star must fit on one page (at most {NORTH_STAR_MAX_WORDS})")
    if n < NORTH_STAR_MIN_WORDS:
        problems.append(f"too short: {n} words (at least {NORTH_STAR_MIN_WORDS})")
    return problems


def validate_synopsis(text: str) -> list[str]:
    n = word_count(text)
    if n < SYNOPSIS_MIN_WORDS:
        return [f"too short: {n} words (at least {SYNOPSIS_MIN_WORDS})"]
    if n > SYNOPSIS_MAX_WORDS:
        return [f"too long: {n} words (at most {SYNOPSIS_MAX_WORDS})"]
    return []


def _read(ctx: StepContext, rel: str) -> str:
    return ctx.project.resolve(rel).read_text(encoding="utf-8").strip()


def _ledger_text(ctx: StepContext) -> str:
    """The series ledger, or 'none' while it is still empty (first book)."""
    path = ctx.project.root / "ledger.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return "none"
    if not isinstance(data, dict) or not any(data.values()):
        return "none (this is the first book)"
    return path.read_text(encoding="utf-8").strip()


SERIES_NORTH_STAR = DocumentSpec(
    layer="series_north_star", prompt="series_north_star", out_path="north-star.md",
    validate=validate_north_star, max_tokens=2000, strip_preamble=True,
    slots=lambda ctx: {"premise": _read(ctx, "premise.md")},
    research_scope="series", research_focus="Broad background for the whole series: the genre, the era, and the world it is set in.",
)

BOOK_NORTH_STAR = DocumentSpec(
    layer="book_north_star", prompt="book_north_star", out_path="books/{book}/north-star.md",
    validate=validate_north_star, max_tokens=2000, strip_preamble=True,
    slots=lambda ctx: {
        "premise": book_brief(ctx.project),  # this book's own brief; the series premise if it has none
        "series_north_star": _read(ctx, "north-star.md"),
        "ledger": _ledger_text(ctx),
    },
    research_scope="book", research_focus="What is specific to this book: its setting, events, professions, objects and customs.",
)

SYNOPSIS = DocumentSpec(
    layer="synopsis", prompt="synopsis", out_path="books/{book}/synopsis.md",
    validate=validate_synopsis, max_tokens=4000, strip_preamble=False,
    slots=lambda ctx: {
        "series_north_star": _read(ctx, "north-star.md"),
        "book_north_star": _read(ctx, f"books/{ctx.project.book}/north-star.md"),
    },
    research_scope="book", research_focus="Gaps the synopsis reveals: real-world facts the plot depends on that the author has not yet checked.",
)


def series_north_star(ctx: StepContext) -> StepResult:
    return generate_document(ctx, SERIES_NORTH_STAR)


def book_north_star(ctx: StepContext) -> StepResult:
    return generate_document(ctx, BOOK_NORTH_STAR)


def synopsis(ctx: StepContext) -> StepResult:
    return generate_document(ctx, SYNOPSIS)
