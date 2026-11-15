"""How much the tool may decide for you, per book: books/<book>/answers.yaml.

mode: `shadow` (the default: the tool only suggests), `assist` (it also settles housekeeping: a sentence that only elaborates an event is attached to
that event, description is waived; each decision is marked as the tool's and can be undone), `auto` (it also answers a minor fact about the world by the book's
policy, recorded as a decision of the tool's: a rule you can undo). An outcome you keep overriding is switched off by itself (see `demoted` in resolve.py). Nothing the tool decides changes what happens in the story:
a new event, a cast entry, a contradiction or a cast conflict is always yours.

waived: synopsis sentences the tool decided need no event (quote, reason, decided_by).
undone: sentences you took back from the tool; it never decides those again.
"""

import yaml

MODES = ("shadow", "assist", "auto")
POLICIES = ("research", "extrapolate", "invent")  # how a fact about the world is answered: look it up, ground it and extend it, or invent it


def path(project):
    return project.book_dir / "answers.yaml"


def load(project) -> dict:
    try:
        data = yaml.safe_load(path(project).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        data = {}
    mode = data.get("mode") if data.get("mode") in MODES else "shadow"
    chosen = data.get("world_facts") if data.get("world_facts") in POLICIES else ""
    return {"mode": mode, "waived": [w for w in data.get("waived") or [] if isinstance(w, dict) and w.get("quote")], "undone": [str(u) for u in data.get("undone") or []],
            "world_facts": chosen, "invention": "minor", "reenabled": {str(k): str(v) for k, v in (data.get("reenabled") or {}).items()}}


def save(project, data: dict) -> None:
    p = path(project)
    p.parent.mkdir(parents=True, exist_ok=True)
    out = {"mode": data["mode"], "waived": data["waived"], "undone": data["undone"]}
    if data.get("reenabled"):
        out["reenabled"] = data["reenabled"]
    if data.get("world_facts"):
        out["world_facts"] = data["world_facts"]
    p.write_text(yaml.safe_dump(out, sort_keys=False, allow_unicode=True), encoding="utf-8")


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


def set_policy(project, world_facts: str) -> dict:
    from .errors import BookforgeError
    if world_facts not in POLICIES and world_facts != "":
        raise BookforgeError(f"unknown policy '{world_facts}' (expected one of: {', '.join(POLICIES)}, or empty to derive it from the realism statement)")
    data = load(project)
    data["world_facts"] = world_facts
    save(project, data)
    return data


_RESEARCH_WORDS = ("historical", "history", "real events", "period-accurate", "accurate to", "documented", "real places", "real people", "true to the period", "real world")
_EXTRAPOLATE_WORDS = ("hard science", "scientifically", "plausible", "physics", "grounded", "realistic science", "near future", "near-future")
_INVENT_WORDS = ("space opera", "fantasy", "myth", "magic", "invented", "alternate", "speculative", "soft science", "secondary world")


def derive_policy(realism: str) -> tuple[str, str]:
    """(policy, why) from the book's realism statement: a plain keyword reading, shown to you and yours to change. Hard words win in the order research,
    extrapolate, invent; a statement that says nothing of the kind gets `extrapolate` (ground the science, invent the institutions)."""
    low = realism.lower()
    for policy, words in (("research", _RESEARCH_WORDS), ("extrapolate", _EXTRAPOLATE_WORDS), ("invent", _INVENT_WORDS)):
        hit = next((w for w in words if w in low), "")
        if hit:
            return policy, f"the realism statement says \"{hit}\""
    return "extrapolate", "the realism statement says nothing decisive: ground what is real, invent the rest" if realism.strip() else "the book has no realism statement yet: ground what is real, invent the rest"


def policy_for(project) -> dict:
    """{"world_facts", "invention", "source"}: what you set, else what the realism statement says."""
    from .realism import realism_setting
    data = load(project)
    if data["world_facts"]:
        return {"world_facts": data["world_facts"], "invention": "minor", "source": "you"}
    policy, why = derive_policy(realism_setting(project))
    return {"world_facts": policy, "invention": "minor", "source": why}


def reenable(project, outcome: str) -> None:
    """Switch an outcome the tool had stopped deciding back on: only decisions from now on count against it."""
    from datetime import datetime, timezone
    data = load(project)
    data["reenabled"][outcome] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save(project, data)
