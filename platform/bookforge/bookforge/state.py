"""state.json: status per layer, per item, and per checkpoint (books/<book>/state.json)."""

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError

from .constants import CHECKPOINTS, CHECKPOINT_STATUSES, LAYER_ORDER, STATE_SCHEMA_VERSION, STATUSES
from .errors import StateError

Status = Literal["pending", "drafted", "checked", "accepted", "stale", "flagged"]
CheckpointStatus = Literal["pending", "waiting", "approved"]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Item(BaseModel):
    status: Status = "pending"
    version: int = 0  # bumped each time the item is accepted; dependency tracking (14.8) keys on it
    updated: str | None = None
    note: str | None = None


class Checkpoint(BaseModel):
    status: CheckpointStatus = "pending"
    reached_at: str | None = None
    approved_at: str | None = None


class BookState(BaseModel):
    schema_version: int = STATE_SCHEMA_VERSION
    book: str
    created: str
    layers: dict[str, Item]
    items: dict[str, Item] = {}  # per-chapter / per-scene records, added from milestone 14.5
    checkpoints: dict[str, Checkpoint]

    def set_layer_status(self, layer: str, status: str, note: str | None = None) -> None:
        if layer not in self.layers:
            raise StateError(f"unknown layer: {layer}")
        if status not in STATUSES:
            raise StateError(f"unknown status: {status}")
        item = self.layers[layer]
        item.status = status  # type: ignore[assignment]
        item.updated = now()
        item.note = note
        if status == "accepted":
            item.version += 1

    def reach_checkpoint(self, name: str) -> None:
        cp = self._checkpoint(name)
        if cp.status == "pending":
            cp.status = "waiting"
            cp.reached_at = now()

    def approve_checkpoint(self, name: str) -> None:
        cp = self._checkpoint(name)
        if cp.status != "waiting":
            raise StateError(
                f"checkpoint '{name}' is not waiting for approval (status: {cp.status})"
            )
        cp.status = "approved"
        cp.approved_at = now()

    def _checkpoint(self, name: str) -> Checkpoint:
        if name not in self.checkpoints:
            raise StateError(f"unknown checkpoint '{name}' (expected one of: {', '.join(CHECKPOINTS)})")
        return self.checkpoints[name]


def new_state(book: str) -> BookState:
    return BookState(
        book=book,
        created=now(),
        layers={name: Item() for name in LAYER_ORDER},
        checkpoints={name: Checkpoint() for name in CHECKPOINTS},
    )


def load_state(path: Path) -> BookState:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise StateError(f"state file not found: {path}") from e
    except (OSError, json.JSONDecodeError) as e:
        raise StateError(f"cannot read state file {path}: {e}") from e
    if not isinstance(raw, dict) or raw.get("schema_version") != STATE_SCHEMA_VERSION:
        raise StateError(
            f"{path}: unsupported schema_version "
            f"{raw.get('schema_version') if isinstance(raw, dict) else None} (expected {STATE_SCHEMA_VERSION})"
        )
    try:
        return BookState.model_validate(raw)
    except ValidationError as e:
        raise StateError(f"{path} is not valid: {e}") from e


def save_state(path: Path, state: BookState) -> None:
    """Write atomically so a crash mid-write never leaves a half-written state.json."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".state-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(state.model_dump_json(indent=2))
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


# Re-exported for callers that validate input.
__all__ = ["BookState", "Item", "Checkpoint", "new_state", "load_state", "save_state", "CHECKPOINT_STATUSES"]
