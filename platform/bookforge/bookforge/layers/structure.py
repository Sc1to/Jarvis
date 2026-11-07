"""Layers 4-6: acts, chapters (with the cast and state tracks) and scenes (with the timeline).

Layer 4 is one document. Layers 5 and 6 fan out: one model call per act (chapters) and per
chapter (scenes). Each reply is checked, corrected, and cached in books/<book>/work/<layer>/
so a stopped run resumes where it left off; when every piece is in, the pieces are assembled
into the final files and the work folder is removed. Judging quality is the critic's job
(milestone 14.7) and the author's, at the structure checkpoint.
"""

import logging
import shutil
from pathlib import Path
from typing import Callable

from ..bible import store
from ..bible.models import Act, Chapter, Constants, Track
from ..bible.positions import parse_position
from ..bible.store import dump_yaml, to_plain
from .. import review_notes, steering
from ..bible.validate import (
    add_entities, merge_constants, parse_acts, parse_cast, parse_chapters, parse_scenes, validate_bible,
)
from ..constants import REDO_NOTE
from ..errors import LayerError
from ..prompts import render
from ..qc.plan_review import review_plan
from ..research.notes import stores_for
from ..research.step import run_research
from .document import DocumentSpec, ask_until_valid, generate_document, prompt_values, research_layer
from .runner import StepContext, StepResult

log = logging.getLogger("platform_bookforge.layers")

DIGEST_SUMMARY_CHARS = 160


# ── digests: compact text views of the structure, for prompts ────────────────

def _read(project, rel: str) -> str:
    return project.resolve(rel).read_text(encoding="utf-8").strip()


def _short(text: str, n: int = DIGEST_SUMMARY_CHARS) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 3] + "..."


def cast_digest(constants: Constants) -> str:
    if not constants.entities and not constants.rules:
        return "none yet"
    lines = [f"- {e.id} ({e.kind}): {e.name}; " + "; ".join(e.facts) for e in constants.entities]
    lines += [f"- rule {r.id}: {r.text}" for r in constants.rules]
    return "\n".join(lines)


def acts_digest(acts: list[Act]) -> str:
    return "\n".join(f"- {a.id} {a.title} ({a.chapter_count} chapters): {_short(a.summary, 200)} Turning point: {_short(a.turning_point, 120)}"
                     for a in acts) or "none"


def chapters_digest(chapters: list[Chapter]) -> str:
    return "\n".join(f"- {c.id} {c.title} (tension {c.tension}): {_short(c.summary)}" for c in chapters) or "none yet (this is the first act)"


def tracks_digest(tracks: list[Track]) -> str:
    if not tracks:
        return "none yet"
    lines = []
    for t in tracks:
        steps = "; ".join(f"{e.from_}: {e.value}" + (" [must_show]" if e.must_show else "") for e in t.plan)
        lines.append(f"- {t.id} (owner {t.entity}, {t.kind}): {steps}")
    return "\n".join(lines)


def _chapter_tracks(tracks: list[Track], book: str, chapter: int) -> tuple[list[Track], list[Track]]:
    def inside(e) -> bool:
        p = parse_position(e.from_)
        return p.book == book and p.chapter == chapter
    touching = [t for t in tracks if any(inside(e) for e in t.plan)]
    return touching, [t for t in tracks if t not in touching]


def tracks_in_chapter_digest(tracks: list[Track], book: str, chapter: int) -> str:
    touching, _ = _chapter_tracks(tracks, book, chapter)
    if not touching:
        return "none"
    lines = []
    for t in touching:
        before = [e for e in t.plan if parse_position(e.from_).book == book and parse_position(e.from_).chapter < chapter]
        here = [e for e in t.plan if parse_position(e.from_).book == book and parse_position(e.from_).chapter == chapter]
        line = f"- {t.id} (owner {t.entity}, {t.kind})"
        if before:
            line += f"\n    before this chapter: {before[-1].value}"
        line += "".join(f"\n    planned: from {e.from_}: {e.value}" + (" [must_show]" if e.must_show else "") for e in here)
        lines.append(line)
    return "\n".join(lines)


# ── cached pieces ───────────────────────────────────────────────────────────

def piece_path(project, layer: str, name: str) -> Path:
    return project.book_dir / "work" / layer / f"{name}.yaml"


