"""What you invent in an answer becomes canon, held like a fact the research found.

When an Inbox answer introduces something new (a person, a place, an object, a group, or a rule of the world), the tool records it in your own words:
- a cast entry (`cast.add`) for a person, place, object or group, so `unknown_name` resolves against it, the briefing carries it and a scene that contradicts
  one of its facts is revised (cast facts are fixed facts to the continuity check);
- an approved `invent` need with `canon: true` for a rule, which the briefing carries and the continuity check holds like a fact (a decision of the tool's or
  of the model's only warns).
Everything is taken from your words: a name must be in the answer exactly as written, a fact must be made of the answer's words, a rule must be a sentence of it.
Every record can be undone (books/<book>/canon.yaml says what was added); an entity the book already uses is kept and reported.
"""

import logging
import re
from datetime import datetime, timezone

import yaml

from . import cast as cast_mod
from .errors import BookforgeError
from .validators.ledger import _norm
from .validators.text import content_stems

log = logging.getLogger("platform_bookforge.canon")
KINDS = ("character", "place", "object", "group", "concept")


def path(project):
    return project.book_dir / "canon.yaml"


def load(project) -> list[dict]:
    try:
        data = yaml.safe_load(path(project).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return []
    return [e for e in data.get("entries") or [] if isinstance(e, dict)]


def save(project, entries: list[dict]) -> None:
    p = path(project)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump({"entries": entries}, sort_keys=False, allow_unicode=True), encoding="utf-8")


def active(project) -> list[dict]:
    return [e for e in load(project) if not e.get("undone")]


def _slug(name: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:50] or "entry"
    if not base[0].isalpha():
        base = "x-" + base
    slug, n = base, 2
    while slug in taken:
        slug, n = f"{base}-{n}", n + 1
    return slug


def verify(data: dict, answer: str, cast_names: set[str]) -> dict:
    """{"entities": [...], "rules": [...]} with only what holds up: names exactly as in the answer and not already in the cast, facts made of the
    answer's words, rules that are sentences of the answer."""
    if not isinstance(data, dict):
        return {"entities": [], "rules": []}
    text = _norm(answer)
    answer_stems = set(content_stems(answer))
    entities = []
    for e in data.get("entities") or []:
        if not isinstance(e, dict):
            continue
        name, kind = str(e.get("name", "")).strip(), str(e.get("kind", "")).strip()
        tokens = [t for t in _norm(name).split() if len(t) > 2]
        if not name or kind not in KINDS or _norm(name) not in text or (tokens and all(t in cast_names for t in tokens)):  # already in the cast: every part of its name is
            continue
        facts = []
        for f in e.get("facts") or []:
            stems = set(content_stems(str(f)))
            if stems and len(stems & answer_stems) / len(stems) >= 0.5:
                facts.append(" ".join(str(f).split()))
        if facts:
            entities.append({"name": name, "kind": kind, "facts": facts[:6]})
    rules = [" ".join(str(r).split()) for r in data.get("rules") or [] if str(r).strip() and _norm(str(r)) in text]
    return {"entities": entities, "rules": rules[:4]}


def _cast_names(project) -> set[str]:
    from .bible import store
    try:
        return cast_mod.name_tokens(store.load_constants(project))
    except Exception:
        return set()


def apply(project, item_id: str, question: str, answer: str, found: dict) -> dict | None:
    """Record what the answer introduced. Returns the canon entry, or None when nothing was introduced."""
    from .bible import store
    from .research.notes import MAX_RULE_CHARS_STORED, stores_for
    if not found["entities"] and not found["rules"]:
        return None
    taken = {e.id for e in store.load_constants(project).entities}
    added, need_ids = [], []
    for e in found["entities"]:
        slug = _slug(e["name"], taken)
        try:
            cast_mod.add(project, slug, e["kind"], e["name"], e["facts"])
        except BookforgeError as err:  # a check refused it: leave it out, say so
            log.info("canon: %s not added (%s)", e["name"], err)
            continue
        taken.add(slug)
        added.append(slug)
    book_store = stores_for(project)["book"]
    for rule in found["rules"]:
        need = book_store.add_need(layer="ledger", question=question[:200], stance="invent", reason="invented by you in the Inbox", rule=rule[:MAX_RULE_CHARS_STORED],
                                   status="approved", decided_by="author", canon=True, applies_to=[])
        need_ids.append(need.id)
    if not added and not need_ids:
        return None
    entry = {"id": f"c{len(load(project)) + 1}", "item": item_id, "answer": answer, "entities": added, "needs": need_ids, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "undone": False}
    save(project, load(project) + [entry])
    return entry


def undo(project, canon_id: str) -> dict:
    """Take back what an answer added: its cast entries (an entry the book already uses is kept, and says so) and its rules."""
    from .research.notes import stores_for
    entries = load(project)
    entry = next((e for e in entries if e["id"] == canon_id and not e.get("undone")), None)
    if entry is None:
        raise BookforgeError(f"no active canon entry {canon_id}")
    kept = []
    for slug in entry.get("entities", []):
        try:
            cast_mod.delete(project, slug)
        except BookforgeError:
            kept.append(slug)
    book_store = stores_for(project)["book"]
    for need in book_store.needs():
        if need.id in entry.get("needs", []):
            need.status, need.decided_by, need.canon = "rejected", "author", False
            book_store.save_need(need)
    entry["undone"], entry["kept"] = True, kept
    save(project, entries)
    return entry


def intake(project, item_id: str, question: str, answer: str, llm) -> dict | None:
    """After an answer: ask the model what it introduces, keep only what holds up, record it. Never raises: a failed call records nothing."""
    from .layers.document import prompt_values
    from .prompts import render
    from .qc.support import parse_json_object
    if llm is None or len(answer.split()) < 4:
        return None
    try:
        for old in active(project):  # answering again replaces what the earlier answer introduced
            if old["item"] == item_id:
                undo(project, old["id"])
        names = _cast_names(project)
        from .bible import store
        cast = ", ".join(e.name for e in store.load_constants(project).entities) or "(none yet)"
        text = llm.complete(project.config.layers["ledger"].model, [{"role": "system", "content": render("system", project.root, **prompt_values(project))},
                                                                     {"role": "user", "content": render("canon_intake", project.root, question=question, answer=answer, cast=cast)}], max_tokens=700)
        found = verify(parse_json_object(text) or {}, answer, names)
        return apply(project, item_id, question, answer, found)
    except Exception as e:  # recording canon must never fail an answer
        log.info("canon intake skipped: %s", e)
        return None
