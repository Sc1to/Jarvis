"""Passage-level revision: fix what was flagged and nothing else.

Never a whole scene. Each flag points at a place in the text (a character span from the mechanical
checks, or a quotation from the continuity check or the critic). The paragraph around it goes to the
fast model together with the problems, and only that paragraph is replaced. Several flags in one
paragraph are fixed in one call. Short chatter and formatting lines are simply deleted. A flag that
cannot be located, or whose problem is not a passage problem (a scene that is too short, a missing
must_show change), is returned as unfixed for the author.
"""

import re
from dataclasses import dataclass, field

from ..ask import ask_until_valid, word_count
from ..prompts import render
from .mechanical import FORMATTING, _banned_regex
from .support import quote_in_page

DELETE_CODES = {"chatter", "formatting"}
DELETE_MAX_CHARS = 300
GROWTH = (0.4, 2.5)  # a revised paragraph may be this much shorter or longer than the original
CONTEXT_CHARS = 400


@dataclass
class Flag:
    source: str  # mechanical | continuity | critic
    code: str
    message: str
    quote: str = ""
    start: int | None = None
    end: int | None = None
    criterion: str = ""


@dataclass
class Revision:
    text: str
    applied: list[dict] = field(default_factory=list)
    unfixed: list[Flag] = field(default_factory=list)


def paragraphs(text: str) -> list[tuple[int, int]]:
    """(start, end) of each paragraph: runs of text between blank lines."""
    return [(m.start(), m.end()) for m in re.finditer(r"\S[\s\S]*?(?=\n[ \t]*\n|\Z)", text)]


def _find_quote(text: str, quote: str) -> int | None:
    i = text.find(quote)
    if i >= 0:
        return i
    words = quote.split()
    if not words:
        return None
    m = re.search(r"\s+".join(re.escape(w) for w in words), text)
    return m.start() if m else None


def locate(text: str, spans: list[tuple[int, int]], flag: Flag) -> int | None:
    """Index of the paragraph a flag points at, or None."""
    pos = flag.start
    if pos is None and flag.quote:
        pos = _find_quote(text, flag.quote)
    if pos is None:
        return None
    pos = min(pos, max(0, len(text) - 1))
    for i, (s, e) in enumerate(spans):
        if s <= pos < e or pos < s:
            return i
    return len(spans) - 1 if spans else None


def revise_text(ctx, text: str, flags: list[Flag], banned: list[str], label: str) -> Revision:
    project = ctx.project
    spans = paragraphs(text)
    result = Revision(text)
    groups: dict[int, list[Flag]] = {}
    for f in flags:
        idx = locate(text, spans, f)
        if idx is None:
            result.unfixed.append(f)
        else:
            groups.setdefault(idx, []).append(f)
    if not groups:
        return result

    paras = [text[s:e] for s, e in spans]
    seps = [text[spans[i][1]: spans[i + 1][0]] for i in range(len(spans) - 1)]
    cfg = project.config
    for idx in sorted(groups, reverse=True):  # last first: indexes stay valid
        old = paras[idx]
        group = groups[idx]
        if all(f.code in DELETE_CODES for f in group) and len(old) <= DELETE_MAX_CHARS:
            paras[idx] = None  # type: ignore[call-overload]
            result.applied.append({"paragraph": idx, "mode": "delete", "flags": [f.code for f in group], "before": old[:200]})
            continue
        issues = "\n".join(f"- {f.message}" for f in group)

        def valid(reply: str, old=old) -> list[str]:
            problems = []
            n, n_old = word_count(reply), max(1, word_count(old))
            if n == 0:
                return ["the revised passage is empty"]
            if n < GROWTH[0] * n_old or n > GROWTH[1] * n_old + 20:
                problems.append(f"the revised passage has {n} words; keep it close to the original {n_old}")
            for entry in banned:
                rx = _banned_regex(entry)
                if rx and rx.search(reply):
                    problems.append(f"the revised passage still contains a banned phrase: '{rx.search(reply).group(0)}'")
            if FORMATTING.search(reply):
                problems.append("the revised passage must be plain prose, with no headings, lists or labels")
            return problems

        before = paras[idx - 1][-CONTEXT_CHARS:] if idx > 0 and paras[idx - 1] else "(start of the scene)"
        after = (paras[idx + 1] or "")[:CONTEXT_CHARS] if idx + 1 < len(paras) else "(end of the scene)"
        msgs = [{"role": "system", "content": render("prose_system", project.root, language=cfg.book.language)},
                {"role": "user", "content": render("revise", project.root, issues=issues, before=before or "(start of the scene)",
                                                   passage=old, after=after or "(end of the scene)", pov=cfg.book.pov, tense=cfg.book.tense)}]
        new = ask_until_valid(ctx, f"{label} revise paragraph {idx + 1}", "writer", msgs, valid,
                              {"max_tokens": int(word_count(old) * 2.2) + 200}, strip_preamble=False).strip()
        paras[idx] = new
        result.applied.append({"paragraph": idx, "mode": "rewrite", "flags": [f.code for f in group], "before": old[:200], "after": new[:200]})

    out = []
    for i, p in enumerate(paras):
        if p is None:
            continue
        out.append(p)
        if i < len(seps):
            out.append(seps[i])
    result.text = "".join(out).strip() + "\n" if text.endswith("\n") else "".join(out).strip()
    result.applied.reverse()
    return result
