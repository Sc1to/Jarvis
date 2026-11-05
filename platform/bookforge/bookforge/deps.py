"""deps.yaml: exactly what a scene's prose was built from, as content fingerprints.

An entry is `id@fingerprint`, where the fingerprint is the first 8 hex digits of the SHA-256 of
the record's content. Unlike a version counter it changes whenever the content changes, however
the change was made, so a hand edit of a file counts too. Comparing a scene's deps.yaml with the
current fingerprints (milestone 14.8) shows what went stale and why.
"""

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

KEYS = ("scene", "parent", "north_stars", "style", "bible", "research", "timeline", "previous", "summaries")


def fingerprint(value) -> str:
    if not isinstance(value, str):
        value = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]


def tag(item_id: str, value) -> str:
    return f"{item_id}@{fingerprint(value)}"


@dataclass
class Deps:
    scene: str = ""
    parent: str = ""
    north_stars: list[str] = field(default_factory=list)
    style: list[str] = field(default_factory=list)
    bible: list[str] = field(default_factory=list)
    research: list[str] = field(default_factory=list)
    timeline: list[str] = field(default_factory=list)
    previous: list[str] = field(default_factory=list)
    summaries: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in KEYS}

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.to_dict(), sort_keys=False, default_flow_style=None, width=100)

    @classmethod
    def from_dict(cls, data: dict) -> "Deps":
        return cls(**{k: data.get(k, [] if k not in ("scene", "parent") else "") for k in KEYS})


def write_deps(path: Path, deps: Deps) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(deps.to_yaml(), encoding="utf-8")


def read_deps(path: Path) -> Deps | None:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    return Deps.from_dict(data) if isinstance(data, dict) else None
