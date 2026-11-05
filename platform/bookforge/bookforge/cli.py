"""Command line: new, run, status, approve, doctor."""

import json
import logging
from pathlib import Path
from typing import Optional

import typer

from . import changes as change_requests, stale as staleness, vcs
from .constants import CHECKPOINTS, LAYER_ORDER
from . import scenefiles
from .bible import store as bible_store
from .bible.lookup import day_of, scene_entities, state_at
from .bible.positions import parse_position
from .briefing import build_briefing
from .doctor import run_doctor
from .errors import BookforgeError
from .layers import HANDLERS
from .layers.prose import check_context
from .layers.runner import StepContext, run as run_layers
from .llm import build_client
from .project import Project
from .qc.mechanical import check_scene
from .research.search import build_web_client

app = typer.Typer(add_completion=False, no_args_is_help=True, help="Bookforge: automated book-writing pipeline.")

PathArg = typer.Argument(..., help="Series folder")
BookOpt = typer.Option("b1", "--book", help="Book id inside the series")


def _fail(e: Exception) -> None:
    typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
    raise typer.Exit(1)


@app.callback()
def _main(verbose: bool = typer.Option(False, "--verbose", "-v", help="Log at DEBUG level")) -> None:
    logging.basicConfig(level=logging.DEBUG if verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s")


@app.command()
def new(
    path: Path = PathArg,
    premise: Path = typer.Option(..., "--premise", help="Markdown file with the premise (a few paragraphs)"),
    book: str = BookOpt,
) -> None:
    """Create a new series folder (its own Git repository) with its first book."""
    try:
        if not premise.is_file():
            raise BookforgeError(f"premise file not found: {premise}")
        project = Project.create(path, premise.read_text(encoding="utf-8"), book)
    except BookforgeError as e:
        _fail(e)
    typer.echo(f"Created series at {project.root} (book {project.book}).")
    typer.echo(f"Next: python -m bookforge run {project.root} --book {project.book}")


@app.command()
def run(
    path: Path = PathArg,
    book: str = BookOpt,
    until: Optional[str] = typer.Option(None, "--until", help=f"Stop after this layer ({', '.join(LAYER_ORDER)})"),
) -> None:
    """Run the pipeline until a checkpoint, the --until layer, or the end."""
    try:
        project = Project.open(path, book)
        web = build_web_client(project) if project.config.research.enabled else None
        summary = run_layers(project, llm=build_client(project), handlers=HANDLERS, until=until, web=web)
    except BookforgeError as e:
        _fail(e)
    for layer in summary.ran:
        typer.echo(f"accepted: {layer}" + (f" ({summary.notes[layer]})" if layer in summary.notes else ""))
    if not summary.ran:
        typer.echo("nothing ran")
    if summary.detail:
        typer.echo(summary.detail)
    elif summary.stopped == "complete":
        typer.echo("all layers accepted")
    raise typer.Exit(summary.exit_code)


@app.command()
def status(
    path: Path = PathArg,
    book: str = BookOpt,
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output"),
) -> None:
    """Show the status of every layer and checkpoint."""
    try:
        project = Project.open(path, book)
    except BookforgeError as e:
        _fail(e)
    state = project.state
    if as_json:
        typer.echo(state.model_dump_json(indent=2))
        return
    typer.echo(f"{project.root}  book {state.book}")
    typer.echo("\nLayers")
    for name in LAYER_ORDER:
        item = state.layers[name]
        cp = project.config.layers[name].checkpoint
        typer.echo(f"  {name:<18} {item.status:<9} v{item.version}" + (f"   [{cp}]" if cp else ""))
    scenes = bible_store.load_scenes(project) if bible_store.scenes_path(project).exists() else []
    if scenes:
        counts: dict[str, int] = {}
        for s in scenes:
            item = state.items.get(s.id)
            counts[item.status if item else "pending"] = counts.get(item.status if item else "pending", 0) + 1
        typer.echo(f"\nProse: {len(scenes)} scenes: " + ", ".join(f"{n} {k}" for k, n in sorted(counts.items())))
    typer.echo("\nCheckpoints")
    for name in CHECKPOINTS:
        typer.echo(f"  {name:<18} {state.checkpoints[name].status}")


@app.command()
def approve(path: Path = PathArg, checkpoint: str = typer.Argument(..., help=f"One of: {', '.join(CHECKPOINTS)}"), book: str = BookOpt) -> None:
    """Approve a checkpoint that is waiting for you."""
    try:
        project = Project.open(path, book)
        project.state.approve_checkpoint(checkpoint)
        project.save_state()
        if checkpoint == "structure":
            staleness.record_plan(project)  # from now on, a changed act or chapter makes what was planned from it stale
        message = f"{project.book}: {checkpoint} approved"
        # Commit everything: the approved version includes any edits you made while reviewing.
        if project.config.git.commit_each_step or project.config.git.tag_checkpoints:
            vcs.commit(project.root, message)
        if project.config.git.tag_checkpoints:
            vcs.tag(project.root, f"{project.book}-{checkpoint}-approved", message)
    except BookforgeError as e:
        _fail(e)
    typer.echo(f"Approved '{checkpoint}'.")


@app.command()
def stale(
    path: Path = PathArg,
    book: str = BookOpt,
    fix: bool = typer.Option(False, "--fix", help="Bring stale scenes up to date: re-check, then patch, then redraft"),
    accept: Optional[list[str]] = typer.Option(None, "--accept", help="Say a scene or planned chapter is fine as it is (repeatable)"),
    only: Optional[list[str]] = typer.Option(None, "--only", help="With --fix: only this scene (repeatable)"),
) -> None:
    """List everything that is out of date and why; with --fix, bring written scenes up to date."""
    try:
        project = Project.open(path, book)
        scene_ids = {s.id for s in bible_store.load_scenes(project)} if bible_store.scenes_path(project).exists() else set()
        for target in accept or []:
            if target in scene_ids:
                staleness.accept_as_is(project, target)
            elif target in {c.id for c in bible_store.load_chapters(project)} | scene_ids:
                staleness.record_plan(project, {target})
            else:
                raise BookforgeError(f"'{target}' is not a scene or chapter of this book")
        if fix:
            llm = build_client(project)
            for r in staleness.fix_all(StepContext(project=project, layer="prose", llm=llm), set(only) if only else None):
                typer.echo(f"{r.scene}: {r.action}" + (f" ({r.note})" if r.note else ""))
        report = staleness.scan(project)
        staleness.sync_status(project, report)
        if project.config.git.commit_each_step:
            keep = [project.state_path, staleness.plan_deps_path(project)]
            vcs.commit(project.root, f"{project.book}: stale scan", [str(f.relative_to(project.root)) for f in keep if f.exists()])
    except BookforgeError as e:
        _fail(e)
    if report.empty and not report.problems:
        typer.echo("nothing is out of date")
        return
    for st in report.scenes:
        typer.echo(f"{st.scene}: stale, start with {st.level}")
        for line in st.why():
            typer.echo(f"    {line}")
    for p in report.plan:
        typer.echo(f"{p.id}: plan out of date ({p.reason}); review it, then `stale --accept {p.id}`")
    for line in report.problems:
        typer.echo(f"could not check {line}")
    raise typer.Exit(1)


@app.command("changes")
def changes_cmd(
    path: Path = PathArg,
    book: str = BookOpt,
    approve_id: Optional[str] = typer.Option(None, "--approve", help="Apply this change request to the plan"),
    reject_id: Optional[str] = typer.Option(None, "--reject", help="Keep the plan: the scene's prose will be patched to agree with it"),
) -> None:
    """List change requests (the prose says something the plan does not); approve or reject one."""
    try:
        project = Project.open(path, book)
        decided = None
        if approve_id:
            decided = change_requests.approve(project, approve_id)
        elif reject_id:
            decided = change_requests.reject(project, reject_id)
        if decided and project.config.git.commit_each_step:
            vcs.commit(project.root, f"{project.book}: change request {decided.id} {decided.status}")
        requests = change_requests.list_requests(project)
    except BookforgeError as e:
        _fail(e)
    if decided:
        typer.echo(f"{decided.id}: {decided.status}")
        if decided.status == "applied":
            typer.echo(f"{len(decided.affects)} scene(s) depend on it; run `stale --fix` to bring them up to date")
        else:
            typer.echo(f"the plan stands; run `stale --fix` to patch {decided.proposed_by} to agree with it")
    if not requests:
        typer.echo("no change requests")
    for c in requests:
        typer.echo(f"{c.id} [{c.status}{', ' + c.decided_by if c.decided_by else ''}] {c.proposed_by}, {c.entity or c.track}: "
                   f"plan '{c.planned}' -> prose '{c.observed}' ({len(c.affects)} scene(s), {c.scope})")


@app.command("state-at")
def state_at_cmd(
    path: Path = PathArg,
    position: str = typer.Argument(..., help="A chapter or scene, like b1.ch05 or b1.ch05.s2"),
    entity: Optional[list[str]] = typer.Option(None, "--entity", "-e", help="Only tracks of this entity (repeatable). Default for a scene: its characters and setting"),
    book: str = BookOpt,
) -> None:
    """Show what is true at a point in the story, according to the bible."""
    try:
        project = Project.open(path, book)
        pos = parse_position(position)
        scenes = bible_store.load_scenes(project)
        timeline = bible_store.load_timeline(project)
        tracks = bible_store.load_tracks(project)
        wanted = set(entity) if entity else (scene_entities(scenes, pos.id) if pos.is_scene else set())
    except (BookforgeError, ValueError) as e:
        _fail(e)
    day = day_of(timeline, pos.id)
    when = next((t for t in timeline if t.id == pos.id), None)
    typer.echo(f"{pos.id}" + (f"  day {day}, {when.time}" if when else ""))
    if wanted:
        typer.echo("entities: " + ", ".join(sorted(wanted)))
    states = state_at(tracks, pos.id, wanted or None)
    if not states:
        typer.echo("no tracked states apply here")
    for s in states:
        flags = (" [begins here]" if s.begins_here else "") + (" [must show on the page]" if s.must_show else "")
        typer.echo(f"- {s.track_id} ({s.entity}, {s.kind}) since {s.since}: {s.value}{flags}")
        if s.begins_here and s.previous:
            typer.echo(f"    before: {s.previous}")


@app.command()
def briefing(
    path: Path = PathArg,
    scene: str = typer.Argument(..., help="A scene, like b1.ch04.s3"),
    book: str = BookOpt,
    tokens: Optional[int] = typer.Option(None, "--tokens", help="Token budget (default: briefing.max_tokens)"),
    full: bool = typer.Option(False, "--full", help="Print the whole briefing, not only the size of each part"),
) -> None:
    """Show what the model is given to write a scene: the size of each part and, with --full, the text."""
    try:
        project = Project.open(path, book)
        b = build_briefing(project, scene, tokens)
    except BookforgeError as e:
        _fail(e)
    typer.echo(f"{scene}: about {b.tokens} of {b.budget} tokens")
    for heading, n in b.breakdown():
        typer.echo(f"  {n:>6}  {heading}")
    for note in b.trimmed:
        typer.echo(f"  cut to fit: {note}")
    if full:
        typer.echo("\n" + b.text())


@app.command()
def check(
    path: Path = PathArg,
    scene: str = typer.Argument(..., help="A scene, like b1.ch04.s3"),
    book: str = BookOpt,
    file: Optional[Path] = typer.Option(None, "--file", help="Check this file instead of the scene's own text"),
) -> None:
    """Run the mechanical checks on a scene's text (banned phrases, repetition, rhythm, length, ...)."""
    try:
        project = Project.open(path, book)
        scenes = bible_store.load_scenes(project)
        target = next((s for s in scenes if s.id == scene), None)
        if target is None:
            raise BookforgeError(f"no scene {scene} in scenes.yaml")
        text = file.read_text(encoding="utf-8") if file else scenefiles.best_text(project, scene)
        if not text:
            raise BookforgeError(f"{scene} has no text yet (write it first, or pass --file)")
        report = check_scene(text, check_context(project, target, scenes))
    except (BookforgeError, OSError) as e:
        _fail(e)
    s = report.stats
    typer.echo(f"{scene}: {s['words']} words, {s['sentences']} sentences, dialogue {s['dialogue_ratio']:.0%}, sentence variation {s['sentence_variation']}")
    for issue in report.issues:
        typer.echo(f"  [{issue.severity}] {issue.code}: {issue.message}" + (f"  ...{issue.excerpt}..." if issue.excerpt else ""))
    for note in report.skipped:
        typer.echo(f"  [skipped] {note}")
    if not report.issues:
        typer.echo("  no problems found")
    raise typer.Exit(1 if report.blocking else 0)


@app.command()
def review(
    path: Path = PathArg,
    scene: str = typer.Argument(..., help="A scene, like b1.ch04.s3"),
    book: str = BookOpt,
) -> None:
    """Show how a scene went through quality control: draft choice, scores, flags, revisions, gaps."""
    import json
    try:
        project = Project.open(path, book)
        raw = scenefiles.read(scenefiles.review_path(project, scene))
        if raw is None:
            raise BookforgeError(f"{scene} has no review yet (it has not been written)")
        r = json.loads(raw)
    except (BookforgeError, ValueError) as e:
        _fail(e)
    item = project.state.items.get(scene)
    typer.echo(f"{scene}: {item.status if item else 'pending'}" + (f" ({item.note})" if item and item.note else ""))
    typer.echo(f"  chosen: {r.get('chosen')} ({r.get('source')}), briefing {r.get('briefing_tokens')} of {r.get('budget_tokens')} tokens")
    for name, rep in (r.get("mechanical") or {}).items():
        typer.echo(f"  mechanical {name}: score {rep['score']}, {len([i for i in rep['issues'] if i['severity'] == 'block'])} blocking, "
                   f"{len([i for i in rep['issues'] if i['severity'] == 'warn'])} warning(s)")
    if r.get("judge"):
        typer.echo(f"  judge: wins {r['judge']['wins']}" + (f" (error: {r['judge']['error']})" if r['judge'].get('error') else ""))
    for rd in r.get("rounds") or []:
        typer.echo(f"  round {rd['round']}: blocking {len(rd['mechanical_blocking'])}, continuity flags {len(rd['continuity_flags'])}, "
                   f"critic lowest {rd['critic_lowest']}, revised {len(rd['revisions'])} passage(s)")
    if r.get("critic"):
        c = r["critic"]
        typer.echo("  critic: " + (f"error: {c['error']}" if c.get("error") else ", ".join(f"{k} {v}" for k, v in c["scores"].items())))
    if r.get("continuity") and r["continuity"].get("unsure"):
        typer.echo(f"  continuity: {len(r['continuity']['unsure'])} unsure answer(s)")
    for g in (r.get("extraction") or {}).get("gaps", []):
        typer.echo(f"  gap: {g['track']}: planned '{g['planned']}', the scene shows '{g['observed']}'")
    for reason in r.get("blocking") or []:
        typer.echo(f"  NEEDS YOU: {reason}")


@app.command()
def doctor(
    path: Optional[Path] = typer.Argument(None, help="Series folder to check as well"),
    book: str = BookOpt,
    offline: bool = typer.Option(False, "--offline", help="Skip the model endpoint checks and the web fetch"),
) -> None:
    """Check the environment, the colibri endpoints and the web tool (and a series, if given)."""
    marks = {"pass": ("PASS", typer.colors.GREEN), "warn": ("WARN", typer.colors.YELLOW), "fail": ("FAIL", typer.colors.RED)}
    failed = False
    for c in run_doctor(path, book, online=not offline):
        label, colour = marks[c.level]
        typer.echo(typer.style(f"[{label}]", fg=colour) + f" {c.name}" + (f": {c.detail}" if c.detail else ""))
        failed = failed or c.level == "fail"
    raise typer.Exit(1 if failed else 0)
