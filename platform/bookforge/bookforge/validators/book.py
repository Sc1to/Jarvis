"""Whole-book prose checks over the accepted scene texts, saved to books/<book>/validation/prose.json."""

from .. import scenefiles
from ..bible import store
from ..bible.positions import parse_position
from . import prose as P, repeats as R
from .text import sentences
from .findings import Finding, HARD, soft
from . import accepted, store as findings_store


def prose_findings(project, ctx=None) -> tuple[list[Finding], dict]:
    scenes = store.load_scenes(project) if store.scenes_path(project).exists() else []
    texts: list[tuple[str, str]] = []
    for s in scenes:
        t = scenefiles.read(scenefiles.final_path(project, s.id))
        if t and t.strip():
            texts.append((s.id, t))
    chapters: dict[str, list[str]] = {}
    for sid, t in texts:
        chapters.setdefault(parse_position(sid).chapter_ref, []).append(t)
    chapter_texts = [(cid, "\n\n".join(parts)) for cid, parts in chapters.items()]
    names = set()
    try:
        for e in store.load_constants(project).entities:
            names |= {w.lower() for w in e.name.split()} | {e.id}
    except Exception:  # a missing or unreadable cast must not hide the prose findings
        pass
    tics, table = P.tic_report(texts, names)
    from ..qc.repeat_confirm import confirm_repeats
    findings = accepted.apply(project, confirm_repeats(ctx, P.repeated_sentences(texts) + P.chapter_openings_copy(chapter_texts) + P.wrap_up_endings(texts) + tics + _event_repeats(project, scenes, names) + _events_shown(project, scenes, texts)), "prose")
    return findings, table


def _events_shown(project, scenes, texts: list[tuple[str, str]]) -> list[Finding]:
    """Soft: a written scene should show the events its plan lists (a third of an event's words, at least, in a scene of 300+ words)."""
    from ..bible.store import active_ledger
    from .ledger import _stems_wo_names
    ledger = active_ledger(project)
    if ledger is None:
        return []
    event_text = {e.id: e.text for e in ledger.events}
    written = dict(texts)
    out = []
    for s in scenes:
        t = written.get(s.id)
        if not t or len(t.split()) < 300:
            continue
        unit = _stems_wo_names(t)
        for ev in s.events:
            need = _stems_wo_names(event_text.get(ev, ""))
            if len(need) >= 3 and len(need & unit) / len(need) < 0.34:
                out.append(soft("prose", "prose_misses_event", f"{s.id} lists {ev} ('{event_text[ev][:80]}') but the written scene hardly mentions it: check that the scene shows it", [s.id, ev]))
    return out


def _event_repeats(project, scenes, names: set[str]) -> list[Finding]:
    """The same event told again in new words: the semantic repeat check on what the written scenes SAY (their summaries), across chapters.
    Copied sentences are caught above; this catches the retelling that shares no sentence."""
    by_chapter: dict[str, list[str]] = {}
    units = []
    for s in scenes:
        summary = scenefiles.read(scenefiles.summary_path(project, s.id))
        if not summary or not summary.strip():
            continue
        by_chapter.setdefault(s.chapter, []).append(summary.strip())
        units.append(dict(id=s.id, chapter=s.chapter, beats=sentences(summary)))
    chapters = [dict(id=c, summary=" ".join(parts)) for c, parts in by_chapter.items()]
    return R.repeated_events(chapters, units, names, None, stage="prose") if len(chapters) > 1 else []


def save_prose_findings(project, ctx=None) -> tuple[list[Finding], str]:
    findings, table = prose_findings(project, ctx)
    return findings, findings_store.save(project, "prose", findings, {"tics": table})


def hard_lines(findings: list[Finding]) -> list[str]:
    return [f.line() for f in findings if f.severity == HARD]