def get_piece(
    ctx: StepContext, layer: str, name: str, build_messages: Callable[[], list[dict]],
    parse: Callable[[str], tuple[object, list[str]]], max_tokens: int, before: Callable[[], None] | None = None,
    review: Callable[[str], list[str]] | None = None,
):
    """One checked model reply, cached on disk. Returns the parsed result."""
    project = ctx.project
    path = piece_path(project, layer, name)
    if path.exists():
        result, problems = parse(path.read_text(encoding="utf-8"))
        if not problems:
            log.info("%s/%s: reused saved piece", layer, name)
            return result
        log.info("%s/%s: saved piece no longer fits (%s); asking again", layer, name, problems[0])
    if ctx.llm is None:
        raise LayerError("no model client available")
    if before is not None:
        before()
    layer_cfg = project.config.layers[layer]
    options: dict = {"max_tokens": max_tokens}
    if layer_cfg.temperature is not None:
        options["temperature"] = layer_cfg.temperature
    sink: list = []
    text = ask_until_valid(ctx, f"{layer}/{name}", layer_cfg.model, build_messages(), lambda t: parse(t)[1], options,
                           strip_preamble=False, soft_validate=review if project.config.qc.review_structure else None,
                           soft_sink=sink)
    for label, problems in sink:
        review_notes.add(project, layer, label, problems)
    result, _ = parse(text)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")
    return result


_TEMPLATE_LAYER = {"acts": "acts", "cast": "acts", "chapters": "chapters", "scenes": "scenes"}  # which layer's author note applies


def _messages(project, template: str, **slots) -> list[dict]:
    values = {**prompt_values(project), **slots}
    note = steering.addendum(project, _TEMPLATE_LAYER.get(template, template))
    return [{"role": "system", "content": render("system", project.root, **values)},
            {"role": "user", "content": render(template, project.root, **values) + note}]


def _fact_ids(project) -> set[str]:
    return {f.id for s in stores_for(project).values() for f in s.facts()}


def _clean_work(project, layer: str) -> None:
    shutil.rmtree(project.book_dir / "work" / layer, ignore_errors=True)
    try:
        (project.book_dir / "work").rmdir()  # only succeeds when nothing else is in it
    except OSError:
        pass


def _north_stars(project) -> dict[str, str]:
    return {
        "series_north_star": _read(project, "north-star.md"),
        "book_north_star": _read(project, f"books/{project.book}/north-star.md"),
        "synopsis": _read(project, f"books/{project.book}/synopsis.md"),
    }


def _reviewer(ctx: StepContext, label: str, what: str, parent: str, tracks_text: str, stars: dict[str, str]):
    """A soft check for get_piece / generate_document: the critic's review of a plan against its parent."""
    return lambda text: review_plan(ctx, label, what, parent, text, tracks_text, stars)


def _note_reviews(project, layer: str, note: str, files: list[str]) -> str:
    n = len(review_notes.read(project, layer))
    if n:
        files.append(str(review_notes.path(project).relative_to(project.root)))
        note += f"; {n} review note(s) for you in {files[-1]}"
    return note


def _adopt_problems(project, extra: list[str]) -> list[str]:
    return extra + validate_bible(project)


# ── layer 4: acts ───────────────────────────────────────────────────────────

def acts(ctx: StepContext) -> StepResult:
    project = ctx.project
    lo, hi = project.config.layers["acts"].count or (3, 4)
    clo, chi = project.config.layers["chapters"].count or (25, 35)

    def normalize(text: str) -> str:
        parsed, _ = parse_acts(text, project)
        return dump_yaml({"acts": [to_plain(a) for a in parsed]})

    spec = DocumentSpec(
        layer="acts", prompt="acts", out_path="books/{book}/acts.yaml",
        validate=lambda text: parse_acts(text, project)[1], max_tokens=3000, strip_preamble=False,
        slots=lambda c: {**_north_stars(project), "act_min": str(lo), "act_max": str(hi),
                         "chapter_min": str(clo), "chapter_max": str(chi)},
        normalize=normalize, research_scope="book",
        review=_reviewer(ctx, "acts", "acts of the book", _north_stars(project)["synopsis"], "none yet", _north_stars(project))
        if project.config.qc.review_structure else None,
        research_focus="Rarely needed: only real-world facts that the large-scale structure of the story depends on.",
    )
    return generate_document(ctx, spec)


# ── layer 5: cast, chapters and tracks ──────────────────────────────────────

def validate_chapters_file(project) -> list[str]:
    chapters = store.load_chapters(project)
    problems = _adopt_problems(project, [] if chapters else ["chapters.yaml has no chapters"])
    lo, hi = project.config.layers["chapters"].count or (25, 35)
    if chapters and not lo <= len(chapters) <= hi:
        problems.append(f"chapters.yaml has {len(chapters)} chapters, expected {lo} to {hi}")
    return problems


