"""The documents you review, as a fixed list the dashboard can read.

Only files named here are ever served (a key maps to one path; there is no path in the request), so nothing outside
the series can be read. Research notes are the one dynamic group: the `*.md` files that the research step wrote.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from . import vcs
from .errors import BookforgeError
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
        Doc("book_brief", "Book brief", "Direction", "markdown", book / "premise.md"),
        Doc("series_north_star", "Series north star", "Direction", "markdown", root / "north-star.md"),
        Doc("book_north_star", "Book north star", "Direction", "markdown", book / "north-star.md"),
        Doc("synopsis", "Synopsis", "Direction", "markdown", book / "synopsis.md"),
        Doc("ledger", "Story events (ledger)", "Story events", "yaml", book / "ledger.yaml"),
        Doc("acts", "Acts", "Structure", "yaml", book / "acts.yaml"),
        Doc("chapters", "Chapters", "Structure", "yaml", book / "chapters.yaml"),
        Doc("scenes", "Scene plans", "Structure", "yaml", book / "scenes.yaml"),
        Doc("constants", "Cast and rules of the world", "Story bible", "yaml", root / "bible" / "constants.yaml"),
        Doc("tracks", "State tracks", "Story bible", "yaml", root / "bible" / "tracks.yaml"),
        Doc("timeline", "Timeline", "Story bible", "yaml", root / "bible" / "timeline.yaml"),
        Doc("style_guide", "Style guide", "Voice", "markdown", root / "style" / "guide.md"),
        Doc("style_suggested", "Style guide (a suggestion beside yours)", "Voice", "markdown", root / "style" / "guide.suggested.md"),
        Doc("banned", "Banned phrases", "Voice", "text", root / project.config.qc.banned_phrases),
    ]
    for scope, directory in (("series", root / "research"), ("book", book / "research")):
        docs.append(Doc(f"needs-{scope}", f"Needs and decisions ({scope})", "Research", "markdown", directory / "needs.md"))
        for p in sorted(directory.glob("*.md")) if directory.is_dir() else []:
            if _STEM.match(p.stem) and p.name != "needs.md":
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


# ── editing ───────────────────────────────────────────────────────────────────

class EditRefused(BookforgeError):
    """The new text would introduce problems; nothing was saved. `problems` says what."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems[:5]))
        self.problems = problems


def editable(doc: Doc) -> bool:
    return doc.group != "Research"  # research notes are written by the research step, and read-only


def _problems(project: Project, doc: Doc) -> list[str]:
    """Structural problems of the document as it is on disk now ([] for the free-text ones)."""
    from .layers import direction, structure
    try:
        text = doc.path.read_text(encoding="utf-8") if doc.path.is_file() else ""
    except OSError:
        text = ""
    match doc.key:
        case "series_north_star" | "book_north_star":
            return direction.validate_north_star(text)
        case "synopsis":
            return direction.validate_synopsis(text)
        case "ledger":
            return _ledger_problems(project, text)
        case "acts":
            return structure.parse_acts(text, project)[1] if text.strip() else []
        case "chapters":
            return structure.validate_chapters_file(project) if text.strip() else []
        case "scenes":
            return structure.validate_scenes_file(project) if text.strip() else []
        case "constants" | "tracks" | "timeline":
            from .bible.validate import validate_bible
            return validate_bible(project, False)
    return []


def _ledger_problems(project: Project, text: str) -> list[str]:
    """Hard findings of a hand-edited ledger: unknown or duplicate ids, order, excerpts that are not in the synopsis, no ending..."""
    if not text.strip():
        return []
    import yaml
    from pydantic import ValidationError
    from .bible.models import Ledger, problems_from
    from .validators import HARD, ledger as ledger_checks
    try:
        ledger = Ledger.model_validate(yaml.safe_load(text) or {})
    except (yaml.YAMLError, ValidationError) as e:
        return [f"not a valid ledger: {problems_from(e)[0] if isinstance(e, ValidationError) else str(e).splitlines()[0]}"]
    try:
        synopsis = (project.book_dir / "synopsis.md").read_text(encoding="utf-8")
    except OSError:
        synopsis = ""
    return [f.line() for f in ledger_checks.check_ledger([e.model_dump() for e in ledger.events], synopsis) if f.severity == HARD]


_EVENT_KEYS = ("id", "text", "once_only", "after", "kind", "weight", "ending", "pays_off", "source", "parent", "excerpt", "carried_in")


def _event_signature(text: str) -> list | None:
    import yaml
    try:
        data = yaml.safe_load(text) or {}
        return [[e.get(k) for k in _EVENT_KEYS] for e in data.get("events", [])] if isinstance(data, dict) else None
    except (yaml.YAMLError, AttributeError):
        return None


def _ledger_has_dependents(project: Project) -> list[str]:
    return [l for l in ("acts", "chapters", "scenes", "prose") if project.state.layers[l].status != "pending"]


def save(project: Project, doc: Doc, text: str) -> None:
    """Write a document you edited. Refused (and the old text put back) if it adds problems the old text did not have.

    Only new problems count: a plan with an old unrelated problem can still be edited, and an older north star without
    a section added since can be edited without adding it.
    """
    if not editable(doc):
        raise BookforgeError(f"'{doc.title}' cannot be edited here")
    if doc.key not in ("banned", "style_guide") and not text.strip():
        raise BookforgeError("the text is empty")
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise BookforgeError(f"the text is too long (at most {MAX_BYTES // 1000} KB)")
    text = text.rstrip() + "\n" if text.strip() else ""
    if doc.key == "ledger" and doc.path.is_file():  # the acts and everything after are built from these events: changing them would leave those out of date, silently
        built = _ledger_has_dependents(project)
        if built and _event_signature(doc.path.read_text(encoding="utf-8")) != _event_signature(text):
            raise EditRefused([f"{', '.join(built)} are built on these events, so changing them would leave those out of date. Use Redo on the ledger in the Overview "
                               "(with the cascade box ticked) to write the ledger and what follows again; your answers to its questions can still be saved"])
    before = _problems(project, doc)
    old = doc.path.read_text(encoding="utf-8") if doc.path.is_file() else None
    doc.path.parent.mkdir(parents=True, exist_ok=True)
    doc.path.write_text(text, encoding="utf-8")
    new = [p for p in _problems(project, doc) if p not in before]
    if new:
        if old is None:
            doc.path.unlink(missing_ok=True)
        else:
            doc.path.write_text(old, encoding="utf-8")
        raise EditRefused(new)
    if project.config.git.commit_each_step:
        vcs.commit(project.root, f"{project.book}: you edited {doc.title}", [doc.path])
