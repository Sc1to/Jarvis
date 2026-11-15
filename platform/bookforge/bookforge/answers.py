"""How much the tool may decide for you, per book: books/<book>/answers.yaml.

mode: `shadow` (the default: the tool only suggests), `assist` (it also settles housekeeping: a sentence that only elaborates an event is attached to
that event, description is waived; each decision is marked as the tool's and can be undone). Nothing the tool decides changes what happens in the story:
a new event, a cast entry, a contradiction or a cast conflict is always yours.

waived: synopsis sentences the tool decided need no event (quote, reason, decided_by).
undone: sentences you took back from the tool; it never decides those again.
"""

import yaml

MODES = ("shadow", "assist")


def path(project):
    return project.book_dir / "answers.yaml"


def load(project) -> dict:
    try:
        data = yaml.safe_load(path(project).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        data = {}
    mode = data.get("mode") if data.get("mode") in MODES else "shadow"
    return {"mode": mode, "waived": [w for w in data.get("waived") or [] if isinstance(w, dict) and w.get("quote")], "undone": [str(u) for u in data.get("undone") or []]}


def save(project, data: dict) -> None:
    p = path(project)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump({"mode": data["mode"], "waived": data["waived"], "undone": data["undone"]}, sort_keys=False, allow_unicode=True), encoding="utf-8")


def set_mode(project, mode: str) -> dict:
    from .errors import BookforgeError
    if mode not in MODES:
        raise BookforgeError(f"unknown mode '{mode}' (expected one of: {', '.join(MODES)})")
    data = load(project)
    data["mode"] = mode
    save(project, data)
    return data


def waive(project, quote: str, reason: str) -> None:
    data = load(project)
    if not any(w["quote"] == quote for w in data["waived"]):
        data["waived"].append({"quote": quote, "reason": reason, "decided_by": "tool"})
    save(project, data)


def take_back(project, quote: str) -> None:
    """Undo: the sentence is no longer waived, and the tool leaves it alone from now on."""
    data = load(project)
    data["waived"] = [w for w in data["waived"] if w["quote"] != quote]
    if quote not in data["undone"]:
        data["undone"].append(quote)
    save(project, data)


def is_undone(data: dict, sentence: str) -> bool:
    from .validators.ledger import _norm
    n = _norm(sentence)
    return any(_norm(u)[:60] and _norm(u)[:60] in n for u in data["undone"])
