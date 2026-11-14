"""Managing a series and its books: add a book, give it a title, rename the series.

A book's id (`b1`, `b2`) is written into every scene id, fact id, saved state and Git tag, so it never changes. What the
author calls a book is its title (kept in the book's state.json). A series is a folder, so renaming it moves the folder
(its Git history moves with it). Each book has its own brief, `books/<id>/premise.md`: what this book is about. The book
north star is written from it, the series north star and the series ledger; a book without a brief falls back to the
series premise (the first book, and every book made before briefs existed).
"""

import re
import shutil
from pathlib import Path

from . import vcs
from .errors import BookforgeError
from .project import BOOK_ID_RE, SERIES_NAME_RE, Project, _BOOK_FILES, _write
from .state import new_state, save_state

TITLE_MAX = 120
INHERITED = "inherited from the series north star"


def book_ids(root: Path) -> list[str]:
    books = Path(root) / "books"
    return sorted(p.name for p in books.iterdir() if (p / "state.json").is_file()) if books.is_dir() else []


def brief_path(root: Path, book: str) -> Path:
    return Path(root) / "books" / book / "premise.md"


def book_brief(project: Project) -> str:
    """This book's brief, or the series premise if it has none."""
    for path in (brief_path(project.root, project.book), project.root / "premise.md"):
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if text:
            return text
    return ""


def clean_title(title: str) -> str:
    title = " ".join(title.split())
    if not title:
        raise BookforgeError("the title is empty")
    if len(title) > TITLE_MAX:
        raise BookforgeError(f"the title is too long ({len(title)} characters, at most {TITLE_MAX})")
    return title


def titles(root: Path) -> dict[str, str]:
    """Book id -> title ("" when it has none), for every book of the series."""
    out = {}
    for b in book_ids(root):
        try:
            out[b] = Project.open(Path(root), b).state.title
        except BookforgeError:
            out[b] = ""
    return out


def set_title(project: Project, title: str) -> str:
    project.state.title = clean_title(title)
    project.save_state()
    if project.config.git.commit_each_step:
        vcs.commit(project.root, f"{project.book}: titled '{project.state.title}'", [str(project.state_path.relative_to(project.root))])
    return project.state.title


def next_book_id(root: Path) -> str:
    """The next free id. One a deleted book used is never handed out again: its Git tags (b2-...) are still in the history."""
    numbers = [int(m.group(1)) for b in book_ids(root) if (m := re.fullmatch(r"b(\d+)", b))]
    try:
        numbers += [int(m.group(1)) for t in vcs.list_tags(Path(root)) if (m := re.match(r"b(\d+)-", t))]
    except BookforgeError:
        pass  # no readable history: the folders are all there is to go by
    return f"b{max(numbers, default=0) + 1}"


_DEAD = re.compile(r"\b(dead|died|dies|killed|executed|murdered|slain|deceased|death|perished|succumb\w*)\b", re.IGNORECASE)


def looks_dead(value: str) -> bool:
    """A state that says the owner is gone (dead, killed, executed...): used to leave a character out of a sequel by default."""
    return bool(_DEAD.search(str(value)))


def last_states(tracks, entity_id: str) -> list[dict]:
    """The state each track of an entity ends on: its last plan entry in position order (or the state it started as)."""
    from .bible.positions import parse_position
    out = []
    for t in tracks:
        if t.entity != entity_id:
            continue
        if t.plan:
            last = max(t.plan, key=lambda e: parse_position(e.from_).key)
            out.append({"track": t.id, "kind": t.kind, "value": last.value})
        elif str(t.starts_as).strip():
            out.append({"track": t.id, "kind": t.kind, "value": str(t.starts_as).strip()})
    return out


def carry_over_preview(root: Path, source: str) -> dict:
    """What a new book could take from `source`: every entity with its facts and last states; characters that ended dead are not suggested."""
    from .bible import store
    sp = Project.open(Path(root), source)
    constants, tracks = store.load_constants(sp), store.load_tracks(sp)
    entities = []
    for e in constants.entities:
        states = last_states(tracks, e.id)
        dead = any(looks_dead(s["value"]) for s in states)
        entities.append({"id": e.id, "kind": e.kind, "name": e.name, "facts": e.facts, "states": states, "dead": dead, "suggested": not dead})
    return {"source": source, "entities": entities, "rules": len(constants.rules)}


