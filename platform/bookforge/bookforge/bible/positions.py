"""Ids and positions: b1.act2, b1.ch04, b1.ch04.s3.

A position is a chapter (the start of the chapter) or a scene. Positions in one book
are ordered by (chapter, scene); a chapter counts as scene 0, so a chapter-level entry
applies from the start of the chapter, before its first scene.
Ordering across books is not supported yet: lookups work inside one book.
"""

import re
from dataclasses import dataclass

_POSITION = re.compile(r"^(?P<book>[a-z][a-z0-9_-]*)\.ch(?P<ch>\d+)(?:\.s(?P<s>\d+))?$")
_ACT = re.compile(r"^(?P<book>[a-z][a-z0-9_-]*)\.act(?P<n>\d+)$")


@dataclass(frozen=True)
class Position:
    book: str
    chapter: int
    scene: int | None = None

    @property
    def key(self) -> tuple[int, int]:
        return (self.chapter, self.scene or 0)

    @property
    def id(self) -> str:
        base = chapter_id(self.book, self.chapter)
        return base if self.scene is None else f"{base}.s{self.scene}"

    @property
    def is_scene(self) -> bool:
        return self.scene is not None

    @property
    def chapter_ref(self) -> str:
        return chapter_id(self.book, self.chapter)


def chapter_id(book: str, n: int) -> str:
    return f"{book}.ch{n:02d}"


def scene_id(book: str, chapter: int, n: int) -> str:
    return f"{chapter_id(book, chapter)}.s{n}"


def act_id(book: str, n: int) -> str:
    return f"{book}.act{n}"


def parse_position(text: str) -> Position:
    """Parse b1.ch04 or b1.ch04.s3 (zero padding optional). Raises ValueError."""
    m = _POSITION.match(str(text).strip())
    if not m:
        raise ValueError(f"'{text}' is not a position (expected like b1.ch04 or b1.ch04.s3)")
    chapter = int(m.group("ch"))
    scene = int(m.group("s")) if m.group("s") is not None else None
    if chapter < 1 or (scene is not None and scene < 1):
        raise ValueError(f"'{text}': chapter and scene numbers start at 1")
    return Position(m.group("book"), chapter, scene)


def canonical(text: str) -> str:
    """The standard spelling of a position, e.g. b1.ch4.s3 -> b1.ch04.s3."""
    return parse_position(text).id


def parse_act_id(text: str) -> tuple[str, int]:
    m = _ACT.match(str(text).strip())
    if not m:
        raise ValueError(f"'{text}' is not an act id (expected like b1.act2)")
    return m.group("book"), int(m.group("n"))
