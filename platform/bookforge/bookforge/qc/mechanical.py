"""Layer 1 of quality control: checks in plain Python, no model.

Banned phrases, phrases repeated across scenes, overused words, sentence rhythm, dialogue
ratio, tense and point-of-view slips, scene length, cut-off endings, assistant chatter,
and recap of the previous scene. Each finding is `block` (the scene cannot be accepted as it
is) or `warn` (reported, and a candidate for the revision loop). Findings carry the character
span they refer to, so a revision can be limited to the flagged passage.

The tense and point-of-view checks are heuristics for English prose. For other languages they
are skipped and the report says so; everything else is language-independent.
"""

import math
import re
import statistics
from collections import Counter
from dataclasses import dataclass, field

from ..config import QC

WORD = re.compile(r"[\w'’-]+", re.UNICODE)
DIALOGUE = re.compile(r'"[^"\n]{1,3000}"|“[^”]{1,3000}”|«[^»]{1,3000}»|„[^“]{1,3000}“')
SENTENCE_END = re.compile(r'(?<=[.!?…])["”’»)]*\s+(?=["“‘(«„]*[A-ZÀ-ÞÄÖÜ0-9])')
FIRST_PERSON = re.compile(r"\b(I|me|my|mine|myself|we|us|our|ours|ourselves)\b")
PRESENT_AUX = {"is", "are", "am", "has", "have", "does", "do", "can", "will"}
PAST_AUX = {"was", "were", "had", "did", "could", "would"}
THOUGHT_VERBS = "thought|wondered|felt|knew|realized|realised|wished|hoped|feared|decided|remembered|understood"
CHATTER_START = re.compile(r"^\W*(sure|certainly|of course|okay|ok|here is|here's|here are|below is)\b", re.IGNORECASE)
CHATTER_END = re.compile(r"(i hope this|let me know|word count|hope you (like|enjoy)|feel free to)", re.IGNORECASE)
FORMATTING = re.compile(r"^(#{1,6}\s|[-*•]\s|\d+\.\s|```|---+\s*$|\*\*scene|scene \d+\s*[:.])", re.IGNORECASE | re.MULTILINE)

STOPWORDS = frozenset("""
a about above after again all also am an and any are as at be because been before being below between both but by
can could did do does doing down during each few for from further had has have having he her here hers herself him
himself his how i if in into is it its itself just me more most my myself no nor not now of off on once only or other
our ours out over own same she should so some such than that the their theirs them themselves then there these they
this those through to too under until up very was we were what when where which while who whom why will with would
you your yours yourself said asked
""".split())

BLOCK, WARN, NOTE = "block", "warn", "note"
FAR_OFF = (0.5, 2.0)  # a scene under half the minimum or over twice the maximum length blocks; merely outside the range warns


def words(text: str) -> list[str]:
    return WORD.findall(text)


def narration(text: str) -> str:
    return DIALOGUE.sub(" ", text)


def sentences(text: str) -> list[str]:
    parts = [p.strip() for p in SENTENCE_END.split(text.replace("\n", " ")) if p.strip()]
    return parts


@dataclass
class Issue:
    code: str
    severity: str  # block | warn | note (a note is recorded, never counted)
    message: str
    excerpt: str = ""
    start: int | None = None  # character span in the checked text, for passage-level revision
    end: int | None = None
    rule: str | None = None  # the rules panel's rule that raised it


@dataclass
class MechanicalReport:
    issues: list[Issue] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)  # checks that did not apply, and why

    @property
    def blocking(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == BLOCK]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == WARN]

    @property
    def score(self) -> int:
        """Lower is better: a blocking issue costs 100, a warning 1. Used to choose between drafts."""
        return 100 * len(self.blocking) + len(self.warnings)

    def to_dict(self) -> dict:
        return {"score": self.score, "stats": self.stats, "skipped": self.skipped,
                "issues": [vars(i) for i in self.issues]}


