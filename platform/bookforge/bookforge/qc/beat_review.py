"""The beat-quality gate: before any prose, one critic call per chapter reads the scenes' beats.

What it looks for (prompts/beat_review.md): a purpose and something new, concrete beats (the actual clue, not "a clue"), conclusions that follow from what is
established, no repeat of earlier scenes, enough material for the length. A scene marked critical has its beats rewritten once in a narrow call, kept only
if the deterministic checks (validators/beats.py) still pass and the rewrite stays about as long; otherwise, and for warnings, the review becomes a soft finding.
It never stops a run. One call per chapter, plus one per critical scene, and none when `qc.beat_review` is off.
"""
import json
import logging

from ..bible.lookup import state_at
from ..validators import beats as beat_checks
from ..validators.findings import soft
from .support import ask_json

log = logging.getLogger("platform_bookforge.qc")


def _scene_text(sc) -> str:
    lines = [f"{sc.id} (purpose: {sc.purpose})"]
    if str(sc.situation).strip():
        lines.append(f"  situation: {sc.situation}")
    lines += [f"  {i}. {b}" for i, b in enumerate(sc.beats, 1)]
    lines.append(f"  end state: {sc.end_state}")
    if str(sc.learns).strip():
        lines.append(f"  new by the end: {sc.learns}")
    return "\n".join(lines)


def _check_review(ids: list[str]):
    def check(data: dict) -> list[str]:
        items = data.get("scenes")
        if not isinstance(items, list):
            return ['the reply must be {"scenes": [{"id": ..., "verdict": "ok|warning|critical", "issue": ..., "fix": ...}]}']
        seen = {str(i.get("id")) for i in items if isinstance(i, dict)}
        out = [f"every scene must be listed; missing: {', '.join(x for x in ids if x not in seen)}"] if set(ids) - seen else []
        if any(isinstance(i, dict) and i.get("verdict") not in ("ok", "warning", "critical") for i in items):
            out.append('"verdict" must be ok, warning or critical')
        return out
    return check


def _check_fix(old_words: int):
    def check(data: dict) -> list[str]:
        b = data.get("beats")
        if not isinstance(b, list) or not b or not all(isinstance(x, str) and x.strip() for x in b) or len(b) > 10:
            return ['"beats" must be a list of 1 to 10 non-empty strings']
        if not isinstance(data.get("purpose"), str) or not data["purpose"].strip():
            return ['"purpose" must be a sentence']
        n = len((data["purpose"] + " " + " ".join(b)).split())
        return [] if 0.5 * old_words <= n <= 2.5 * old_words + 20 else [f"the rewrite has {n} words; keep it near the original {old_words}"]
    return check


def review_chapters(ctx, chapters: list, scenes: list, tracks: list, word_range) -> tuple[list, list[str]]:
    """(findings, notes). Mutates the scenes it rewrites. `word_range(scene) -> (lo, hi)`."""
    project = ctx.project
    findings: list = []
    notes: list[str] = []
    if ctx is None or ctx.llm is None or not project.config.qc.beat_review:
        return findings, notes
    role = project.config.layers["scenes"].model
    by_chapter: dict[str, list] = {}
    for s in scenes:
        by_chapter.setdefault(s.chapter, []).append(s)
    for idx, ch in enumerate(chapters):
        group = by_chapter.get(ch.id, [])
        if not group:
            continue
        ids = [s.id for s in group]
        entities = {e for s in group for e in list(s.characters) + [s.pov, s.setting]}
        state = "\n".join(f"- {s.entity} ({s.kind}){'' if s.status == 'established' else ' [' + s.status + ', NOT established]'}: {s.value}"
                          for s in state_at(tracks, group[0].id, entities)) or "none tracked"
        so_far = "\n".join(f"- {c.id} {c.title}: {c.end_state}" for c in chapters[max(0, idx - 4):idx] if c.end_state) or "nothing before this chapter"
        words = f"{min(word_range(s)[0] for s in group)} to {max(word_range(s)[1] for s in group)}"
        try:
            data = ask_json(ctx, f"review beats {ch.id}", role, "beat_review", _check_review(ids), max_tokens=1500,
                            chapter=f"{ch.id} {ch.title}: {ch.purpose} {ch.summary}", state=state, so_far=so_far,
                            scenes="\n\n".join(_scene_text(s) for s in group), words=words)
        except Exception as e:  # no review is no finding: the gate never stops a run
            log.info("beat review of %s skipped (%s)", ch.id, e)
            continue
        by_id = {s.id: s for s in group}
        for item in data.get("scenes", []):
            if not isinstance(item, dict) or item.get("verdict") in (None, "ok") or str(item.get("id")) not in by_id:
                continue
            sc, issue, fix = by_id[str(item["id"])], str(item.get("issue", "")).strip(), str(item.get("fix", "")).strip()
            if item["verdict"] == "critical" and _rewrite(ctx, sc, issue, fix, notes):
                continue
            findings.append(soft("scenes", "beat_review", f"{sc.id}: {issue or 'the beats leave story logic to the writer'}" + (f" Suggested: {fix}" if fix else ""),
                                 [sc.id], [item["verdict"]]))
    return findings, notes


def _rewrite(ctx, sc, issue: str, fix: str, notes: list[str]) -> bool:
    """One narrow rewrite of a critical scene's beats, kept only if the vagueness check passes."""
    old = (sc.purpose, sc.situation, list(sc.beats), sc.learns)
    old_words = len((sc.purpose + " " + " ".join(sc.beats)).split())
    try:
        data = ask_json(ctx, f"fix beats {sc.id}", ctx.project.config.layers["scenes"].model, "beat_fix", _check_fix(old_words), max_tokens=1200,
                        purpose=sc.purpose, situation=sc.situation or "(not given)", beats="\n".join(f"- {b}" for b in sc.beats), learns=sc.learns or "(not given)",
                        issue=issue or "the beats leave the writer to invent story logic", fix=fix or "make the vague beats concrete")
    except Exception as e:
        log.info("beats of %s not fixed (%s)", sc.id, e)
        return False
    sc.purpose, sc.beats = data["purpose"].strip(), [b.strip() for b in data["beats"]]
    if isinstance(data.get("situation"), str) and data["situation"].strip():
        sc.situation = data["situation"].strip()
    if isinstance(data.get("learns"), str) and data["learns"].strip():
        sc.learns = data["learns"].strip()
    if beat_checks.vague_beats([sc.model_dump()]):
        sc.purpose, sc.situation, sc.beats, sc.learns = old[0], old[1], old[2], old[3]
        log.info("beats of %s not fixed (the rewrite is still vague)", sc.id)
        return False
    notes.append(f"{sc.id}: its beats left story logic to the writer ({issue[:120]}); they were made concrete before any prose")
    return True
