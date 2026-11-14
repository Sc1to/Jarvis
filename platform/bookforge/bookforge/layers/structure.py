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
    add_entities, count_range, merge_constants, merge_derived, parse_acts, parse_cast, parse_chapters, parse_scenes, validate_bible,
)
from ..constants import REDO_NOTE
from ..errors import LayerError
from ..ledger_view import status_text
from ..prompts import render
from ..qc.plan_review import review_plan
from ..research.notes import stores_for
from ..research.select import notes_text
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


def chapters_end_digest(chapters: list[Chapter]) -> str:
    """Where each chapter left things: the story so far, from the plan's end states."""
    return "\n".join(f"- {c.id} {c.title}: {c.end_state or _short(c.summary)}" for c in chapters) or "none yet (this is the first act)"


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

def _forced_counts(project) -> str:
    cfg = project.config.layers
    parts = []
    if cfg["acts"].count:
        parts.append(f"The author requires {cfg['acts'].count[0]} to {cfg['acts'].count[1]} acts.")
    if cfg["chapters"].count:
        parts.append(f"The author requires the chapter counts to add up to between {cfg['chapters'].count[0]} and {cfg['chapters'].count[1]}.")
    return " ".join(parts)


def _ledger_acts(ctx: StepContext, ledger) -> StepResult:
    from ..ledger_view import events_text
    from ..validators import ledger as ledger_checks, store as findings_store
    project = ctx.project
    stars = _north_stars(project)
    plain_events = [e.model_dump() for e in ledger.events]

    def normalize(text: str) -> str:
        parsed, _ = parse_acts(text, project, ledger)
        for a in parsed:  # the real weights next to the model's reasoning, so the saved file is honest about its sizing
            note = ledger_checks.sizing_note(a.model_dump(), plain_events, project.config.ledger.weight_per_chapter)
            a.sizing_reason = f"{a.sizing_reason} {note}".strip() if "[computed:" not in a.sizing_reason else a.sizing_reason
        return dump_yaml({"acts": [to_plain(a) for a in parsed]})

    spec = DocumentSpec(
        layer="acts", prompt="acts_ledger", out_path="books/{book}/acts.yaml",
        validate=lambda text: parse_acts(text, project, ledger)[1], max_tokens=3500, strip_preamble=False,
        slots=lambda c: {**stars, "ledger_events": events_text(ledger.events), "constraints": _forced_counts(project),
                         "weight_per_chapter": f"{project.config.ledger.weight_per_chapter:g}"},
        normalize=normalize, research_scope="book",
        review=_reviewer(ctx, "acts", "acts of the book", stars["synopsis"], "none yet", stars) if project.config.qc.review_structure else None,
        research_focus="Rarely needed: only real-world facts that the large-scale structure of the story depends on.",
    )
    result = generate_document(ctx, spec)
    act_list = store.load_acts(project)
    findings = ledger_checks.check_acts([a.model_dump() for a in act_list], plain_events, weight_per_chapter=project.config.ledger.weight_per_chapter)
    hard_left = [f.line() for f in findings if f.severity == "hard"]
    if hard_left:  # an adopted (hand-edited) file passes through the same checks
        raise LayerError("acts.yaml does not fit the ledger: " + "; ".join(hard_left[:6]))
    result.files.append(findings_store.save(project, "acts", findings))
    total = sum(a.chapter_count for a in act_list)
    result.note += f"; {len(act_list)} acts, {total} chapters planned from {len(ledger.events)} events"
    return result


