"""Passage-level revision: fix what was flagged and nothing else.

Never a whole scene. Each flag points at a place in the text (a character span from the mechanical
checks, or a quotation from the continuity check or the critic). The paragraph around it goes to the
fast model together with the problems, and only that paragraph is replaced. Several flags in one
paragraph are fixed in one call. Short chatter and formatting lines are simply deleted. A flag that
cannot be located, or whose problem is not a passage problem (a scene that is too short, a missing
must_show change), is returned as unfixed for the author.
"""

import json
import re
from dataclasses import dataclass, field

from ..ask import ask_until_valid, word_count
from ..prompts import render
from ..research.step import parse_json_object
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
    fact: str = ""  # the fixed fact (or change to show) a continuity flag is about
    instruction: str = ""  # what the author told the writer to do about this finding


@dataclass
class Revision:
    text: str
    applied: list[dict] = field(default_factory=list)
    unfixed: list[Flag] = field(default_factory=list)


def issue_text(flag: Flag) -> str:
    """The problem as the writer sees it: specific, with the exact words, the fact and what to do about it."""
    if flag.source == "continuity" and flag.code == "contradiction" and flag.fact:
        what = (f"- The passage says \"{flag.quote}\", which contradicts this fixed fact: {flag.fact}. Rewrite the passage so it agrees with "
                "the fact. Keep what happens in it and what it is for; change only what is needed to remove the clash."
                if flag.quote else f"- The passage contradicts this fixed fact: {flag.fact}. Change only what is needed to remove the clash.")
    else:
        what = f"- {flag.message}"
    if flag.instruction:
        what += f"\n  The author says: {flag.instruction}"
    return what


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
    obligations = [f for f in flags if f.code == "obligation"]  # a change that must happen on the page: a passage is inserted
    flags = [f for f in flags if f.code != "obligation"]
    groups: dict[int, list[Flag]] = {}
    for f in flags:
        idx = locate(text, spans, f)
        if idx is None:
            result.unfixed.append(f)
        else:
            groups.setdefault(idx, []).append(f)
    if not groups:
        if obligations:
            _insert_passages(ctx, result, obligations, label)
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
        issues = "\n".join(issue_text(f) for f in group)

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
    if obligations:
        _insert_passages(ctx, result, obligations, label)
    return result


INSERT_WORDS = (25, 250)


def _insert_passages(ctx, result: Revision, obligations: list[Flag], label: str) -> None:
    """For each change that must be shown: have the writer write a short passage and place it. A failure leaves the flag unfixed."""
    project = ctx.project
    cfg = project.config
    for flag in obligations:
        text = result.text
        spans = paragraphs(text)
        if not spans:
            result.unfixed.append(flag)
            continue
        outline = "\n".join(f"{i}. {text[s:e].strip()[:110]}" for i, (s, e) in enumerate(spans, 1))

        def valid(reply: str, count=len(spans)) -> list[str]:
            data = parse_json_object(reply)
            if data is None:
                return ["the reply must be a single JSON object with 'after' and 'passage'"]
            problems = []
            after = data.get("after")
            if isinstance(after, bool) or not isinstance(after, int) or not 1 <= after <= count:
                problems.append(f"'after' must be a paragraph number from 1 to {count}")
            passage = data.get("passage")
            if not isinstance(passage, str) or not passage.strip():
                return problems + ["'passage' must be the passage as plain prose"]
            n = word_count(passage)
            if not INSERT_WORDS[0] <= n <= INSERT_WORDS[1]:
                problems.append(f"the passage has {n} words; write {INSERT_WORDS[0]} to {INSERT_WORDS[1]}")
            if FORMATTING.search(passage):
                problems.append("the passage must be plain prose, with no headings, lists or labels")
            return problems

        msgs = [{"role": "system", "content": render("prose_system", project.root, language=cfg.book.language)},
                {"role": "user", "content": render("insert", project.root, change=flag.fact or flag.message, outline=outline,
                                                   pov=cfg.book.pov, tense=cfg.book.tense, count=str(len(spans)))
                 + (f"\n\nThe author says: {flag.instruction}" if flag.instruction else "")}]
        try:
            reply = ask_until_valid(ctx, f"{label} insert a passage", "writer", msgs, valid, {"max_tokens": 500}, strip_preamble=False)
        except Exception as e:  # the writer could not produce one: the flag stays for the author
            result.unfixed.append(flag)
            result.applied.append({"mode": "insert-failed", "flags": [flag.code], "error": str(e)[:200]})
            continue
        data = parse_json_object(reply) or {}
        after, passage = int(data["after"]), str(data["passage"]).strip()
        end = spans[after - 1][1]
        result.text = text[:end] + "\n\n" + passage + text[end:]
        result.applied.append({"paragraph": after, "mode": "insert", "flags": [flag.code], "after": passage[:200]})
