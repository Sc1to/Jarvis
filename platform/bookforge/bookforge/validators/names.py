"""Who a chapter or scene is about, and whether every name in it is in the cast.

The point-of-view character must be in the text and be its main viewpoint: a chapter marked as one character's whose summary follows two others
(or names a person the cast does not have) is wrong before any prose is written. Every proper name in a plan must also resolve to a cast entry."""

import re

from .findings import Finding, hard, soft
from .text import WORD, proper_nouns, sentences


def _tokens(entity) -> set[str]:
    return {w.lower() for w in WORD.findall(entity.name) if len(w) >= 3} | {p for p in entity.id.lower().split("-") if len(p) >= 3}


def cast_index(constants) -> dict[str, set[str]]:
    """entity id -> the lowercase name parts that stand for it in text."""
    return {e.id: _tokens(e) for e in constants.entities}


def _mentions(text: str, tokens: set[str]) -> int:
    low = " ".join(w.lower() for w in WORD.findall(text))
    return sum(len(re.findall(rf"\b{re.escape(t)}\b", low)) for t in tokens)


def pov_findings(units: list[dict], constants, stage: str, text_keys=("purpose", "summary")) -> list[Finding]:
    """For each unit (a chapter or scene dict with `pov`): the POV character appears in its text, and is its main person. `text_keys` name the
    fields read; a scene's beats count as text."""
    index = cast_index(constants)
    characters = {e.id for e in constants.entities if e.kind == "character"}
    out: list[Finding] = []
    for u in units:
        pov = u.get("pov") or ""
        if pov not in index or pov not in characters:
            continue  # an unknown POV is reported where ids are checked
        text = " ".join([str(u.get(k, "")) for k in text_keys] + [str(b) for b in (u.get("beats") or [])])
        if not text.strip():
            continue
        own = _mentions(text, index[pov])
        others = {c: _mentions(text, index[c]) for c in characters if c != pov and not (index[c] & index[pov])}
        top_id, top = max(others.items(), key=lambda kv: kv[1], default=(None, 0))
        first = sentences(text)[0] if sentences(text) else ""
        named = [c for c, n in others.items() if n]
        if own == 0 and named:  # a text that names nobody follows its viewpoint character by pronoun, and one that names a single other person may be told from the one they act on
            make = hard if len(named) >= 2 else soft
            out.append(make(stage, "pov_not_in_text", f"{u['id']} is told from {pov}'s point of view but its text never mentions {pov} and follows {', '.join(named[:3])} instead: "
                            "make the viewpoint character the one it follows, or change its pov", [u["id"], pov], [text[:160]]))
        elif top > own and _mentions(first, index[pov]) == 0:
            out.append(soft(stage, "pov_not_main", f"{u['id']} is told from {pov}'s point of view but its text is mostly about {top_id} ({top} mentions against {own}): check whose chapter it is",
                            [u["id"], pov, top_id], [text[:160]]))
    return out


def unknown_names(units: list[dict], constants, stage: str, text_keys=("purpose", "summary", "end_state"), allowed: set[str] = frozenset()) -> list[Finding]:
    """Capitalised names in a plan's text that are in nobody's name in the cast (soft: one finding per unit listing them). A cast that does not exist
    yet judges nothing."""
    if not constants.entities:
        return []
    known = set().union(*cast_index(constants).values()) | {t.lower() for t in allowed} | {w.lower() for e in constants.entities for w in WORD.findall(e.name)}
    out: list[Finding] = []
    for u in units:
        text = " ".join(str(u.get(k, "")) for k in text_keys) + " " + " ".join(str(b) for b in (u.get("beats") or []))
        names = sorted({re.sub(r"[\u2019']s$", "", n) for n in proper_nouns(text)})  # "Halloway's" is Halloway
        names = [n for n in names if n not in known and len(n) >= 3]
        if names:
            out.append(soft(stage, "unknown_name", f"{u['id']} names {', '.join(names[:5])}, which is in nobody's name in the cast: add them to the cast, or use the name the cast already has", [u["id"]] + names[:5], [text[:160]]))
    return out