def acts(ctx: StepContext) -> StepResult:
    project = ctx.project
    ledger = store.active_ledger(project)
    if ledger is not None:
        return _ledger_acts(ctx, ledger)
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
    lo, hi = count_range(project, "chapters")
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
    ledger = store.active_ledger(project)
    done: list[Chapter] = []
    adopted: list[str] = []
    first = 1
    for act in act_list:
        last = first + act.chapter_count - 1
        if ledger is None:
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
        else:
            before = list(done)
            act_text = dump_yaml(to_plain(act)) + "\n".join(e.text for e in ledger.events if e.id in act.events)
            bundle = get_piece(
                ctx, "chapters", act.id.split(".")[-1],
                lambda act=act, first=first, last=last, before=before, ledger=ledger: _messages(
                    project, "chapters_ledger", act=dump_yaml(to_plain(act)), acts_overview=acts_digest(act_list),
                    ledger_status=status_text(ledger, set(act.events), before), story_so_far=chapters_end_digest(before),
                    cast=cast_digest(constants), tracks_so_far=tracks_digest(tracks), research_notes=notes_text(project, act_text),
                    chapter_count=str(act.chapter_count), first_chapter=_ch(project, first), last_chapter=_ch(project, last), **stars),
                lambda text, act=act, first=first, before=before, ledger=ledger: parse_chapters(
                    text, project=project, act=act, first_number=first, constants=constants, tracks_so_far=tracks,
                    fact_ids=_fact_ids(project), ledger=ledger, chapters_before=before, acts=act_list),
                max_tokens=7000,
                review=_reviewer(ctx, f"chapters {act.id}", f"chapters of {act.id}", dump_yaml(to_plain(act)), tracks_digest(tracks), stars),
            )
            if bundle.derived:  # minor complications join the ledger, so later acts and the validators see them
                ledger = ledger.model_copy(update={"events": merge_derived(ledger.events, bundle.derived)})
        done += bundle.chapters
        if bundle.new_entities:  # places the planner needed that the cast did not list: they join the cast
            adopted += [e.id for e in bundle.new_entities if e.id not in {x.id for x in constants.entities}]
            constants = add_entities(constants, bundle.new_entities)
        tracks = store.upsert_plan(tracks, bundle.tracks)
        first = last + 1

    store.save_constants(project, constants)
    store.save_tracks(project, tracks)
    store.save_chapters(project, done)
    if ledger is not None:
        store.save_ledger(project, ledger)
        files.append("books/%s/ledger.yaml" % project.book)
        files.append(_book_chapter_checks(project, done, ledger))
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


def _book_chapter_checks(project, chapters: list[Chapter], ledger) -> str:
    """Whole-book checks once every act is planned: events and flat stretches. Hard findings stop the layer (the pieces are kept)."""
    from ..validators import HARD, ledger as ledger_checks, repeats, store as findings_store, tension
    ch = [c.model_dump() for c in chapters]
    ev = [e.model_dump() for e in ledger.events]
    acts_plain = [a.model_dump() for a in store.load_acts(project)]
    findings = (ledger_checks.check_chapters(ch, ev, acts_plain) + ledger_checks.check_chapter_texts(ch, ev) + repeats.repeated_events(ch, [], ledger_events=ev)
                + tension.flat_stretches(ch) + [f for f in ledger_checks.check_ledger(ev) if f.severity == "soft"])
    rel = findings_store.save(project, "chapters", findings)
    hard_left = [f.line() for f in findings if f.severity == HARD]
    if hard_left:
        store.chapters_path(project).unlink(missing_ok=True)  # keep the saved pieces so a rerun does not start over
        raise LayerError("the chapters do not hold together: " + "; ".join(hard_left[:6]) + f" (all findings: {rel})")
    return rel


def story_so_far_planning(project, chapters_before: list[Chapter], scenes_before: list) -> str:
    """The story so far for the scene planner: from written scene summaries where the prose exists, else from the planned end states."""
    from .. import scenefiles
    by_chapter: dict[str, list] = {}
    for s in scenes_before:
        by_chapter.setdefault(s.chapter, []).append(s)
    lines = []
    for c in chapters_before:
        scs = by_chapter.get(c.id, [])
        written = [t for s in scs if (t := scenefiles.read(scenefiles.summary_path(project, s.id)))]
        if written:
            lines.append(f"- {c.id} {c.title} (written): " + " ".join(t.strip() for t in written))
        else:
            lines.append(f"- {c.id} {c.title} (planned): {(scs[-1].end_state if scs and scs[-1].end_state else c.end_state) or _short(c.summary)}")
    return "\n".join(lines) or "nothing yet: this is the first chapter"


