"""A series folder on disk and the book being worked on."""

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from . import vcs
from .config import Config, load_config
from .errors import BookforgeError
from .state import BookState, load_state, new_state, save_state

log = logging.getLogger("platform_bookforge.project")

BOOK_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")

_GITIGNORE = "books/*/logs/\n"

# Files every new series starts with (path relative to the series root -> content).
_SERIES_FILES = {
    "ledger.yaml": "open_threads: []\nend_of_book_states: {}\n",
    "style/guide.md": "# Style guide\n\n",
    "style/banned.txt": "",
    "style/samples/.gitkeep": "",
    "bible/constants.yaml": "{}\n",
    "bible/tracks.yaml": "tracks: []\n",
    "bible/timeline.yaml": "scenes: []\n",
    "research/.gitkeep": "",
}

_BOOK_FILES = {
    "research/.gitkeep": "",
    "scenes/.gitkeep": "",
    "change-requests/.gitkeep": "",
    "reports/.gitkeep": "",
}


def check_book_id(book: str) -> str:
    if not BOOK_ID_RE.match(book):
        raise BookforgeError(
            f"invalid book id '{book}': use lowercase letters, digits, '-' or '_', starting with a letter"
        )
    return book


@dataclass
class Project:
    root: Path
    book: str
    config: Config
    state: BookState

    @property
    def book_dir(self) -> Path:
        return self.root / "books" / self.book

    @property
    def state_path(self) -> Path:
        return self.book_dir / "state.json"

    def save_state(self) -> None:
        save_state(self.state_path, self.state)

    def resolve(self, rel: str | Path) -> Path:
        """Resolve a path inside the series; refuses anything that escapes it."""
        root = self.root.resolve()
        full = (root / rel).resolve()
        if full != root and root not in full.parents:
            raise BookforgeError(f"path escapes the series folder: {rel}")
        return full

    @classmethod
    def open(cls, root: Path, book: str = "b1") -> "Project":
        root = Path(root)
        check_book_id(book)
        if not (root / "books" / book / "state.json").exists():
            raise BookforgeError(f"no book '{book}' in {root} (run `new` first, or check --book)")
        config = load_config(root)
        state = load_state(root / "books" / book / "state.json")
        return cls(root=root, book=book, config=config, state=state)

    @classmethod
    def create(cls, root: Path, premise: str, book: str = "b1") -> "Project":
        root = Path(root)
        check_book_id(book)
        if not premise.strip():
            raise BookforgeError("the premise is empty")
        if root.exists() and any(root.iterdir()):
            raise BookforgeError(f"{root} already exists and is not empty")
        config = load_config()  # host config only; a brand-new series has no override yet
        root.mkdir(parents=True, exist_ok=True)
        vcs.init_repo(root)

        (root / ".gitignore").write_text(_GITIGNORE, encoding="utf-8")
        (root / "premise.md").write_text(premise.rstrip() + "\n", encoding="utf-8")
        for rel, content in _SERIES_FILES.items():
            _write(root / rel, content)
        for rel, content in _BOOK_FILES.items():
            _write(root / "books" / book / rel, content)

        project = cls(root=root, book=book, config=config, state=new_state(book))
        project.save_state()
        vcs.commit(root, f"series: initialized with book {book}")
        log.info("created series at %s (book %s)", root, book)
        return project


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
