"""Layer 7: the prose, scene by scene.

For each scene: build the briefing, write `layers.prose.drafts` drafts with the fast model, run the
mechanical checks on each, keep the best draft as final.md, and write a short summary for later
briefings. A scene whose best draft still has a blocking problem is flagged and left for the
author (the revision loop and the model critic come in milestone 14.7).

Chapter 1 goes first and the run then stops at the voice checkpoint: read it, edit the style guide
and banned.txt, and `approve voice` before the rest of the book is written. If a final.md already
exists for a scene that is not accepted, it is checked and adopted instead of written.

Progress is kept scene by scene (files, state and a commit each), so a stopped run resumes where it
stopped. Drafts already on disk for an unfinished scene are reused; a flagged scene is written again.
"""

import json
import logging
import time

import yaml

from .. import activity, changes, rules, scenefiles, vcs
from ..bible import store
from ..bible.models import Scene
from ..briefing import build_briefing
from ..deps import write_deps
from ..errors import BookforgeError, LayerError
from ..llm import TruncatedReply
from ..prompts import render
from ..qc.extract import extract_observed, record_observed
from ..qc.mechanical import CheckContext, check_scene, load_banned
from ..qc import scene_notes
from ..qc.critic import rubric_line
from ..qc.scene import clear_progress, settle_scene
from ..state import Item, now
from .document import ask_until_valid, prompt_values, word_count
from .runner import StepContext, StepResult

log = logging.getLogger("platform_bookforge.layers")

PREVIOUS_TAIL_WORDS = 300  # how much of the previous scene the recap check compares against


def check_context(project, scene: Scene, scenes: list[Scene], banned_text: str | None = None) -> CheckContext:
    """The context the mechanical checks need for one scene: earlier accepted scenes, the previous tail, names."""
    cfg = project.config
    constants = store.load_constants(project)
    names = {e.id: e.name for e in constants.entities if e.id in set(scene.characters) | {scene.pov}}
    earlier: list[str] = []
    for s in scenes:
        if s.id == scene.id:
            break
        text = scenefiles.read(scenefiles.final_path(project, s.id))
        if text:
            earlier.append(text)
    prev = scenefiles.previous_scene(scenes, scene.id)
    prev_text = scenefiles.best_text(project, prev.id) if prev else None
    if banned_text is None:
        banned_text = scenefiles.read(project.root / cfg.qc.banned_phrases) or ""
    return CheckContext(
        scene_words=tuple(cfg.layers["prose"].words or (1500, 3000)), pov=cfg.book.pov, tense=cfg.book.tense,
        language=cfg.book.language, banned=load_banned(banned_text), phrase_rules=rules.phrase_rules(rules.rules_for(project, scene, ("banned_phrase",))), names=names, pov_id=scene.pov,
        previous_tail=" ".join(prev_text.split()[-PREVIOUS_TAIL_WORDS:]) if prev_text else None,
        earlier_texts=earlier, qc=cfg.qc,
    )


def _item(project, scene_id: str) -> Item:
    return project.state.items.setdefault(scene_id, Item())


def _set_status(project, scene_id: str, status: str, note: str | None = None) -> None:
    item = _item(project, scene_id)
    item.status = status  # type: ignore[assignment]
    item.updated = now()
    item.note = note
    if status == "accepted":
        item.version += 1
    project.save_state()


def _commit(project, scene_id: str, label: str, paths: list) -> None:
    if project.config.git.commit_each_step:
        rel = [scenefiles.rel(project, p) for p in paths if p.exists()] + [str(project.state_path.relative_to(project.root))]
        vcs.commit(project.root, f"{scene_id}: {label}", rel)


def _summarise(ctx: StepContext, scene: Scene, text: str) -> tuple[str, str]:
    """(summary, source). The fast model writes it; if that fails the plan's purpose stands in."""
    project = ctx.project

    def valid(reply: str) -> list[str]:
        n = word_count(reply)
        return [] if 15 <= n <= 160 else [f"the summary is {n} words; it must be 3 to 5 sentences, between 15 and 160 words"]

    try:
        messages = [{"role": "system", "content": render("system", project.root, **prompt_values(project))},
                    {"role": "user", "content": render("scene_summary", project.root, scene_text=text, **prompt_values(project))}]
        reply = ask_until_valid(ctx, f"{scene.id} summary", "writer", messages, valid, {"max_tokens": 700}, strip_preamble=False)
        return reply.strip(), "model"
    except BookforgeError as e:
        log.warning("%s: no model summary (%s); using the plan", scene.id, e)
        return scene.purpose, "plan"


