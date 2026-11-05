"""What is true at a point in the story.

`state_at(tracks, "b1.ch05.s2")` answers, for every track, the value in force during that
scene: the latest plan entry whose position is at or before it. A track has no state
before its first entry. Entries that start at the scene itself are flagged `begins_here`,
and `must_show` ones are obligations the scene has to fulfil on the page.
"""

from dataclasses import dataclass
from typing import Iterable

from .models import Constants, Entity, Scene, TimelineEntry, Track
from .positions import parse_position


@dataclass(frozen=True)
class TrackState:
    track_id: str
    entity: str
    kind: str
    value: str
    since: str  # position of the plan entry in force
    begins_here: bool  # the entry starts exactly at the queried position
    must_show: bool  # begins here AND has to happen on the page
    previous: str | None  # the value before this entry, if any
    version: int


def state_at(tracks: Iterable[Track], position: str, entities: Iterable[str] | None = None) -> list[TrackState]:
    pos = parse_position(position)
    wanted = None if entities is None else set(entities)
    states: list[TrackState] = []
    for t in tracks:
        if wanted is not None and t.entity not in wanted:
            continue
        in_book = [e for e in t.plan if parse_position(e.from_).book == pos.book]
        in_book.sort(key=lambda e: parse_position(e.from_).key)
        current = None
        previous = None
        for e in in_book:
            if parse_position(e.from_).key <= pos.key:
                previous = current.value if current else None
                current = e
            else:
                break
        if current is None:
            continue
        begins = parse_position(current.from_).key == pos.key
        states.append(TrackState(
            track_id=t.id, entity=t.entity, kind=t.kind, value=current.value, since=parse_position(current.from_).id,
            begins_here=begins, must_show=begins and current.must_show, previous=previous, version=t.version,
        ))
    return states


def obligations_at(tracks: Iterable[Track], scene: str) -> list[TrackState]:
    """The states this exact scene must show on the page."""
    return [s for s in state_at(tracks, scene) if s.must_show]


def scene_entities(scenes: Iterable[Scene], scene: str) -> set[str]:
    """The entities a scene touches: the characters present and the setting."""
    for s in scenes:
        if s.id == scene:
            return set(s.characters) | {s.pov, s.setting}
    return set()


def constants_for(constants: Constants, entity_ids: Iterable[str]) -> list[Entity]:
    wanted = set(entity_ids)
    return [e for e in constants.entities if e.id in wanted]


def day_of(timeline: Iterable[TimelineEntry], scene: str) -> int | None:
    for e in timeline:
        if e.id == scene:
            return e.day
    return None


def elapsed_days(timeline: Iterable[TimelineEntry], earlier: str, later: str) -> int | None:
    """Story days between two scenes (negative if `later` is earlier in story time, for example a flashback)."""
    entries = list(timeline)
    a, b = day_of(entries, earlier), day_of(entries, later)
    return None if a is None or b is None else b - a