def _note_end_states(root: Path, source: str, entities: list[dict]) -> None:
    """Write what the source book ended on into the series ledger (end_of_book_states), unless that is already there: the series record."""
    import yaml
    path = Path(root) / "ledger.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    states = data.get("end_of_book_states")
    if not isinstance(states, dict):
        states = {}
    if source in states:
        return
    lines = [f"- {e['name']} ({e['kind']}): " + "; ".join(s["value"] for s in e["states"]) for e in entities if e["states"]]
    if not lines:
        return
    states[source] = "How " + source + " ended:\n" + "\n".join(lines)
    data["end_of_book_states"] = states
    data.setdefault("open_threads", [])
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def add_book(root: Path, title: str, brief: str, book: str | None = None, copy_from: str | None = None,
             copy_entities: list[str] | None = None) -> Project:
    """A new book in an existing series, with its own brief and its own bible. It inherits the series north star if there is one.

    The bible starts empty. With `copy_from` it starts with the cast of that book: the entities in `copy_entities` (by default every one
    that did not end dead), each with its facts, and each one's last state there as the state it starts this book in. The rules of the
    world come along. Nothing is shared afterwards: the new book can change a character without touching the first."""
    root = Path(root)
    if not (root / "premise.md").is_file():
        raise BookforgeError(f"{root} is not a series")
    title = clean_title(title)
    if not brief.strip():
        raise BookforgeError("the brief is empty: say what this book is about")
    book = book or next_book_id(root)
    if not BOOK_ID_RE.match(book):
        raise BookforgeError(f"'{book}' is not a valid book id")
    if (root / "books" / book).exists():
        raise BookforgeError(f"the series already has a book '{book}'")
    book_dir = root / "books" / book
    try:  # all or nothing: a book that could not be made (an unknown entity to copy...) leaves no folder behind
        for rel, content in _BOOK_FILES.items():
            _write(book_dir / rel, content)
        brief_path(root, book).write_text(brief.rstrip() + "\n", encoding="utf-8")
        if copy_from:
            _copy_cast(root, copy_from, book, copy_entities)
        state = new_state(book)
        state.title = title
        star = root / "north-star.md"
        if star.is_file() and star.read_text(encoding="utf-8").strip():
            state.set_layer_status("series_north_star", "accepted", INHERITED)
        save_state(book_dir / "state.json", state)
    except BaseException:
        shutil.rmtree(book_dir, ignore_errors=True)
        raise
    vcs.commit(root, f"series: added book {book} '{title}'")
    return Project.open(root, book)


def _copy_cast(root: Path, source: str, book: str, chosen: list[str] | None) -> None:
    from .bible import store
    from .bible.models import Constants, Track
    if source not in book_ids(root):
        raise BookforgeError(f"no book '{source}' to copy from")
    preview = carry_over_preview(root, source)
    wanted = {e["id"] for e in preview["entities"] if e["suggested"]} if chosen is None else set(chosen)
    unknown = wanted - {e["id"] for e in preview["entities"]}
    if unknown:
        raise BookforgeError(f"{source} has no entity {', '.join(sorted(unknown))}")
    sp = Project.open(root, source)
    constants, tracks = store.load_constants(sp), store.load_tracks(sp)
    kept = Constants(entities=[e for e in constants.entities if e.id in wanted], rules=constants.rules)
    carried = [Track(id=t.id, entity=t.entity, kind=t.kind, starts_as=s["value"])
               for t in tracks if t.entity in wanted for s in last_states([t], t.entity)]
    target = Path(root) / "books" / book / "bible"
    from .bible.store import dump_yaml, to_plain
    (target / "constants.yaml").write_text(dump_yaml({"entities": [to_plain(e) for e in kept.entities], "rules": [to_plain(r) for r in kept.rules]}), encoding="utf-8")
    (target / "tracks.yaml").write_text(dump_yaml({"tracks": [to_plain(t) for t in carried]}), encoding="utf-8")
    _note_end_states(root, source, preview["entities"])


def rename_series(data_dir: Path, old: str, new: str) -> Path:
    """Move a series folder to a new name. Nothing inside it changes."""
    data_dir = Path(data_dir)
    if not SERIES_NAME_RE.match(new):
        raise BookforgeError("the series name must be lowercase letters, digits, '-' or '_' (up to 64 characters)")
    src, dest = data_dir / old, data_dir / new
    if not (src / "premise.md").is_file():
        raise BookforgeError(f"no series '{old}'")
    if new == old:
        raise BookforgeError("the new name is the same as the old one")
    if dest.exists():
        raise BookforgeError(f"a series called '{new}' already exists")
    src.rename(dest)
    return dest
