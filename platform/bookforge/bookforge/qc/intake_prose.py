"""Intake from the prose: a written scene that brings in something the plan does not have becomes a change request.

Two kinds, both decided by you like any change request (approve = the plan follows the prose, reject = the scene is brought back to the plan, dismiss):
- a NEW ENTITY: a capitalised name that appears at least twice and is in nobody's name in the cast. A deterministic pass finds the candidates (no model); one narrow
  call per scene, only when there are candidates, sorts a new person/place from an alias or a passing mention, and must quote the scene;
- a NEW EVENT: a development the critic says the scene tells that no beat contains (`unplanned` in the critic's report, no extra call), with its quote checked against the text.
Nothing is changed in the plan or the cast here; the requests only wait for you.
"""
import logging
import re

from ..bible import store
from ..errors import BookforgeError
from ..validators.names import cast_index
from ..validators.text import WORD, proper_nouns
from .support import ask_json, quote_in_page

log = logging.getLogger("platform_bookforge.qc")
MIN_MENTIONS = 2
MAX_CANDIDATES = 6


def candidate_names(text: str, constants) -> list[str]:
    """Capitalised names the scene uses at least twice that the cast has under nobody's name."""
    if not constants.entities:
        return []
    known = set().union(*cast_index(constants).values()) | {w.lower() for e in constants.entities for w in WORD.findall(e.name)}
    found: dict[str, int] = {}
    low = " ".join(w.lower() for w in WORD.findall(text))
    for n in {re.sub(r"[’']s$", "", x) for x in proper_nouns(text)}:
        if n in known or len(n) < 3:
            continue
        found[n] = len(re.findall(rf"\b{re.escape(n)}\b", low))
    return [n for n, c in sorted(found.items(), key=lambda kv: -kv[1]) if c >= MIN_MENTIONS][:MAX_CANDIDATES]


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s if s[:1].isalpha() else "x" + s


def new_entities(ctx, scene, text: str) -> list[dict]:
    """[{kind: "entity", name, entity_kind, quote, facts, same_as}] for names the scene introduces. [] when nothing qualifies or the model is unavailable."""
    project = ctx.project
    constants = store.load_constants(project)
    names = candidate_names(text, constants)
    if not names or ctx.llm is None:
        return []
    ids = {e.id for e in constants.entities}

    def check(data: dict) -> list[str]:
        items = data.get("names")
        if not isinstance(items, list):
            return ['the reply must be {"names": [...]}']
        return [] if all(isinstance(i, dict) and i.get("verdict") in ("new_entity", "alias", "detail", "not_a_name") for i in items) else ['"verdict" must be new_entity, alias, detail or not_a_name']

    try:
        data = ask_json(ctx, f"{scene.id} new names", project.config.layers["scenes"].model, "intake_prose", check, max_tokens=900,
                        text=text, cast="\n".join(f"- {e.id}: {e.name}" for e in constants.entities), names="\n".join(f"- {n}" for n in names))
    except BookforgeError as e:
        log.info("%s: new names not sorted (%s)", scene.id, e)
        return []
    out: list[dict] = []
    for item in data.get("names", []):
        if not isinstance(item, dict) or item.get("verdict") not in ("new_entity", "alias"):
            continue
        name = " ".join(str(item.get("name", "")).split())
        quote = " ".join(str(item.get("quote", "")).split())
        if not name or name.lower() not in {n.lower() for n in names} or not quote or not quote_in_page(quote, text):
            continue  # a name we did not ask about, or no quotable words: dropped
        same = str(item.get("same_as", "")).strip()
        stems = {w.lower() for w in WORD.findall(text)}
        facts = [" ".join(str(f).split())[:240] for f in item.get("facts") or [] if isinstance(f, str) and f.strip()
                 and {w.lower() for w in WORD.findall(f) if len(w) > 3} <= stems | {name.lower()}][:2]  # only what the scene's own words say
        kind = str(item.get("kind", "character")).strip().lower()
        out.append({"kind": "entity", "name": name, "entity_kind": kind if kind in ("character", "place", "object", "group", "concept") else "character",
                    "quote": quote, "facts": facts or [quote[:240]], "same_as": same if same in ids else ""})
    return out


def new_events(review: dict, text: str) -> list[dict]:
    """[{kind: "event", text, quote}] from the critic's `unplanned` list (already quote-checked)."""
    unplanned = (review.get("critic") or {}).get("unplanned") or []
    return [{"kind": "event", "text": u["what"], "quote": u["quote"]} for u in unplanned if u.get("what") and u.get("quote") and quote_in_page(u["quote"], text)]


def find(ctx, scene, text: str, review: dict) -> list[dict]:
    return new_entities(ctx, scene, text) + new_events(review, text)