@dataclass
class CheckContext:
    scene_words: tuple[int, int] = (1500, 3000)
    pov: str = "third-limited"
    tense: str = "past"
    language: str = "English"
    banned: list[str] = field(default_factory=list)  # lines of banned.txt, comments already removed
    phrase_rules: list[tuple[str, str, str]] = field(default_factory=list)  # (rule id, phrase, severity) from workbench/rules.yaml
    names: dict[str, str] = field(default_factory=dict)  # entity id -> full name, for the characters of the scene
    pov_id: str | None = None
    previous_tail: str | None = None  # the end of the previous scene
    earlier_texts: list[str] = field(default_factory=list)  # accepted scenes before this one
    qc: QC = field(default_factory=QC)


def all_banned(ctx: "CheckContext") -> list[str]:
    """Every phrase a revision must avoid: banned.txt and the blocking phrase rules."""
    return list(ctx.banned) + [p for _, p, sev in ctx.phrase_rules if sev == BLOCK]


def load_banned(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]


def _banned_regex(entry: str) -> re.Pattern | None:
    try:
        if entry.startswith("re:"):
            return re.compile(entry[3:], re.IGNORECASE)
        parts = [re.escape(p) for p in entry.split()]
        core = r"\s+".join(parts)
        left = r"\b" if entry[0].isalnum() else ""
        right = r"\b" if entry[-1].isalnum() else ""
        return re.compile(left + core + right, re.IGNORECASE)
    except re.error:
        return None


def _excerpt(text: str, start: int, end: int, pad: int = 40) -> str:
    return " ".join(text[max(0, start - pad): end + pad].split())


def _is_english(language: str) -> bool:
    return language.strip().lower() in ("english", "en", "eng")


def _tokens(text: str) -> list[str]:
    return [w.lower().strip("'’-") for w in words(text)]


def _content(tokens: list[str]) -> int:
    return sum(1 for t in tokens if t not in STOPWORDS)


# ── repeated phrases ────────────────────────────────────────────────────────

def _ngrams(tokens: list[str], n: int) -> list[tuple[str, ...]]:
    return [tuple(tokens[i: i + n]) for i in range(len(tokens) - n + 1)]


def repeated_spans(text: str, earlier: list[str], n: int, min_scenes: int) -> list[tuple[str, int]]:
    """Phrases of at least n words in `text` that occur in at least `min_scenes` earlier scenes, longest first."""
    if not earlier:
        return []
    tokens = _tokens(text)
    counter: Counter = Counter()
    for other in earlier:
        counter.update(set(_ngrams(_tokens(other), n)))
    marked = [False] * len(tokens)
    seen_in: dict[int, int] = {}
    for i, g in enumerate(_ngrams(tokens, n)):
        scenes = counter.get(g, 0)
        if scenes >= min_scenes and _content(list(g)) >= 2:
            for j in range(i, i + n):
                marked[j] = True
                seen_in[j] = max(seen_in.get(j, 0), scenes)
    spans: list[tuple[str, int]] = []
    i = 0
    while i < len(tokens):
        if marked[i]:
            j = i
            while j < len(tokens) and marked[j]:
                j += 1
            spans.append((" ".join(tokens[i:j]), max(seen_in[k] for k in range(i, j))))
            i = j
        else:
            i += 1
    return sorted(spans, key=lambda s: -len(s[0]))


def suggest_phrases(texts: list[str], size: int = 4, min_scenes: int = 4, limit: int = 20) -> list[tuple[str, int]]:
    """Phrases found in many scenes: candidates for banned.txt (for the morning report)."""
    counter: Counter = Counter()
    for t in texts:
        counter.update({g for g in _ngrams(_tokens(t), size) if _content(list(g)) >= 2})
    common = [(" ".join(g), c) for g, c in counter.items() if c >= min_scenes]
    return sorted(common, key=lambda x: (-x[1], x[0]))[:limit]


# ── the checks ──────────────────────────────────────────────────────────────

