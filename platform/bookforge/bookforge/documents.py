"""The documents you review, as a fixed list the dashboard can read.

Only files named here are ever served (a key maps to one path; there is no path in the request), so nothing outside
the series can be read. Research notes are the one dynamic group: the `*.md` files that the research step wrote.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from .project import Project

MAX_BYTES = 400_000
_STEM = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


@dataclass
class Doc:
    key: str
    title: str
    group: str
    kind: str  # markdown | yaml | text
    path: Path

    @property
    def exists(self) -> bool:
        """Written, as opposed to missing or still the starter placeholder (a lone heading, `{}`, `tracks: []`)."""
        try:
            text = self.path.read_text(encoding="utf-8") if self.path.is_file() else ""
        except OSError:
            return False
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if self.kind == "markdown":
            return any(not ln.startswith("#") for ln in lines)
        if self.kind == "yaml":
            return bool(lines) and not all(ln in ("{}", "[]") or re.fullmatch(r"\w+:\s*(\[\]|\{\})", ln) for ln in lines)
        return bool(lines)


def catalog(project: Project) -> list[Doc]:
    root, book = project.root, project.book_dir
    docs = [
        Doc("premise", "Premise", "Direction", "markdown", root / "premise.md"),
        Doc("series_north_star", "Series north star", "Direction", "markdown", root / "north-star.md"),
        Doc("book_north_star", "Book north star", "Direction", "markdown", book / "north-star.md"),
        Doc("synopsis", "Synopsis", "Direction", "markdown", book / "synopsis.md"),
        Doc("acts", "Acts", "Structure", "yaml", book / "acts.yaml"),
        Doc("chapters", "Chapters", "Structure", "yaml", book / "chapters.yaml"),
        Doc("scenes", "Scene plans", "Structure", "yaml", book / "scenes.yaml"),
        Doc("constants", "Cast and rules of the world", "Story bible", "yaml", root / "bible" / "constants.yaml"),
        Doc("tracks", "State tracks", "Story bible", "yaml", root / "bible" / "tracks.yaml"),
        Doc("timeline", "Timeline", "Story bible", "yaml", root / "bible" / "timeline.yaml"),
        Doc("style_guide", "Style guide", "Voice", "markdown", root / "style" / "guide.md"),
        Doc("banned", "Banned phrases", "Voice", "text", root / project.config.qc.banned_phrases),
    ]
    for scope, directory in (("series", root / "research"), ("book", book / "research")):
        for p in sorted(directory.glob("*.md")) if directory.is_dir() else []:
            if _STEM.match(p.stem):
                docs.append(Doc(f"research-{scope}-{p.stem}", f"Research: {p.stem.replace('_', ' ')} ({scope})", "Research", "markdown", p))
    return docs


def find(project: Project, key: str) -> Doc | None:
    return next((d for d in catalog(project) if d.key == key), None)


def read(doc: Doc) -> tuple[str, bool]:
    """(text, truncated). Empty text for a file that is not written yet."""
    try:
        raw = doc.path.read_bytes()
    except OSError:
        return "", False
    return raw[:MAX_BYTES].decode("utf-8", errors="replace"), len(raw) > MAX_BYTES
