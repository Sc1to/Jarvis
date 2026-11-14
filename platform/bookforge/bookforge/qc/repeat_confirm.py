"""A second opinion on repeat findings: the lexical check finds passages that share words, a model says whether they tell the same event.

The word-overlap check cannot tell a retelling from a deliberate echo or a consequence that shares vocabulary, and a false positive stops
the stage. Each hard repeat finding is put to the critic in one small call. Only a clear 'not the same event' downgrades it (to soft,
with the reason); an unclear or failed answer keeps the finding as it was.
"""

import logging
from dataclasses import replace

from ..validators import HARD, SOFT, Finding
from .support import ask_json

log = logging.getLogger("platform_bookforge.qc")
CONFIRMABLE = ("event_repeated", "chapter_replans_chapter", "scene_retells_event", "chapter_retells_event")
MAX_CALLS = 10
_ANSWERS: dict[tuple, dict] = {}  # the critic's answer per set of passages: a piece check runs again for every correction round and every cached reuse


def _check(data: dict) -> list[str]:
    return [] if isinstance(data.get("same_event"), bool) and isinstance(data.get("reason", ""), str) else ['"same_event" must be true or false and "reason" a sentence']


def confirm_repeats(ctx, findings: list[Finding]) -> list[Finding]:
    """The findings, with each hard repeat the critic judges to be different events turned soft."""
    if ctx is None or ctx.llm is None or not ctx.project.config.qc.confirm_repeats:
        return findings
    out, calls = [], 0
    for f in findings:
        if f.severity != HARD or f.code not in CONFIRMABLE or len(f.evidence) < 2 or calls >= MAX_CALLS:
            out.append(f)
            continue
        calls += 1
        passages = "\n".join(f"- {t}" for t in f.evidence[:4])
        key = (f.code, passages)
        try:
            data = _ANSWERS.get(key) or ask_json(ctx, f"repeat check {f.code}", "critic", "repeat_confirm", _check, max_tokens=300, passages=passages)
            _ANSWERS[key] = data
        except Exception as e:  # no answer is no change: the finding stays as it was
            log.info("repeat confirmation failed (%s); keeping the finding", e)
            out.append(f)
            continue
        if data.get("same_event") is False:
            out.append(replace(f, severity=SOFT, message=f"(a model reads these as different events: {str(data.get('reason', '')).strip()[:160]}) {f.message}"))
        else:
            out.append(f)
    return out