def _write_drafts(ctx: StepContext, scene: Scene, briefing_text: str, drafts: int, words: tuple[int, int]) -> list[str]:
    project = ctx.project
    values = {**prompt_values(project), "scene_id": scene.id, "word_min": str(words[0]), "word_max": str(words[1])}
    messages = [{"role": "system", "content": render("prose_system", project.root, **values)},
                {"role": "user", "content": render("prose", project.root, briefing=briefing_text, **values)}]
    layer_cfg = project.config.layers["prose"]
    ceiling = layer_cfg.max_tokens or int(words[1] * 1.6) + 300
    texts: list[str] = []
    cut_off: list[TruncatedReply] = []
    for i in range(1, drafts + 1):
        path = scenefiles.draft_path(project, scene.id, i)
        existing = scenefiles.read(path)
        if existing is None:
            # `grow=False`: the ceiling is already well above the longest scene asked for. A draft that hits it is far too long (or the
            # model is repeating itself); asking again with more tokens only costs minutes. It is a failed draft, and the other one is used.
            options = {"max_tokens": ceiling, "draft": i - 1, "grow": False}
            if layer_cfg.temperature is not None:
                options["temperature"] = layer_cfg.temperature
            started = time.monotonic()
            try:
                reply = ctx.llm.complete(layer_cfg.model, messages, **options)
            except TruncatedReply as e:
                log.warning("%s draft %d: %s (after %.0fs)", scene.id, i, e, time.monotonic() - started)
                cut_off.append(e)
                continue
            existing = reply.strip()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(existing + "\n", encoding="utf-8")
        texts.append(existing)
    if not texts:
        first = cut_off[0]
        raise TruncatedReply(
            f"every draft was cut off at {ceiling} tokens, more than the {words[1]} words a scene may have "
            + ("(the model is repeating itself: " + f"{first.repeated:.0%} of the text is repeated) " if first.repeating else "")
            + "- shorten the scene's beats, lower layers.prose.words, or raise layers.prose.max_tokens",
            tail=first.tail, chars=first.chars, repeated=first.repeated)
    return texts


def record_extraction(ctx: StepContext, scene: Scene, scenes: list[Scene], text: str, review: dict, paths: list) -> tuple[int, list]:
    """Extract what the accepted text says about the tracked states; file change requests for gaps.

    Returns (number of gaps, change requests filed). Adds the files it wrote to `paths`, fills `review`.
    """
    project, sid = ctx.project, scene.id
    if not project.config.qc.extract_observed:
        return 0, []
    extraction = extract_observed(ctx, scene, scenes, text)
    review["extraction"] = {"error": extraction.error, "observations": len(extraction.observations), "gaps": extraction.gaps}
    if extraction.observations:
        record_observed(project, sid, extraction)
        scenefiles.extracted_path(project, sid).write_text(
            yaml.safe_dump({"scene": sid, "observations": extraction.observations, "gaps": extraction.gaps},
                           sort_keys=False, allow_unicode=True), encoding="utf-8")
        paths += [scenefiles.extracted_path(project, sid), project.root / "bible" / "tracks.yaml"]
    filed = changes.file_gaps(project, scene, scenes, extraction.gaps)
    if filed:
        review["extraction"]["change_requests"] = [c.id for c in filed]
        paths += changes.paths(project, filed)
    return len(extraction.gaps), filed


def _saved_review(project, sid: str) -> dict:
    raw = scenefiles.read(scenefiles.review_path(project, sid))
    try:
        return json.loads(raw) if raw else {}
    except ValueError:
        return {}


def _problems_text(project, scene: Scene, review: dict) -> str:
    """What was wrong with an attempt at this scene (from its review), and what the author said about it, for the writer. "" if nothing."""
    sid = scene.id
    notes = scene_notes.read(project, sid)
    continuity = review.get("continuity") or {}
    lines: list[str] = []
    for f in continuity.get("flags") or []:
        q = f.get("question", "")
        if not q or q in notes["dismissed"]:
            continue
        line = f"- It contradicted this fixed fact: {q}." + (f" (It said: \"{f['evidence']}\")" if f.get("evidence") else "")
        if notes["instructions"].get(q):
            line += f" The author says: {notes['instructions'][q]}"
        lines.append(line)
    # The critic: what it scored too low, what each criterion asks for, and the three lines it quoted with what is wrong with them.
    critic = review.get("critic") or {}
    minimum = project.config.qc.critic_min_score
    low = {c: v for c, v in (critic.get("scores") or {}).items() if isinstance(v, int) and v < minimum}
    if low:
        for c, v in low.items():
            lines.append(f"- The critic scored {c} {v} (minimum {minimum}): {rubric_line(project, c)}")
        for w in critic.get("weakest") or []:
            lines.append(f"- [{w.get('criterion')}] \"{w.get('quote')}\": {w.get('issue')}")
        if "beats_covered" in low:
            lines.append("- Make every one of these beats happen on the page, in order: " + "; ".join(f"{n}. {b}" for n, b in enumerate(scene.beats, 1)))
    flagged_text = {f.get("question") for f in continuity.get("flags") or []}
    for b in review.get("blocking") or review.get("unresolved") or []:
        if any(q and q in b for q in flagged_text) or (low and b.startswith("the critic scored")):
            continue
        lines.append(f"- {b}")
    if not lines:
        return ""
    return "\n\n## Problems found in the previous attempt at this scene (do not repeat them)\n\n" + "\n".join(lines)[:2600]


