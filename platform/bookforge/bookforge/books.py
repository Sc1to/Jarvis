"""Managing a series and its books: add a book, give it a title, rename the series.

A book's id (`b1`, `b2`) is written into every scene id, fact id, saved state and Git tag, so it never changes. What the
author calls a book is its title (kept in the book's state.json). A series is a folder, so renaming it moves the folder
(its Git history moves with it). Each book has its own brief, `books/<id>/premise.md`: what this book is about. The book
north star is written from it, the series north star and the series ledger; a book without a brief falls back to the
series premise (the first book, and every book made before briefs existed).
"""

import re
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


def add_book(root: Path, title: str, brief: str, book: str | None = None) -> Project:
    """A new book in an existing series, with its own brief. It inherits the series north star if there is one."""
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
    for rel, content in _BOOK_FILES.items():
        _write(root / "books" / book / rel, content)
    brief_path(root, book).write_text(brief.rstrip() + "\n", encoding="utf-8")
    state = new_state(book)
    state.title = title
    star = root / "north-star.md"
    if star.is_file() and star.read_text(encoding="utf-8").strip():
        state.set_layer_status("series_north_star", "accepted", INHERITED)
    save_state(root / "books" / book / "state.json", state)
    vcs.commit(root, f"series: added book {book} '{title}'")
    return Project.open(root, book)


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