def check_scene(text: str, ctx: CheckContext) -> MechanicalReport:
    report = MechanicalReport()
    issues = report.issues
    qc = ctx.qc
    ws = words(text)
    n_words = len(ws)
    narr = narration(text)
    sents = sentences(narr)
    lengths = [len(words(s)) for s in sents]
    dialogue_words = n_words - len(words(narr))
    ratio = dialogue_words / n_words if n_words else 0.0
    mean_len = statistics.fmean(lengths) if lengths else 0.0
    cv = statistics.pstdev(lengths) / mean_len if len(lengths) > 1 and mean_len else 0.0
    report.stats = {"words": n_words, "sentences": len(sents), "mean_sentence_words": round(mean_len, 1),
                    "sentence_variation": round(cv, 2), "dialogue_ratio": round(ratio, 3),
                    "paragraphs": len([p for p in text.split("\n\n") if p.strip()])}

    # assistant chatter and formatting
    head, tail = text[:200], text[-250:]
    if CHATTER_START.search(head):
        issues.append(Issue("chatter", BLOCK, "the text starts with a remark to the reader instead of the story", _excerpt(text, 0, 80), 0, 80))
    if CHATTER_END.search(tail):
        issues.append(Issue("chatter", BLOCK, "the text ends with a remark to the reader instead of the story", _excerpt(text, len(text) - 120, len(text)), max(0, len(text) - 250), len(text)))
    for m in FORMATTING.finditer(text):
        issues.append(Issue("formatting", BLOCK, "headings, lists, labels or code fences do not belong in scene prose", _excerpt(text, m.start(), m.end()), m.start(), m.end()))
        break

    # length
    lo, hi = ctx.scene_words
    if n_words < lo * FAR_OFF[0] or n_words > hi * FAR_OFF[1]:
        issues.append(Issue("length", BLOCK, f"{n_words} words is far outside the target of {lo} to {hi}"))
    elif n_words < lo or n_words > hi:
        issues.append(Issue("length", WARN, f"{n_words} words is outside the target of {lo} to {hi}"))

    # cut off
    stripped = text.rstrip()
    if stripped and stripped[-1] not in '.!?…"”’»)*_':
        issues.append(Issue("cut_off", BLOCK, "the text does not end with closing punctuation; it may be cut off", _excerpt(text, len(stripped) - 60, len(stripped)), len(stripped) - 60, len(stripped)))

    # banned phrases
    for entry in ctx.banned:
        rx = _banned_regex(entry)
        if rx is None:
            report.skipped.append(f"banned entry is not usable: {entry}")
            continue
        for m in rx.finditer(text):
            issues.append(Issue("banned_phrase", BLOCK, f"banned phrase: '{m.group(0)}'", _excerpt(text, m.start(), m.end()), m.start(), m.end()))

    # phrase rules from the rules panel (block, warn or note)
    for rule_id, phrase, severity in ctx.phrase_rules:
        rx = _banned_regex(phrase)
        if rx is None:
            report.skipped.append(f"rule {rule_id}: the phrase is not usable")
            continue
        for m in rx.finditer(text):
            issues.append(Issue("rule_phrase", severity, f"rule {rule_id}: '{m.group(0)}'", _excerpt(text, m.start(), m.end()), m.start(), m.end(), rule=rule_id))

    # phrases repeated from earlier scenes, and inside this one
    n = qc.repeat_ngram_size
    for phrase, count in repeated_spans(text, ctx.earlier_texts, n, qc.repeat_ngram_scenes)[:5]:
        issues.append(Issue("repeated_phrase", WARN, f"the phrase '{phrase}' already appears in {count} earlier scenes"))
    own = Counter(g for g in _ngrams(_tokens(text), n) if _content(list(g)) >= 2)
    for g, c in own.most_common(3):
        if c >= 3:
            issues.append(Issue("repeated_phrase", WARN, f"the phrase '{' '.join(g)}' appears {c} times in this scene"))

    # overused words
    name_tokens = {t.lower() for full in ctx.names.values() for t in full.split()}
    counts = Counter(t for t in _tokens(text) if t not in STOPWORDS and len(t) >= 4 and t not in name_tokens)
    for word, c in counts.most_common(3):
        if c >= qc.overused_word_min_count and n_words and 100 * c / n_words >= qc.overused_word_percent:
            issues.append(Issue("overused_word", WARN, f"'{word}' appears {c} times ({100 * c / n_words:.1f}% of the words)"))

    # sentence rhythm
    if len(lengths) >= 8 and cv < qc.sentence_variation_min:
        issues.append(Issue("monotone_rhythm", WARN, f"sentence lengths vary little (variation {cv:.2f}, minimum {qc.sentence_variation_min})"))
    long = [s for s, k in zip(sents, lengths) if k > 70]
    if long:
        issues.append(Issue("long_sentence", WARN, f"{len(long)} sentence(s) run over 70 words", long[0][:120]))
    firsts = [(words(s) or [""])[0].lower() for s in sents]
    run = 1
    for i in range(1, len(firsts)):
        run = run + 1 if firsts[i] == firsts[i - 1] and firsts[i] else 1
        if run >= 4:
            issues.append(Issue("repeated_openings", WARN, f"four sentences in a row start with '{firsts[i]}'"))
            break

    # dialogue ratio
    dlo, dhi = qc.dialogue_ratio
    if n_words >= 200 and not dlo <= ratio <= dhi:
        issues.append(Issue("dialogue_ratio", WARN, f"{ratio:.0%} of the words are dialogue; expected {dlo:.0%} to {dhi:.0%}"))

    # recap of the previous scene
    if ctx.previous_tail:
        head_tokens = _tokens(" ".join(text.split()[:200]))
        tail_grams = set(_ngrams(_tokens(ctx.previous_tail), 6))
        shared = [g for g in _ngrams(head_tokens, 6) if g in tail_grams]
        if len(shared) >= 3:
            issues.append(Issue("recap", WARN, "the opening repeats the end of the previous scene", " ".join(shared[0])))

    # a scene that ends by summing itself up (a note: recorded, never counted)
    from ..validators.prose import wrap_up_endings
    for f in wrap_up_endings([("scene", text)]):
        issues.append(Issue("wrap_up_ending", NOTE, f.message, f.evidence[0] if f.evidence else ""))

    # tense, point of view and head-hopping (English heuristics)
    if _is_english(ctx.language):
        _check_voice(narr, text, ctx, issues)
    else:
        report.skipped.append(f"tense, point-of-view and head-hopping checks are English-only (language: {ctx.language})")
    return report


