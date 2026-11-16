"""Hard whole-book prose findings the tool resolves itself, with the passage reviser it already has.

Two checks over the accepted prose stop a run and nothing resolved them before: a chapter that opens with words copied from the end of the chapter
before (`chapter_opens_with_previous_ending`), and a scene made largely of sentences already written in earlier scenes (`sentences_repeated`).
For each, the one scene it points to goes to `revise_text` with the quoted words and an instruction (a paragraph, never the whole scene), and the
result is kept only if

1. the revision was applied to every flag (a passage that cannot be located leaves the scene as it was),
2. the finding is gone when the check is run again on the new text, and
3. the scene's own checks pass on the new text (banned phrases, continuity).

Anything else leaves the saved text untouched and the finding open. Text you wrote or adopted yourself is never touched. A fixed scene gets a new
summary and extraction like any patched scene, and each fix is a "Fixed automatically" line in the Inbox (bookforge/healing.py).
"""

import logging

from . import scenefiles
from .bible import store
from .bible.positions import parse_position
from .errors import LayerError
from .qc.mechanical import all_banned
from .qc.revise import Flag, revise_text
from .validators import prose as prose_checks
from .validators.findings import HARD, Finding

log = logging.getLogger("platform_bookforge.prose_repair")

OPENING, REPEATED = "chapter_opens_with_previous_ending", "sentences_repeated"
HANDLED = (OPENING, REPEATED)


def _texts(project, scenes) -> list[tuple[str, str]]:
    out = []
    for s in scenes:
        t = scenefiles.read(scenefiles.final_path(project, s.id))
        if t and t.strip():
            out.append((s.id, t))
    return out


def _chapter_texts(texts: list[tuple[str, str]]) -> list[tuple[str, str]]:
    chapters: dict[str, list[str]] = {}
    for sid, t in texts:
        chapters.setdefault(parse_position(sid).chapter_ref, []).append(t)
    return [(cid, "\n\n".join(parts)) for cid, parts in chapters.items()]


def still_holds(f: Finding, texts: list[tuple[str, str]]) -> bool:
    """Does the same hard finding come up again on these texts?"""
    if f.code == OPENING:
        return any(x.code == OPENING and x.items[-1:] == f.items[-1:] for x in prose_checks.chapter_openings_copy(_chapter_texts(texts)))
    return any(x.code == REPEATED and x.severity == HARD and x.items == f.items for x in prose_checks.repeated_sentences(texts))


def _flags(f: Finding, texts: list[tuple[str, str]]) -> list[Flag]:
    if f.code == OPENING:
        return [Flag("prose", "copied_opening", "This passage opens the chapter with words copied from the end of the chapter before. Begin with something new "
                     "(a different first image, action or line) and keep what happens in the scene.", start=0)]
    return [Flag("prose", "repeated_sentence", "This sentence was already written in an earlier scene. Say it in new words, or cut it if the scene "
                 "does not need it; keep what the scene tells.", quote=q) for q in prose_checks.duplicate_sentences(texts).get(f.items[0], (0, []))[1]]  # every repeated sentence, not only the few the finding quotes


def fix(ctx, findings: list[Finding]) -> list[str]:
    """Resolve what can be resolved; returns one line per scene that was fixed."""
    project = ctx.project
    if not project.config.qc.fix_prose_findings or ctx.llm is None:
        return []
    from .layers.prose import check_context, _commit, _summarise, record_extraction  # noqa: F401  (the same machinery the stale patch uses)
    from . import stale

    scenes = store.load_scenes(project)
    first: dict[str, str] = {}
    for s in scenes:
        first.setdefault(s.chapter, s.id)
    todo: dict[str, list[Finding]] = {}
    for f in findings:
        if f.severity != HARD or f.accepted or f.code not in HANDLED or not f.items:
            continue
        sid = first.get(f.items[-1]) if f.code == OPENING else f.items[0]
        if sid:
            todo.setdefault(sid, []).append(f)
    notes: list[str] = []
    for scene in scenes:  # book order: a change to one scene is seen by the checks of the next
        fs = todo.get(scene.id)
        text = scenefiles.read(scenefiles.final_path(project, scene.id)) if fs else None
        if not fs or not text:
            continue
        review = stale._read_review(project, scene.id)
        if review.get("source") == "adopted":
            continue  # your own text is never rewritten
        texts = _texts(project, scenes)
        flags = [fl for f in fs for fl in _flags(f, texts)]
        mech = check_context(project, scene, scenes)
        try:
            revision = revise_text(ctx, text, flags, all_banned(mech), f"{scene.id} prose check")
        except LayerError as e:
            log.info("%s: prose check not fixed (%s)", scene.id, e)
            continue
        if not revision.applied or revision.unfixed:
            log.info("%s: prose check not fixed: applied=%s unfixed=%s", scene.id, len(revision.applied), [f.quote[:30] for f in revision.unfixed])
            continue
        new_texts = [(sid, revision.text if sid == scene.id else t) for sid, t in texts]
        if any(still_holds(f, new_texts) for f in fs):
            log.info("%s: prose check not fixed: the finding still holds on the new text", scene.id)
            continue
        after, left, err = stale._problems(ctx, scene, scenes, revision.text, None, mech)
        if after or left or err:
            log.info("%s: prose check not fixed: the new text fails its own checks (%s)", scene.id, [f.message for f in after][:2] or left[:2] or err)
            continue
        what = "its opening copied the end of the chapter before" if any(f.code == OPENING for f in fs) else "it repeated sentences already written"
        stale._finish_patch(ctx, scene, scenes, revision.text, review, list(revision.applied), "a whole-book prose check", stale.SceneStale(scene.id, []))
        notes.append(f"{scene.id}: {what}; the passage was rewritten and the check passes")
    return notes
