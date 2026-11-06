"""The realism setting of a book: how faithful to the real world its story must be.

It is a short statement in the `## Realism` section of the series north star and, where a book differs, of the
book's north star. The book's statement wins; "As the series." (optionally followed by exceptions) means the series'
statement applies. Later steps read it to decide what must be looked up, extended, bent or simply invented.
"""

import re

from .project import Project

_H2 = re.compile(r"^##\s+(.+?)\s*#*\s*$", re.MULTILINE)
_AS_SERIES = re.compile(r"^as the series\b[.:;,\s-]*", re.IGNORECASE)


def section(text: str, name: str) -> str:
    """The body of the `## name` section of a north star, or "" if it has none."""
    heads = list(_H2.finditer(text))
    for i, m in enumerate(heads):
        if m.group(1).strip().casefold() == name.casefold():
            stop = heads[i + 1].start() if i + 1 < len(heads) else len(text)
            return " ".join(text[m.end():stop].split())
    return ""


def _read(project: Project, rel: str) -> str:
    try:
        return project.resolve(rel).read_text(encoding="utf-8")
    except (OSError, ValueError):
        return ""


def realism_setting(project: Project) -> str:
    """The realism statement that applies to the open book, or "" if neither north star has one (older projects)."""
    series = section(_read(project, "north-star.md"), "Realism")
    book = section(_read(project, f"books/{project.book}/north-star.md"), "Realism")
    if not book:
        return series
    m = _AS_SERIES.match(book)
    if not m:
        return book
    extra = book[m.end():].strip()
    return f"{series} {extra}".strip() if extra else series