def _check_voice(narr: str, text: str, ctx: CheckContext, issues: list[Issue]) -> None:
    toks = [w.lower() for w in words(narr)]
    present = sum(1 for t in toks if t in PRESENT_AUX)
    past = sum(1 for t in toks if t in PAST_AUX)
    total = present + past
    if total >= 15:
        if ctx.tense == "past" and present / total > 0.2:
            issues.append(Issue("tense_slip", WARN, f"the narration is meant to be past tense but {present} of {total} auxiliary verbs are present tense"))
        elif ctx.tense == "present" and past / total > 0.35:
            issues.append(Issue("tense_slip", WARN, f"the narration is meant to be present tense but {past} of {total} auxiliary verbs are past tense"))
    first = FIRST_PERSON.findall(narr)
    if ctx.pov.startswith("third") and len(first) > 2:
        issues.append(Issue("pov_slip", WARN, f"third-person narration uses first-person pronouns {len(first)} times outside dialogue"))
    elif ctx.pov == "first" and not first and len(toks) > 100:
        issues.append(Issue("pov_slip", WARN, "first-person narration never uses I, me or my outside dialogue"))
    if ctx.pov.startswith("third") and "omniscient" not in ctx.pov:
        pov_first = ctx.names.get(ctx.pov_id or "", "").split(" ")[0].lower()
        for eid, full in ctx.names.items():
            first_name = full.split(" ")[0]
            if eid == ctx.pov_id or not first_name or first_name.lower() == pov_first:
                continue
            m = re.search(rf"\b{re.escape(first_name)}\b[^.!?\n]{{0,40}}?\b({THOUGHT_VERBS})\b", narr)
            if m:
                issues.append(Issue("head_hop", WARN, f"narration enters {first_name}'s mind, but the point of view is {ctx.names.get(ctx.pov_id or '', 'the viewpoint character')}'s", " ".join(m.group(0).split())))