def chapters(ctx: StepContext) -> StepResult:
    project = ctx.project
    out = store.chapters_path(project)
    files = [store.rel(project, out)]

    if project.state.layers["chapters"].note != REDO_NOTE and out.exists() and out.read_text(encoding="utf-8").strip():
        problems = validate_chapters_file(project)
        if problems:
            raise LayerError("existing chapters.yaml is not acceptable: " + "; ".join(problems[:6])
                             + " (fix the file, or delete it to have it regenerated)")
        note = "adopted existing file"
    else:
        note = _build_chapters(ctx, files)

    note = _note_reviews(project, "chapters", note, files)
    focus = "Settings and events of the chapters: real-world facts about the places, periods, trades and events they use."
    chapters_list = store.load_chapters(project)
    outcome = research_layer(ctx, "book", focus, chapters_digest(chapters_list))
    if outcome is not None:
        files += outcome.files
        note += "; " + outcome.summary()
    return StepResult(files=files, note=note)


def _build_chapters(ctx: StepContext, files: list[str]) -> str:
    project = ctx.project
    if ctx.llm is None:
        raise LayerError("no model client available")
    act_list = store.load_acts(project)
    if not act_list:
        raise LayerError("acts.yaml is missing or empty; the acts layer has to be accepted first")
    stars = _north_stars(project)
    existing = store.load_constants(project)
    acts_text = dump_yaml({"acts": [to_plain(a) for a in act_list]})

    cast_new = get_piece(
        ctx, "chapters", "cast",
        lambda: _messages(project, "cast", acts=acts_text, existing_cast=cast_digest(existing), **stars),
        lambda text: parse_cast(text, existing), max_tokens=3500,
    )
    constants = merge_constants(existing, cast_new)

    tracks = store.load_tracks(project)
    done: list[Chapter] = []
    adopted: list[str] = []
    first = 1
    for act in act_list:
        last = first + act.chapter_count - 1
        bundle = get_piece(
            ctx, "chapters", act.id.split(".")[-1],
            lambda act=act, first=first, last=last: _messages(
                project, "chapters", act=dump_yaml(to_plain(act)), acts_overview=acts_digest(act_list),
                cast=cast_digest(constants), tracks_so_far=tracks_digest(tracks), previous_chapters=chapters_digest(done),
                chapter_count=str(act.chapter_count), first_chapter=_ch(project, first), last_chapter=_ch(project, last), **stars),
            lambda text, act=act, first=first: parse_chapters(
                text, project=project, act=act, first_number=first, constants=constants, tracks_so_far=tracks,
                fact_ids=_fact_ids(project)),
            max_tokens=6000,
            review=_reviewer(ctx, f"chapters {act.id}", f"chapters of {act.id}", dump_yaml(to_plain(act)), tracks_digest(tracks), stars),
        )
        done += bundle.chapters
        if bundle.new_entities:  # places the planner needed that the cast did not list: they join the cast
            adopted += [e.id for e in bundle.new_entities if e.id not in {x.id for x in constants.entities}]
            constants = add_entities(constants, bundle.new_entities)
        tracks = store.upsert_plan(tracks, bundle.tracks)
        first = last + 1

    store.save_constants(project, constants)
    store.save_tracks(project, tracks)
    store.save_chapters(project, done)
    problems = validate_chapters_file(project)
    if problems:
        store.chapters_path(project).unlink(missing_ok=True)  # keep the saved pieces so a rerun does not start over
        raise LayerError("the assembled chapters do not hold together: " + "; ".join(problems[:6]))
    _clean_work(project, "chapters")
    files += ["bible/constants.yaml", "bible/tracks.yaml"]
    if adopted:
        log.info("chapters: %d place(s) added to the cast: %s", len(adopted), ", ".join(adopted))
    return (f"{len(done)} chapters, {len(constants.entities)} entities, {len(tracks)} tracks"
            + (f"; added to the cast because chapters used them: {', '.join(adopted)}" if adopted else ""))


def _ch(project, n: int) -> str:
    from ..bible.positions import chapter_id
    return chapter_id(project.book, n)


# ── layer 6: scenes, timeline and track refinement ──────────────────────────

SCENE_RESEARCH_FOCUS = ("Concrete details for this chapter's scenes: how things look, work and are done in this place and time, "
                        "and what a made-up or changed thing does when these scenes use it.")


def validate_scenes_file(project) -> list[str]:
    return validate_bible(project, require_scenes=True)


def scenes(ctx: StepContext) -> StepResult:
    project = ctx.project
    out = store.scenes_path(project)
    files = [store.rel(project, out)]
    if project.state.layers["scenes"].note != REDO_NOTE and out.exists() and out.read_text(encoding="utf-8").strip():
        problems = validate_scenes_file(project)
        if problems:
            raise LayerError("existing scenes.yaml is not acceptable: " + "; ".join(problems[:6])
                             + " (fix the file, or delete it to have it regenerated)")
        return StepResult(files=files, note="adopted existing file")
    note = _build_scenes(ctx, files)
    note = _note_reviews(project, "scenes", note, files)
    return StepResult(files=files, note=note)


