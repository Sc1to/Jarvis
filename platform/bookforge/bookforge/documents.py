"""The documents you review, as a fixed list the dashboard can read.

Only files named here are ever served (a key maps to one path; there is no path in the request), so nothing outside
the series can be read. Research notes are the one dynamic group: the `*.md` files that the research step wrote.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from . import vcs
from .errors import BookforgeError
from .bible import store as bible
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
        Doc("constants", "Cast and rules of the world", "Story bible", "yaml", bible.constants_path(project)),
        Doc("tracks", "State tracks", "Story bible", "yaml", bible.tracks_path(project)),
        Doc("timeline", "Timeline", "Story bible", "yaml", bible.timeline_path(project)),
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


class EditNeedsCast(EditRefused):
    """The only thing wrong with the edit is that it names people, places or things the cast does not have. Nothing was saved; `proposal` says what to add."""

    def __init__(self, problems: list[str], proposal: list[dict]):
        super().__init__(problems)
        self.proposal = proposal


_UNKNOWN_ID = re.compile(r"^(?P<label>.*?): '(?P<id>[a-z][a-z0-9-]*)' is not in the cast")


def _unknown_ids(problems: list[str]) -> list[tuple[str, str]]:
    """(label, id) for every problem that is an unknown cast id; [] unless ALL of them are."""
    found = [_UNKNOWN_ID.match(p) for p in problems]
    return [(m["label"], m["id"]) for m in found] if found and all(found) else []


def _tokens(entity_id: str) -> list[str]:
    return [t for t in entity_id.split("-") if len(t) >= 3]


def _facts_from(text: str, entity_id: str) -> list[str]:
    """What the edit itself says about the new entity: the lines of the edited text that mention its name, in the author's own words."""
    toks = _tokens(entity_id)
    out: list[str] = []
    for line in text.splitlines():
        body = re.sub(r"^\s*-\s*", "", line).strip().strip("\"'")
        key = re.match(r"^(purpose|summary|end_state|situation|learns|title)\s*:\s*(.+)$", body)
        body = key.group(2).strip().strip("\"'") if key else body
        if len(body.split()) >= 5 and any(t in body.lower() for t in toks) and not body.lower().startswith(("characters:", "pov:", "setting:")):
            out.append(body[:240])
        if len(out) >= 3:
            break
    return out or [f"Introduced by an edit of the plan; details still open."]


def propose_cast(project: Project, text: str, unknown: list[tuple[str, str]]) -> list[dict]:
    """For each unknown id: a suggested entity (kind from where it was used, name from the id, facts from the edit's own words) and the existing entities it may be an alias of."""
    constants = bible.load_constants(project)
    out, seen = [], set()
    for label, eid in unknown:
        if eid in seen:
            continue
        seen.add(eid)
        kind = "place" if "setting" in label else "character"
        toks = set(_tokens(eid))
        aliases = [e.id for e in constants.entities if (toks & set(_tokens(e.id)) or toks & {w.lower() for w in e.name.split() if len(w) >= 3}) and (e.kind == kind or kind == "character" and e.kind == "group")]
        out.append({"id": eid, "kind": kind, "name": eid.replace("-", " ").title(), "facts": _facts_from(text, eid), "used_in": label, "may_be": aliases[:3]})
    return out


def replace_id(text: str, old: str, new: str) -> str:
    """The id in a plan text, wherever it stands as a whole token (`'old'`, `old,` ...), replaced by an existing one."""
    return re.sub(rf"(?<![A-Za-z0-9-]){re.escape(old)}(?![A-Za-z0-9-])", new, text)


def save_with_cast(project: Project, doc: Doc, text: str, entities: list[dict]) -> list[str]:
    """Save the edit together with the cast entries it needs, all or nothing. Each entry is {id, kind, name, facts} (a new entity) or {id, alias_of} (the id was a
    second name for an existing entity: the plan text is changed to the existing id). Returns the ids added. If the edit is still refused, the entries are taken out again."""
    from . import cast
    added: list[str] = []
    try:
        for e in entities:
            if e.get("alias_of"):
                text = replace_id(text, e["id"], e["alias_of"])
            else:
                cast.add(project, e["id"], e["kind"], e["name"], list(e.get("facts") or []))
                added.append(e["id"])
        save(project, doc, text)
    except Exception:
        for eid in reversed(added):
            try:
                cast.delete(project, eid)
            except Exception:  # the entry stays: it is harmless, and the cast tab can remove it
                pass
        raise
    return added


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
    return [f.line() for f in ledger_checks.check_ledger([e.model_dump() for e in ledger.events], synopsis, no_event_needed=ledger.no_event_needed) if f.severity == HARD]


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
        unknown = _unknown_ids(new)
        if unknown:  # not wrong, only new: offer to add what it introduces instead of making you leave the editor
            raise EditNeedsCast(new, propose_cast(project, text, unknown))
        raise EditRefused(new)
    if project.config.git.commit_each_step:
        vcs.commit(project.root, f"{project.book}: you edited {doc.title}", [doc.path])
