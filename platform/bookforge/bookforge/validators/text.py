"""Small language-neutral-ish text helpers for the validators: tokens, stems, similarity. No models, no corpus files."""

import re
from collections import Counter

WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*|\d+")
SENT = re.compile(r"(?<=[.!?…])[\"”’»)]*\s+")

STOP = frozenset("""
a about above after again all also am an and any are as at be because been before being below between both but by can
could did do does doing down during each few for from further had has have having he her here hers herself him himself
his how i if in into is it its itself just me more most my myself no nor not now of off on once only or other our ours
out over own same she should so some such than that the their theirs them themselves then there these they this those
through to too under until up very was we were what when where which while who whom why will with would you your yours
yourself said asked says say then again still back one two three another before after toward towards back
""".split())

# Generic English action vocabulary, grouped so that paraphrases of one action compare as equal. Nothing here is about any
# particular story: these are the common verbs stories use for movement, discovery, force, flight and the like.
_VERB_CLASSES = {
    "ENTER": "enter board aboard infiltrate inside climb step slip",
    "LEAVE": "leave depart exit flee escape evade withdraw retreat",
    "FIND": "find discover locate uncover spot unearth retrieve recover",
    "FORCE": "force pry break smash crack jimmy batter wrench",
    "OPEN": "open unlock unseal unbolt unlatch",
    "SEE": "see notice watch observe glimpse spot",
    "HIDE": "hide conceal stash bury",
    "FIGHT": "fight attack strike hit struggle clash",
    "SPEAK": "tell say speak explain confess reveal admit",
    "GO": "go walk move head travel run hurry",
}


def stem(word: str) -> str:
    w = word.lower().strip("'’-")
    if w.endswith("'s") or w.endswith("’s"):
        w = w[:-2]
    for suf, rep in (("ies", "y"), ("ings", ""), ("ing", ""), ("edly", ""), ("ied", "y"), ("ed", ""), ("es", ""), ("ly", ""), ("s", "")):
        if w.endswith(suf) and len(w) - len(suf) + len(rep) >= 3:
            if suf == "s" and w.endswith("ss"):
                continue
            w = w[: len(w) - len(suf)] + rep
            break
    if len(w) > 4 and w[-1] == w[-2] and w[-1] not in "aeiouls":  # stopp -> stop
        w = w[:-1]
    if len(w) > 4 and w.endswith("e"):  # decide / decides / deciding all become 'decid'
        w = w[:-1]
    return w


_CLASS = {}
for _label, _words in _VERB_CLASSES.items():
    for _w in _words.split():
        _CLASS[stem(_w)] = _label


def canon(token: str) -> str:
    s = stem(token)
    return _CLASS.get(s, s)


def sentences(text: str) -> list[str]:
    return [s.strip() for s in SENT.split(" ".join(text.split())) if s.strip()]


def proper_nouns(text: str) -> set[str]:
    """Capitalised words that are not at the start of a sentence: names of people, places and things."""
    out: set[str] = set()
    for s in sentences(text):
        toks = WORD.findall(s)
        for t in toks[1:]:
            if t[0].isupper() and t.lower() not in STOP:
                out.add(t.lower())
    return out


def content_stems(text: str, drop: set[str] = frozenset()) -> list[str]:
    """Stems of the content words (stopwords, proper nouns in `drop` and one-letter tokens removed), verb classes merged."""
    out = []
    for t in WORD.findall(text):
        low = t.lower()
        if low in STOP or low in drop or len(low) < 3:
            continue
        out.append(canon(t))
    return out


def dice(a: set, b: set) -> float:
    return 0.0 if not a or not b else 2 * len(a & b) / (len(a) + len(b))


class Unit:
    """One comparable piece of plan text: a sentence of a chapter summary, or one scene beat."""

    __slots__ = ("id", "chapter", "text", "stems", "names", "kind")

    def __init__(self, id: str, chapter: str, text: str, names_known: set[str] = frozenset(), kind: str = "beat"):
        self.id, self.chapter, self.text, self.kind = id, chapter, text, kind
        self.names = {n for n in proper_nouns(text)} | {w.lower() for w in WORD.findall(text) if w.lower() in names_known}
        self.stems = set(content_stems(text, drop=self.names))


def similar(a: Unit, b: Unit, threshold: float = 0.5, min_shared: int = 3) -> bool:
    shared = a.stems & b.stems
    if len(shared) < min_shared or dice(a.stems, b.stems) < threshold:
        return False
    if a.names and b.names and not (a.names & b.names):
        return False  # same action by different people is a different event
    return True


def shingles(text: str, n: int = 5) -> set[tuple]:
    toks = [t.lower() for t in WORD.findall(text)]
    return {tuple(toks[i:i + n]) for i in range(max(0, len(toks) - n + 1))}


def norm_sentence(s: str) -> str:
    return " ".join(t.lower() for t in WORD.findall(s))


def top_counts(items, n: int = 10):
    return Counter(items).most_common(n)
