"""Whole-book prose checks over the accepted scene texts, saved to books/<book>/validation/prose.json."""

from .. import scenefiles
from ..bible import store
from ..bible.positions import parse_position
from . import prose as P, repeats as R
from .text import sentences
from .findings import Finding, HARD
from . import store as findings_store


def prose_findings(project) -> tuple[list[Finding], dict]:
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
    findings = P.repeated_sentences(texts) + P.chapter_openings_copy(chapter_texts) + P.wrap_up_endings(texts) + tics + _event_repeats(project, scenes, names)
    return findings, table


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


def save_prose_findings(project) -> tuple[list[Finding], str]:
    findings, table = prose_findings(project)
    return findings, findings_store.save(project, "prose", findings, {"tics": table})


def hard_lines(findings: list[Finding]) -> list[str]:
    return [f.line() for f in findings if f.severity == HARD]
