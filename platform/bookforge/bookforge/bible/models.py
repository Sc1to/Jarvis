"""Typed records for the bible and the structure files, with plain-language problem reports.

Unknown keys a model adds are ignored. Every file is written back from these records,
so what is stored is always the validated form.
"""

import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints, ValidationError


def as_text(value):
    """Give back the sentence the model wrote when YAML read it as something else.

    A beat like `- Jonas confronts her: she lies` is valid YAML, but it is read as the mapping {"Jonas confronts her": "she lies"};
    a title like `1883` is read as a number and a date like `1883-04-12` as a date. Anything else is returned unchanged.
    """
    scalar = (str, int, float, bool, datetime.date, datetime.datetime)
    if isinstance(value, dict) and len(value) == 1:
        key, inner = next(iter(value.items()))
        if isinstance(key, scalar) and (inner is None or isinstance(inner, scalar)):
            return f"{as_text(key)}: {as_text(inner)}" if inner is not None else f"{as_text(key)}:"
        return value
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return value


Slug = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]*$", max_length=60)]
Text = Annotated[str, BeforeValidator(as_text), StringConstraints(strip_whitespace=True, min_length=1)]
Loose = Annotated[str, BeforeValidator(as_text)]  # free text that may be empty (a date, a travel note)

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
    value: Annotated[str, BeforeValidator(as_text), StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
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
    date: Loose = ""  # optional calendar date in the book's own calendar
    flashback: bool = False  # story time runs backwards here
    travel: Loose = ""  # optional note on travel since the previous scene


def problems_from(error: ValidationError, limit: int = 8) -> list[str]:
    """Short, readable problems from a pydantic error, safe to send back to a model."""
    out = []
    for e in error.errors()[:limit]:
        where = ".".join(str(p) for p in e["loc"]) or "(top level)"
        if e["type"] == "string_type":
            kind = {dict: "a mapping (key: value)", list: "a list", type(None): "empty", bool: "yes/no"}.get(type(e.get("input")), type(e.get("input")).__name__)
            out.append(f"{where}: must be one piece of text but is {kind}; write it as a single sentence inside double quotes")
            continue
        out.append(f"{where}: {e['msg']}")
    if len(error.errors()) > limit:
        out.append(f"... and {len(error.errors()) - limit} more")
    return out