def write_scene(ctx: StepContext, scene: Scene, scenes: list[Scene], drafts: int, words: tuple[int, int]) -> tuple[bool, list[str]]:
    """Write, check and settle one scene. Returns (accepted, files)."""
    project = ctx.project
    sid = scene.id
    d = scenefiles.scene_dir(project, sid)
    briefing = build_briefing(project, sid)
    deps = scenefiles.deps_path(project, sid)
    write_deps(deps, briefing.deps)
    check_ctx = check_context(project, scene, scenes)
    paths = [deps]
    review: dict = {"budget_tokens": briefing.budget, "briefing_tokens": briefing.tokens, "briefing_trimmed": briefing.trimmed}
    review_file = scenefiles.review_path(project, sid)
    paths.append(review_file)

    adopted = scenefiles.read(scenefiles.final_path(project, sid))
    if adopted is not None:
        # The author's own text: only the mechanical checks apply, and the file is never rewritten.
        text, source, reasons = adopted.strip(), "adopted", []
        report = check_scene(text, check_ctx)
        review.update(source=source, chosen="final", mechanical={"final": report.to_dict()})
        reasons = [i.message for i in report.blocking]
    else:
        flagged_before = _item(project, sid).status == "flagged"
        prior_review = _saved_review(project, sid) if flagged_before else {}
        problems_section = _problems_text(project, scene, prior_review) if flagged_before else ""
        rewrite_ok = project.config.qc.critic_rewrite
        result = None
        # Revise what was written, with what was found, before throwing it away and starting again. Not when the critic said the scene as a
        # whole is the problem (a missing beat, uneven pacing): patching lines cannot fix that, only writing it again can.
        if flagged_before and project.config.qc.revise_flagged and not (rewrite_ok and prior_review.get("rewrite_advised")):
            saved = scenefiles.best_text(project, sid)
            if saved and saved.strip():
                _set_status(project, sid, "drafted")
                activity.set(step="revising the saved text")
                attempt = settle_scene(ctx, scene, scenes, {"saved": saved}, check_ctx, can_rewrite=rewrite_ok)
                if attempt.accepted:
                    result = attempt
                    review["revised_after_flag"] = True
        extra: dict = {}
        if result is None:
            if flagged_before:
                for old in list(d.glob("draft-*.md")) + [scenefiles.revised_path(project, sid)]:
                    old.unlink(missing_ok=True)
                clear_progress(project, sid)
            activity.set(step="writing drafts")
            texts = _write_drafts(ctx, scene, briefing.text() + problems_section, drafts, words)
            _set_status(project, sid, "drafted")
            paths += [scenefiles.draft_path(project, sid, i) for i in range(1, len(texts) + 1)]
            # A scene flagged before already carries the notes of the earlier attempt; otherwise the first attempt may be redone once.
            may_rewrite = rewrite_ok and not flagged_before
            result = settle_scene(ctx, scene, scenes, {f"draft-{i}": t for i, t in enumerate(texts, 1)}, check_ctx, can_rewrite=may_rewrite)
            if may_rewrite and not result.accepted and result.review.get("rewrite_advised"):
                notes = _problems_text(project, scene, result.review)
                extra = {"rewrote_with_critic_notes": True, "first_attempt_critic": result.review.get("critic")}
                for old in list(d.glob("draft-*.md")) + [scenefiles.revised_path(project, sid)]:
                    old.unlink(missing_ok=True)
                clear_progress(project, sid)  # the checks belonged to the drafts that were thrown away
                activity.set(step="writing the scene again with the critic's notes")
                texts = _write_drafts(ctx, scene, briefing.text() + notes, drafts, words)
                paths += [scenefiles.draft_path(project, sid, i) for i in range(1, len(texts) + 1)]
                result = settle_scene(ctx, scene, scenes, {f"draft-{i}": t for i, t in enumerate(texts, 1)}, check_ctx, can_rewrite=False)
        text, source, reasons = result.text, "written", [] if result.accepted else result.reasons
        review.update(source=source, **result.review, **extra)
        report = check_scene(text, check_ctx)

    if reasons:
        review["blocking"] = reasons
        if source == "written" and review.get("revised"):
            scenefiles.revised_path(project, sid).write_text(text.rstrip() + "\n", encoding="utf-8")
            paths.append(scenefiles.revised_path(project, sid))
        review_file.write_text(json.dumps(review, indent=2, ensure_ascii=False), encoding="utf-8")
        clear_progress(project, sid)
        _set_status(project, sid, "flagged", "; ".join(reasons)[:300])
        _commit(project, sid, "drafted, flagged", paths)
        return False, [scenefiles.rel(project, p) for p in paths if p.exists()]

    _set_status(project, sid, "checked")
    final = scenefiles.final_path(project, sid)
    if source == "written":
        final.write_text(text.rstrip() + "\n", encoding="utf-8")  # an adopted file is the author's: left exactly as it is
    activity.set(step="summarising")
    summary, summary_source = _summarise(ctx, scene, text)
    scenefiles.summary_path(project, sid).write_text(summary.rstrip() + "\n", encoding="utf-8")
    review["summary_source"] = summary_source
    paths += [final, scenefiles.summary_path(project, sid)]

    activity.set(step="recording what the scene shows")
    gaps, filed = record_extraction(ctx, scene, scenes, text, review, paths)
    review_file.write_text(json.dumps(review, indent=2, ensure_ascii=False), encoding="utf-8")
    note = f"{report.stats['words']} words, {len(report.warnings)} warning(s)" + (f", {gaps} gap(s) between plan and prose" if gaps else "") + (f" ({len(filed)} change request(s) filed, {sum(c.status == 'pending' for c in filed)} waiting for you)" if filed else "")
    clear_progress(project, sid)
    _set_status(project, sid, "accepted", note)
    _commit(project, sid, "drafted, checked, accepted" if source == "written" else "adopted, checked, accepted", paths)
    return True, [scenefiles.rel(project, p) for p in paths if p.exists()]


