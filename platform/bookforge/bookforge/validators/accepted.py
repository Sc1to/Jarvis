"""Findings the author accepted: books/<book>/validation/accepted.json.

The checks are heuristics, and a model cannot always satisfy one that is wrong about this book. A hard finding you accept stays in the
report (marked accepted, now soft) and no longer stops the stage or asks the model to change anything. Accepting is per finding: the
same code on the same items. A different finding of the same kind still blocks.
"""

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from .findings import HARD, SOFT, Finding
from . import store as findings_store


def path(project) -> Path:
    return project.book_dir / "validation" / "accepted.json"


def fingerprint(stage: str, code: str, items) -> str:
    return f"{stage}:{code}:{','.join(sorted(str(i) for i in items))}"


def load(project) -> dict[str, dict]:
    try:
        data = json.loads(path(project).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(project, data: dict) -> None:
    p = path(project)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def accept(project, stage: str, code: str, items: list[str], message: str = "") -> str:
    fp = fingerprint(stage, code, items)
    data = load(project)
    data[fp] = {"stage": stage, "code": code, "items": list(items), "message": message[:300], "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    _save(project, data)
    return fp


def unaccept(project, fp: str) -> bool:
    data = load(project)
    if fp not in data:
        return False
    del data[fp]
    _save(project, data)
    return True


def apply(project, findings: list[Finding], stage: str | None = None) -> list[Finding]:
    """The findings with the accepted hard ones turned soft (and marked), so they no longer block."""
    known = load(project)
    if not known:
        return findings
    out = []
    for f in findings:
        if f.severity == HARD and fingerprint(stage or f.stage, f.code, f.items) in known:
            f = replace(f, severity=SOFT, accepted=True, message=f"(accepted by you) {f.message}")
        out.append(f)
    return out


def hard_lines(project, findings: list[Finding], stage: str) -> list[str]:
    """The lines of the hard findings that remain after the accepted ones are set aside. When there are some, they are saved to
    validation/<stage>.json so the dashboard can show them (and offer to accept them) even though the stage failed."""
    findings = apply(project, findings, stage)
    lines = [f.line() for f in findings if f.severity == HARD]
    if lines:
        findings_store.save(project, stage, [replace(f, stage=stage) for f in findings], {"attempt": True})
    return lines
