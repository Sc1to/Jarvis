"""Append-only JSONL log of every model and web call (books/<book>/logs/calls.jsonl)."""

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("platform_bookforge.calllog")


class CallLog:
    def __init__(self, path: Path | None):
        self.path = path
        self._lock = threading.Lock()

    def write(self, record: dict) -> None:
        """Never raises: a logging problem must not fail a model call."""
        if self.path is None:
            return
        line = json.dumps(
            {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), **record},
            ensure_ascii=False, default=str,
        )
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except OSError as e:
            log.warning("could not write call log %s: %s", self.path, e)
