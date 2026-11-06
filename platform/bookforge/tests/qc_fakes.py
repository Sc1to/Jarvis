"""Scripted replies for the quality-control calls. Each builds its answer from the prompt it is given,
so quotes are real quotes from the scene and question ids match."""

import json
import re

CONTINUITY = "against facts the author has fixed"
CRITIC = "Review the scene below as a demanding editor"
JUDGE = "Two drafts of the same scene follow"
CONFIRM = "A reader flagged a possible contradiction"
REVISE = "Revise one passage of a scene"
INSERT = "A scene has to show a change on the page"
EXTRACT = "Record what the scene below actually says"
PLAN_REVIEW = "Review the proposed"


def between(text: str, tag: str) -> str:
    m = re.search(rf"<{tag}>\n?(.*?)\n?</{tag}>", text, re.DOTALL)
    return m.group(1) if m else ""


def user(messages) -> str:
    return next(m["content"] for m in messages if m["role"] == "user")


def continuity(overrides=None):
    """Answers every question 'silent' / 'shown', unless a substring of the question text is in `overrides` mapped to
    (answer, confidence, evidence). `answer` is "yes" (contradicts / shown) or "no" (silent / not_shown), or a relation itself
    ("agrees", "silent", "contradicts", "shown", "not_shown")."""
    overrides = overrides or {}

    def relation(kind, answer):
        if answer in ("contradicts", "agrees", "silent", "shown", "not_shown"):
            return answer
        return ("shown" if answer == "yes" else "not_shown") if kind == "shown" else ("contradicts" if answer == "yes" else "silent")

    def reply(messages):
        out = []
        for qid, kind, text in re.findall(r"^(q\d+) \[(\w+)\] (.+)$", user(messages), re.MULTILINE):
            answer, conf, evidence = ("yes", 0.95, "") if kind == "shown" else ("no", 0.95, "")
            for needle, value in overrides.items():
                if needle in text:
                    answer, conf, evidence = value
            out.append({"id": qid, "relation": relation(kind, answer), "confidence": conf, "evidence": evidence})
        return json.dumps({"answers": out})

    return reply


def critic(scores=None, issue="the line is flat"):
    """A critique with real quotes (the first words of three paragraphs). `scores` may be a dict or a list of dicts (one per call)."""
    calls = {"n": 0}
    base = {"stakes": 4, "voice": 4, "show_dont_tell": 4, "pacing": 4, "dialogue": 4, "beats_covered": 4}

    def reply(messages):
        text = between(user(messages), "scene")
        paras = [p for p in re.split(r"\n\s*\n", text) if len(p.split()) >= 8]
        quotes = [" ".join(p.split()[:8]) for p in paras[:3]]
        while len(quotes) < 3:
            quotes.append(quotes[-1] if quotes else "nothing quoted here at all")
        chosen = scores[min(calls["n"], len(scores) - 1)] if isinstance(scores, list) else scores
        calls["n"] += 1
        s = {**base, **(chosen or {})}
        low = sorted(s, key=lambda k: s[k])[:3]
        return json.dumps({"scores": s, "weakest": [{"criterion": c, "quote": q, "issue": issue} for c, q in zip(low, quotes)]})

    return reply


def judge(prefer: str):
    """Prefers the draft that contains `prefer`."""

    def reply(messages):
        a, b = between(user(messages), "draft_a"), between(user(messages), "draft_b")
        return json.dumps({"winner": "A" if prefer in a and prefer not in b else "B", "reason": "r"})

    return reply


def reviser(replacements, log=None):
    """Applies `replacements` {old: new} to the passage it is given."""

    def reply(messages):
        passage = between(user(messages), "passage")
        if log is not None:
            log.append({"passage": passage, "prompt": user(messages)})
        for old, new in replacements.items():
            passage = passage.replace(old, new)
        return passage

    return reply


def extractor(gap=None):
    """Observes every listed track as matching the plan, with the first words of the scene's second paragraph as evidence.
    `gap` is a track id that is reported as differing."""

    def reply(messages):
        text = between(user(messages), "scene")
        paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
        evidence = " ".join(paras[min(1, len(paras) - 1)].split()[:8])
        out = []
        for tid in re.findall(r"^- ([a-z0-9-]+) \(", user(messages), re.MULTILINE):
            out.append({"track": tid, "observed": "as planned" if tid != gap else "something else", "matches_plan": tid != gap, "evidence": evidence})
        return json.dumps({"observations": out})

    return reply


def plan_review(problems=None):
    """`problems` maps a substring of the 'what' to a list of (item, issue); anything else is fine."""
    problems = problems or {}

    def reply(messages):
        what = re.search(r"Review the proposed (.+?) as a demanding editor", user(messages)).group(1)
        for needle, items in problems.items():
            if needle in what:
                return json.dumps({"ok": False, "problems": [{"item": i, "issue": t} for i, t in items]})
        return json.dumps({"ok": True, "problems": []})

    return reply


def inserter(after=1, words=60, log=None):
    """Writes a passage of `words` words and says it goes after paragraph `after`."""

    def reply(messages):
        if log is not None:
            log.append(user(messages))
        passage = " ".join(["She felt the cut open on her shoulder, and the world narrowed to that one bright line."] * ((words // 17) + 1))
        return json.dumps({"after": after, "passage": " ".join(passage.split()[:words])})

    return reply