def _book_scene_checks(project, chapters: list[Chapter], scenes_all: list, timeline: list, tracks: list[Track], constants, ledger) -> str:
    """Whole-book checks on the planned scenes. Hard findings stop the layer (the pieces are kept for a rerun)."""
    from ..validators import HARD, ledger as ledger_checks, repeats, research_leak, state as state_checks, store as findings_store
    ch = [c.model_dump() for c in chapters]
    sc = [s.model_dump() for s in scenes_all]
    tl = [t.model_dump() for t in timeline]
    ev = [e.model_dump() for e in ledger.events]
    names = {e.id for e in constants.entities} | {w.lower() for e in constants.entities if e.kind == "character" for w in e.name.split()}
    claims = [f.claim for s in stores_for(project).values() for f in s.facts()]
    story_texts = [_read(project, f"books/{project.book}/synopsis.md"), _read(project, "north-star.md"), _read(project, f"books/{project.book}/north-star.md"),
                   " ".join(e.text for e in ledger.events), " ".join(" ".join(e.facts) + " " + e.name for e in constants.entities)]
    tracks_plain = [to_plain(t) for t in tracks]
    findings = (ledger_checks.check_scenes_vs_chapters(sc, ch, ev) + ledger_checks.check_scene_texts(sc, ch, ev) + repeats.repeated_events(ch, sc, names, ev, stage="scenes")
                + repeats.action_patterns(sc, ch, names) + research_leak.research_in_beats(sc, claims, story_texts)
                + state_checks.track_regressions(tracks_plain) + state_checks.location_conflicts(sc, tl, tracks_plain) + state_checks.day_regressions(sc, tl))
    rel = findings_store.save(project, "scenes", findings)
    hard_left = [f.line() for f in findings if f.severity == HARD]
    if hard_left:
        store.scenes_path(project).unlink(missing_ok=True)  # keep the saved pieces so a rerun does not start over
        raise LayerError("the scenes do not hold together: " + "; ".join(hard_left[:6]) + f" (all findings: {rel})")
    return rel


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
    ledger = store.active_ledger(project)

    for idx, chapter in enumerate(ch_list):
        ch_num = parse_position(chapter.id).chapter
        before = None
        if cfg.research.enabled and ctx.web is not None and cfg.research.scene_questions > 0:
            def before(chapter=chapter):
                outcome = run_research(ctx, "book", SCENE_RESEARCH_FOCUS, dump_yaml(to_plain(chapter)),
                                       max_questions=cfg.research.scene_questions, applies_to=[chapter.id])
                research_files.extend(outcome.files)

        def build(chapter=chapter, idx=idx, ch_num=ch_num, tracks=tracks, prev_when=prev_when, scenes_so_far=list(scenes_all)):
            touching, others = _chapter_tracks(tracks, project.book, ch_num)
            lo, hi = count_range(project, "scenes")
            act = act_by_id.get(chapter.act)
            if ledger is not None:
                act_line = f"{act.id} {act.title}: {_short(act.summary, 300)} Turning point: {_short(act.turning_point, 160)}" if act else chapter.act
                return _messages(
                    project, "scenes_ledger", chapter=dump_yaml(to_plain(chapter)), act=act_line,
                    ledger_status=status_text(ledger, set(chapter.events_covered), ch_list[:idx], "SHOWN IN THIS CHAPTER: plan scenes for these"),
                    story_so_far=story_so_far_planning(project, ch_list[:idx], scenes_so_far),
                    cast=cast_digest(constants), tracks_in_chapter=tracks_in_chapter_digest(tracks, project.book, ch_num),
                    other_tracks="\n".join(f"- {t.id} (owner {t.entity})" for t in others) or "none",
                    previous_time=prev_when, research_notes=notes_text(project, dump_yaml(to_plain(chapter))),
                    first_scene=f"{chapter.id}.s1", **{k: v for k, v in stars.items() if k != "synopsis"})
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
                fact_ids=_fact_ids(project), ledger=ledger, all_chapters=ch_list),
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
    if ledger is not None:
        files.append(_book_scene_checks(project, ch_list, scenes_all, timeline_all, tracks, constants, ledger))
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
