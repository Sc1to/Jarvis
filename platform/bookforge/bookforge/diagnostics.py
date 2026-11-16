"""Bugs of the tool itself, saved where you can find them.

A STRUCTURAL finding (remedies/registry.py) is bookkeeping with one right answer, so it is derived by construction and never asked about. If one
still shows up after the layer's normalisation (bible/normalize.py), the tool got something wrong that it should not have: the run keeps going as
before, and a bundle is saved to `books/<book>/diagnostics/` with the reply as it was parsed, the findings and what the check saw. Nothing about it is
an item for you to answer; the page only says that bundles exist, and the file is what to send when something looks wrong.
"""

import json
from datetime import datetime, timezone

from .remedies import registry

KEEP = 30  # the newest bundles are kept


def folder(project):
    return project.book_dir / "diagnostics"


def record(project, layer: str, key: str, findings: list, context: dict) -> str | None:
    """Save a bundle for the findings among `findings` that the tool already makes impossible (registry.guaranteed). Returns the file name, or None."""
    bad = [f for f in findings if registry.guaranteed(getattr(f, "code", ""), getattr(f, "stage", ""))]
    if not bad:
        return None
    try:
        now = datetime.now(timezone.utc)
        name = f"{now.strftime('%Y%m%d-%H%M%S-%f')}-{layer}-{key.split('.')[-1]}.json"
        folder(project).mkdir(parents=True, exist_ok=True)
        body = {"at": now.isoformat(timespec="seconds"), "layer": layer, "key": key, "codes": sorted({f.code for f in bad}),
                "findings": [f.to_dict() for f in bad], "context": context}
        (folder(project) / name).write_text(json.dumps(body, indent=1, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
        for old in sorted(folder(project).glob("*.json"))[:-KEEP]:
            old.unlink(missing_ok=True)
        return name
    except OSError:  # a diagnostics file that cannot be written must never stop a run
        return None


def listing(project, limit: int = 5) -> dict:
    files = sorted(folder(project).glob("*.json")) if folder(project).exists() else []
    out = []
    for p in files[-limit:][::-1]:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            out.append({"file": p.name, "at": d.get("at", ""), "layer": d.get("layer", ""), "key": d.get("key", ""), "codes": d.get("codes", [])})
        except (OSError, ValueError):
            continue
    return {"count": len(files), "latest": out, "folder": str(folder(project).relative_to(project.root)) if files else ""}
