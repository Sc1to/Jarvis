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

from .. import scenefiles, vcs
from ..bible import store
from ..bible.models import Scene
from ..briefing import build_briefing
from ..deps import write_deps
from ..errors import BookforgeError, LayerError
from ..prompts import render
from ..qc.mechanical import CheckContext, MechanicalReport, check_scene, load_banned
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
        language=cfg.book.language, banned=load_banned(banned_text), names=names, pov_id=scene.pov,
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
        reply = ask_until_valid(ctx, f"{scene.id} summary", "writer", messages, valid, {"max_tokens": 400}, strip_preamble=False)
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
    texts = []
    for i in range(1, drafts + 1):
        path = scenefiles.draft_path(project, scene.id, i)
        existing = scenefiles.read(path)
        if existing is None:
            options = {"max_tokens": int(words[1] * 1.6) + 300, "draft": i - 1}
            if layer_cfg.temperature is not None:
                options["temperature"] = layer_cfg.temperature
            reply = ctx.llm.complete(layer_cfg.model, messages, **options)
            existing = reply.strip()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(existing + "\n", encoding="utf-8")
        texts.append(existing)
    return texts


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

    adopted = scenefiles.read(scenefiles.final_path(project, sid))
    reports: dict[str, MechanicalReport] = {}
    if adopted is not None:
        text, chosen = adopted.strip(), "final"
        report = check_scene(text, check_ctx)
        reports["final"] = report
        source = "adopted"
    else:
        if _item(project, sid).status == "flagged":
            for old in d.glob("draft-*.md"):
                old.unlink()
        texts = _write_drafts(ctx, scene, briefing.text(), drafts, words)
        _set_status(project, sid, "drafted")
        paths += [scenefiles.draft_path(project, sid, i) for i in range(1, len(texts) + 1)]
        for i, t in enumerate(texts, 1):
            reports[f"draft-{i}"] = check_scene(t, check_ctx)
        chosen = min(reports, key=lambda k: (reports[k].score, k))
        text, report = texts[int(chosen.split("-")[1]) - 1], reports[chosen]
        source = "written"

    review = {"chosen": chosen, "source": source, "budget_tokens": briefing.budget, "briefing_tokens": briefing.tokens,
              "briefing_trimmed": briefing.trimmed, "mechanical": {k: v.to_dict() for k, v in reports.items()}}
    review_file = scenefiles.review_path(project, sid)
    paths.append(review_file)
    if report.blocking:
        review["blocking"] = [i.message for i in report.blocking]
        review_file.write_text(json.dumps(review, indent=2, ensure_ascii=False), encoding="utf-8")
        _set_status(project, sid, "flagged", "; ".join(review["blocking"])[:300])
        _commit(project, sid, "drafted, flagged", paths)
        return False, [scenefiles.rel(project, p) for p in paths if p.exists()]

    _set_status(project, sid, "checked")
    final = scenefiles.final_path(project, sid)
    if source == "written":
        final.write_text(text.rstrip() + "\n", encoding="utf-8")  # an adopted file is the author's: left exactly as it is
    summary, summary_source = _summarise(ctx, scene, text)
    scenefiles.summary_path(project, sid).write_text(summary.rstrip() + "\n", encoding="utf-8")
    review["summary_source"] = summary_source
    review_file.write_text(json.dumps(review, indent=2, ensure_ascii=False), encoding="utf-8")
    paths += [final, scenefiles.summary_path(project, sid)]
    _set_status(project, sid, "accepted", f"{report.stats['words']} words, {len(report.warnings)} warning(s)")
    _commit(project, sid, "drafted, checked, accepted" if source == "written" else "adopted, checked, accepted", paths)
    return True, [scenefiles.rel(project, p) for p in paths if p.exists()]


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

    if voice == "waiting":
        return StepResult(files=[], note="chapter 1 is written; waiting for you to approve the voice checkpoint",
                          outcome="partial", checkpoint="voice")
    if not scenefiles.read(project.root / "style" / "guide.md") and not list((project.root / "style" / "samples").glob("*.md")):
        log.warning("no style guide and no sample passages: the north stars' tone is the only voice guidance")

    done_now = 0
    for scene in scenes:
        if voice != "approved" and scene.chapter != first_chapter:
            break
        if _item(project, scene.id).status == "accepted":
            continue
        accepted, scene_files = write_scene(ctx, scene, scenes, drafts, words)
        files += scene_files
        done_now += accepted

    items = project.state.items
    flagged = [s.id for s in scenes if items.get(s.id, Item()).status == "flagged"]
    accepted_n = sum(1 for s in scenes if items.get(s.id, Item()).status == "accepted")
    note = f"{accepted_n}/{len(scenes)} scenes accepted" + (f", {len(flagged)} need you: {', '.join(flagged)}" if flagged else "")
    if voice != "approved":
        return StepResult(files=files, note=note, outcome="partial", checkpoint="voice")
    if flagged:
        return StepResult(files=files, note=note, outcome="flagged")
    return StepResult(files=files, note=note)