def order_for_run(project, scenes: list[Scene], voice_approved: bool, first_chapter: str) -> list[Scene]:
    """The scenes a run goes through, in order. Scenes still to do come first (one that was interrupted, `drafted`, before the
    untouched ones); flagged scenes are retried afterwards, so pausing a run does not send it back to a flagged scene at the start of
    the book. `layers.prose.retry_flagged: inline` keeps plain book order."""
    allowed = [s for s in scenes if voice_approved or s.chapter == first_chapter]
    if project.config.layers["prose"].retry_flagged == "inline":
        return allowed
    status = {s.id: _item(project, s.id).status for s in allowed}
    interrupted = [s for s in allowed if status[s.id] == "drafted"]
    pending = [s for s in allowed if status[s.id] not in ("drafted", "flagged")]
    flagged = [s for s in allowed if status[s.id] == "flagged"]
    return interrupted + pending + flagged


def prose(ctx: StepContext) -> StepResult:
    project = ctx.project
    if ctx.llm is None:
        raise LayerError("no model client available")
    scenes = store.load_scenes(project)
    chapters = store.load_chapters(project)
    if not scenes or not chapters:
        raise LayerError("scenes.yaml is missing or empty; the scenes layer has to be accepted first")
    cfg = project.config.layers["prose"]
    drafts, words = max(1, cfg.drafts or 2), tuple(cfg.words or (1500, 3000))
    first_chapter = chapters[0].id
    voice = project.state.checkpoints["voice"].status
    files: list[str] = []

    if not scenefiles.read(project.root / "style" / "guide.md") and not list((project.root / "style" / "samples").glob("*.md")):
        log.warning("no style guide and no sample passages: the north stars' tone is the only voice guidance")

    done_now = 0
    stale: list[str] = []
    for scene in order_for_run(project, scenes, voice == "approved", first_chapter):
        status = _item(project, scene.id).status
        if status == "accepted":
            continue
        if status == "stale":
            stale.append(scene.id)  # brought up to date by `stale --fix`, not rewritten from scratch
            continue
        activity.set(scene=scene.id, step="starting")
        try:
            accepted, scene_files = write_scene(ctx, scene, scenes, drafts, words)
        except TruncatedReply as e:
            # One reply that is too long for its token limit, even after raising it, must not stop the book: this scene waits for you.
            log.warning("%s: %s", scene.id, e)
            _set_status(project, scene.id, "flagged", f"the writer's reply was cut off: {e}"[:300])
            continue
        files += scene_files
        done_now += accepted
        if accepted:
            activity.add("scenes_done")

    items = project.state.items
    flagged = [s.id for s in scenes if items.get(s.id, Item()).status == "flagged"]
    accepted_n = sum(1 for s in scenes if items.get(s.id, Item()).status == "accepted")
    note = f"{accepted_n}/{len(scenes)} scenes accepted" + (f", {len(flagged)} need you: {', '.join(flagged)}" if flagged else "") + (f", {len(stale)} stale (run `stale --fix`)" if stale else "")
    if voice != "approved":
        return StepResult(files=files, note=note, outcome="partial", checkpoint="voice")
    if flagged:
        return StepResult(files=files, note=note, outcome="flagged")
    return StepResult(files=files, note=note)
