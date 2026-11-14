"""Deterministic checks of the synopsis itself, before any event is extracted. They find what can be found without a model and give the
model audit its starting points. Nothing here knows any particular book: markers are words of English, names come from the cast."""

import re

from .text import WORD, proper_nouns, sentences

CAUSAL = re.compile(r"\b(only if|only on the condition|on the condition that|on the condition|in exchange for|in return for|provided that|unless|so that|in order to|"
                    r"because|as a result of|only after|only when|only once|but only)\b", re.I)


def causal_sentences(synopsis: str) -> list[dict]:
    """Sentences with a condition or cause marker: {sentence, marker}. The audit asks whether what they depend on comes first."""
    out = []
    for s in sentences(synopsis):
        m = CAUSAL.search(s)
        if m:
            out.append({"sentence": s.strip(), "marker": m.group(1).lower()})
    return out


def cast_tokens(constants) -> set[str]:
    """Lowercase name parts and ids of the cast entities."""
    toks: set[str] = set()
    for e in constants.entities:
        toks |= {w.lower() for w in WORD.findall(e.name)} | {e.id.lower()} | {p for p in e.id.lower().split("-") if p}
    return toks


def unknown_names(synopsis: str, constants) -> list[dict]:
    """Capitalised names in the synopsis that are in nobody's name in the cast: [{name, sentence}]. Empty while there is no cast yet:
    a new book's cast is made later, from the plan, so its absence says nothing."""
    if not constants.entities:
        return []
    known = cast_tokens(constants)
    seen: dict[str, str] = {}
    for s in sentences(synopsis):
        for token in WORD.findall(s)[1:]:
            low = token.lower()
            if token[0].isupper() and low in proper_nouns(s) and low not in known and low not in seen:
                seen[low] = s.strip()
    return [{"name": n, "sentence": s} for n, s in seen.items()]


def cast_roles_absent(synopsis: str, constants) -> list[dict]:
    """Cast characters whose name never occurs in the synopsis: [{id, name}]. Not a finding by itself (an earlier book's cast has people who
    are not in this one); it is a hint for the audit, which asks whether another name now fills their role."""
    low = " ".join(w.lower() for w in WORD.findall(synopsis))
    out = []
    for e in constants.entities:
        if e.kind != "character":
            continue
        parts = [w.lower() for w in WORD.findall(e.name) if len(w) > 2]
        if parts and not any(re.search(rf"\b{re.escape(p)}\b", low) for p in parts):
            out.append({"id": e.id, "name": e.name})
    return out
