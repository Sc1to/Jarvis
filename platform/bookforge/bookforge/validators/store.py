"""Findings on disk: books/<book>/validation/<stage>.json, what the UI and the morning report show next to each stage."""

import json
from pathlib import Path

from .findings import Finding, summarize


def path(project, stage: str) -> Path:
    return project.book_dir / "validation" / f"{stage}.json"


def save(project, stage: str, findings: list[Finding], extra: dict | None = None) -> str:
    p = path(project, stage)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"stage": stage, "summary": summarize(findings), "findings": [f.to_dict() for f in findings], **(extra or {})},
                            indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return str(p.relative_to(project.root))


def load(project, stage: str) -> dict:
    try:
        return json.loads(path(project, stage).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"stage": stage, "summary": {"hard": 0, "soft": 0, "codes": []}, "findings": []}