def _build_scenes(ctx: StepContext, files: list[str]) -> str:
    project = ctx.project
    cfg = project.config
    if ctx.llm is None:
        raise LayerError("no model client available")
    chapter_list = store.load_chapters(project)
    if not chapter_list:
        raise LayerError("chapters.yaml is missing or empty; the chapters layer has to be accepted first")
    act_by_id = {a.id: a for a in store.load_acts(project)}
    constants = store.load_constants(project)
    tracks = store.load_tracks(project)
    stars = _north_stars(project)
    scenes_all, timeline_all = [], []
    adopted: list[str] = []
    prev_day: int | None = None
    prev_when = "none: this is the first scene of the book"
    research_files: list[str] = []
    ch_list = list(chapter_list)

    for idx, chapter in enumerate(ch_list):
        ch_num = parse_position(chapter.id).chapter
        before = None
        if cfg.research.enabled and ctx.web is not None and cfg.research.scene_questions > 0:
            def before(chapter=chapter):
                outcome = run_research(ctx, "book", SCENE_RESEARCH_FOCUS, dump_yaml(to_plain(chapter)),
                                       max_questions=cfg.research.scene_questions, applies_to=[chapter.id])
                research_files.extend(outcome.files)

        def build(chapter=chapter, idx=idx, ch_num=ch_num, tracks=tracks, prev_when=prev_when):
            touching, others = _chapter_tracks(tracks, project.book, ch_num)
            lo, hi = cfg.layers["scenes"].per_chapter or (2, 4)
            act = act_by_id.get(chapter.act)
            return _messages(
                project, "scenes", chapter=dump_yaml(to_plain(chapter)),
                act=(f"{act.id} {act.title}: {_short(act.summary, 300)} Turning point: {_short(act.turning_point, 160)}" if act else chapter.act),
                cast=cast_digest(constants), tracks_in_chapter=tracks_in_chapter_digest(tracks, project.book, ch_num),
                other_tracks="\n".join(f"- {t.id} (owner {t.entity})" for t in others) or "none",
                previous_chapter=_short(f"{ch_list[idx - 1].id} {ch_list[idx - 1].title}: {ch_list[idx - 1].summary}") if idx else "none (first chapter)",
                next_chapter=_short(f"{ch_list[idx + 1].id} {ch_list[idx + 1].title}: {ch_list[idx + 1].summary}") if idx + 1 < len(ch_list) else "none (last chapter)",
                previous_time=prev_when, scene_min=str(lo), scene_max=str(hi),
                first_scene=f"{chapter.id}.s1", **{k: v for k, v in stars.items() if k != "synopsis"})

        bundle = get_piece(
            ctx, "scenes", chapter.id.split(".", 1)[1], build,
            lambda text, chapter=chapter, prev_day=prev_day, tracks=tracks: parse_scenes(
                text, project=project, chapter=chapter, prev_day=prev_day, constants=constants, tracks_so_far=tracks,
                fact_ids=_fact_ids(project)),
            max_tokens=3500, before=before,
            review=_reviewer(ctx, f"scenes {chapter.id}", f"scenes of {chapter.id}",
                             dump_yaml(to_plain(chapter)), tracks_in_chapter_digest(tracks, project.book, ch_num), stars),
        )
        if bundle.new_entities:  # places the planner needed that the cast did not list: they join the cast
            adopted += [e.id for e in bundle.new_entities if e.id not in {x.id for x in constants.entities}]
            constants = add_entities(constants, bundle.new_entities)
        scenes_all += bundle.scenes
        timeline_all += bundle.timeline
        tracks = bundle.tracks_after
        for t in bundle.timeline:
            if not t.flashback:
                prev_day = t.day
        last = bundle.timeline[-1]
        prev_when = f"the previous scene ({bundle.scenes[-1].id}) took place on day {last.day}, {last.time}" + (" (a flashback)" if last.flashback else "")

    kept = [t for t in store.load_timeline(project) if parse_position(t.id).book != project.book]
    store.save_timeline(project, kept + timeline_all)
    store.save_tracks(project, tracks)
    if adopted:
        store.save_constants(project, constants)
        log.info("scenes: %d place(s) added to the cast: %s", len(adopted), ", ".join(adopted))
    store.save_scenes(project, scenes_all)
    problems = validate_scenes_file(project)
    if problems:
        store.scenes_path(project).unlink(missing_ok=True)  # keep the saved pieces so a rerun does not start over
        raise LayerError("the assembled scenes do not hold together: " + "; ".join(problems[:6]))
    _clean_work(project, "scenes")
    files += ["bible/timeline.yaml", "bible/tracks.yaml"] + sorted(set(research_files))
    if adopted:
        files.append("bible/constants.yaml")
    return (f"{len(scenes_all)} scenes in {len(ch_list)} chapters, {len(tracks)} tracks"
            + (f"; added to the cast because scenes used them: {', '.join(adopted)}" if adopted else ""))
