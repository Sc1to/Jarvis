"""Typed records for the bible and the structure files, with plain-language problem reports.

Unknown keys a model adds are ignored. Every file is written back from these records,
so what is stored is always the validated form.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

Slug = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]*$", max_length=60)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

ENTITY_KINDS = ("character", "place", "object", "group", "concept")
TRACK_KINDS = ("physical", "location", "relationship", "possession", "knowledge", "status", "other")


class _Record(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class Entity(_Record):
    id: Slug
    kind: Literal["character", "place", "object", "group", "concept"]
    name: Text
    facts: list[Text] = Field(min_length=1)  # things that never change


class Rule(_Record):
    id: Slug
    text: Text


class Constants(_Record):
    entities: list[Entity] = []
    rules: list[Rule] = []


class PlanEntry(_Record):
    from_: str = Field(alias="from")  # a chapter id (from the start of the chapter) or a scene id
    value: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
    must_show: bool = False  # the change itself must happen on the page in that scene


class Track(_Record):
    id: Slug
    entity: Slug
    kind: Literal["physical", "location", "relationship", "possession", "knowledge", "status", "other"] = "other"
    version: int = Field(1, ge=1)  # bumped when the plan changes after it was first written
    plan: list[PlanEntry] = Field(min_length=1)
    observed: list[dict] = []  # filled from the prose after each scene (milestone 14.7)


class Act(_Record):
    id: str
    title: Text
    summary: Text
    purpose: Text
    turning_point: Text
    chapter_count: int = Field(ge=1, le=60)


class Chapter(_Record):
    id: str
    act: str = ""
    title: Text
    purpose: Text
    summary: Text
    pov: Slug
    setting: Slug
    tension: int = Field(ge=1, le=10)
    research: list[str] = []


class Scene(_Record):
    id: str
    chapter: str = ""
    purpose: Text
    pov: Slug
    setting: Slug
    characters: list[Slug] = Field(min_length=1)
    beats: list[Text] = Field(min_length=2, max_length=10)
    research: list[str] = []


class TimelineEntry(_Record):
    id: str  # scene id
    day: int = Field(ge=1)  # story day, counted from day 1 at the start of the story
    time: Text  # time of day or similar: "dusk", "just after midnight"
    date: str = ""  # optional calendar date in the book's own calendar
    flashback: bool = False  # story time runs backwards here
    travel: str = ""  # optional note on travel since the previous scene


def problems_from(error: ValidationError, limit: int = 8) -> list[str]:
    """Short, readable problems from a pydantic error, safe to send back to a model."""
    out = []
    for e in error.errors()[:limit]:
        where = ".".join(str(p) for p in e["loc"]) or "(top level)"
        out.append(f"{where}: {e['msg']}")
    if len(error.errors()) > limit:
        out.append(f"... and {len(error.errors()) - limit} more")
    return out
