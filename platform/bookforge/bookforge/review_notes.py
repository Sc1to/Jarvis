"""Review notes: problems the critic found in a plan that the correction rounds did not resolve.

They never fail a layer. They are kept in books/<book>/reports/review-notes.jsonl, one line per
piece reviewed, for the author (and, from milestone 14.9, the morning report).
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from .project import Project


def path(project: Project) -> Path:
    return project.book_dir / "reports" / "review-notes.jsonl"


def add(project: Project, layer: str, label: str, problems: list[str]) -> None:
    p = path(project)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "layer": layer,
                            "item": label, "problems": problems}, ensure_ascii=False) + "\n")


def read(project: Project, layer: str | None = None) -> list[dict]:
    p = path(project)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if layer is None or rec.get("layer") == layer:
            out.append(rec)
    return out
