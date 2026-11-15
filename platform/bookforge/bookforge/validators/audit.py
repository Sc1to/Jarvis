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


_CONDITIONAL = ("only if", "only on the condition", "on the condition that", "on the condition", "in exchange for", "in return for", "provided that", "unless", "but only", "only when", "only once", "only after")


def condition_after_effect(synopsis: str, window: int = 8) -> list[dict]:
    """A condition stated AFTER the thing it conditions has already happened. For a sentence with a condition marker ("only on the condition", "in
    exchange for"), the nearest earlier sentence that tells what its main clause grants (they share content words, names left out) is the thing
    already done: {earlier, condition, marker}. Found without a model, quoted exactly, and put to the author as a question."""
    from .ledger import _plain_stems, paragraphs
    flat = [x for para in paragraphs(synopsis) for x in sentences(para)]
    out = []
    for i, s in enumerate(flat):
        m = CAUSAL.search(s)
        if not m or m.group(1).lower() not in _CONDITIONAL:
            continue
        main = _plain_stems(s[:m.start()])
        if not main:
            continue
        for j in range(i - 1, max(-1, i - 1 - window), -1):  # the nearest earlier sentence first
            shared = main & _plain_stems(flat[j])
            if shared and len(shared) / len(main) >= 0.5:
                out.append({"earlier": flat[j].strip(), "condition": s.strip(), "marker": m.group(1).lower(), "shared": sorted(shared)})
                break
    return out


def unintroduced_things(synopsis: str, constants=None, limit: int = 6) -> list[dict]:
    """Things first mentioned with "the" late in the text, as if the reader already knew them ("the report" when no report was ever written): [{noun, sentence}]. Only a starting point for the audit: many are things the reader may take for granted."""
    from .ledger import paragraphs
    known = cast_tokens(constants) if constants is not None else set()
    seen: set[str] = set()
    out = []
    for n, para in enumerate(paragraphs(synopsis)):
        for s in sentences(para):
            for m in re.finditer(r"\b(?:the|The)\s+([a-z]{3,})\b", s):
                noun = m.group(1).lower()
                if noun in seen or noun in known or noun in STOP_NOUNS:
                    continue
                seen.add(noun)
                earlier = " ".join(paragraphs(synopsis)[:n]).lower() + " " + s[:m.start()].lower()
                if n >= 2 and not re.search(rf"\b{re.escape(noun)}s?\b", earlier):
                    out.append({"noun": noun, "sentence": s.strip(), "mentions": len(re.findall(rf"\b{re.escape(noun)}s?\b", synopsis.lower()))})
            seen |= {w.lower() for w in WORD.findall(s)}
    # a thing the text comes back to matters more than one it mentions once: most mentioned first
    return sorted((o for o in out if o["mentions"] >= 2), key=lambda o: -o["mentions"])[:limit]


STOP_NOUNS = frozenset("""
end rest same first last other next only very most whole main center middle edge side top bottom front back
""".split())


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
    from .ledger import paragraphs
    known = cast_tokens(constants)
    seen: dict[str, str] = {}
    for s in [x for para in paragraphs(synopsis) for x in sentences(para)]:  # prose only: a heading's words are not names
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
