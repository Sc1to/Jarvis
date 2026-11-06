"""Command line: new, run, status, approve, doctor."""

import json
import logging
from pathlib import Path
from typing import Optional

import typer

from . import books as book_mgmt, assemble as assembly, changes as change_requests, deletion, export as exporting, ops, report as morning_report, stale as staleness, vcs
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
        outcome = ops.run_pipeline(project, build_client(project), web, until, handlers=HANDLERS)
    except BookforgeError as e:
        _fail(e)
    summary, assembled, report_path = outcome.summary, outcome.assembled, outcome.report_path
    if outcome.report_error:
        typer.secho(f"warning: no morning report: {outcome.report_error}", fg=typer.colors.YELLOW, err=True)
    for layer in summary.ran:
        typer.echo(f"accepted: {layer}" + (f" ({summary.notes[layer]})" if layer in summary.notes else ""))
    if not summary.ran:
        typer.echo("nothing ran")
    if summary.detail:
        typer.echo(summary.detail)
    elif summary.stopped == "complete":
        typer.echo("all layers accepted")
    if assembled:
        typer.echo(f"assembled {assembled.path}: {assembled.words} words in {assembled.scenes} scenes"
                   + (f", tagged {assembled.tag}" if assembled.tag else "") + "; read it, then `approve final`")
    if report_path:
        typer.echo(f"morning report: {report_path}")
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
        ops.approve_checkpoint(project, checkpoint)
    except BookforgeError as e:
        _fail(e)
    typer.echo(f"Approved '{checkpoint}'.")


@app.command("finding")
def finding_cmd(
    path: Path = PathArg,
    scene: str = typer.Argument(..., help="The scene, like b1.ch07.s2"),
    question: str = typer.Option(..., "--question", help="The finding, exactly as the review shows it (the fact it is about)"),
    dismiss: bool = typer.Option(False, "--dismiss", help="A false alarm: do not ask about it again for this scene"),
    instruct: Optional[str] = typer.Option(None, "--instruct", help="What the writer should do about it when the scene is revised"),
    clear: bool = typer.Option(False, "--clear", help="Take back a dismissal or an instruction"),
    book: str = BookOpt,
) -> None:
    """Tell the pipeline what you think of a finding that flagged a scene. It applies the next time the scene runs."""
    action = "dismiss" if dismiss else "instruct" if instruct else "clear" if clear else None
    try:
        if action is None or (dismiss + bool(instruct) + clear) > 1:
            raise BookforgeError("give exactly one of --dismiss, --instruct \"...\" or --clear")
        notes = ops.decide_finding(Project.open(path, book), scene, question, action, instruct or "")
    except BookforgeError as e:
        _fail(e)
    typer.echo(f"{scene}: {len(notes['dismissed'])} dismissed, {len(notes['instructions'])} instruction(s); applied the next time it runs")


@app.command("add-book")
def add_book_cmd(
    path: Path = PathArg,
    title: str = typer.Option(..., "--title", help="What the book is called"),
    brief: Optional[str] = typer.Option(None, "--brief", help="What this book is about, in a few sentences"),
    brief_file: Optional[Path] = typer.Option(None, "--brief-file", help="Read the brief from this file"),
) -> None:
    """Add a book to a series. It gets its own brief and north star and inherits the series north star."""
    try:
        text = brief_file.read_text(encoding="utf-8") if brief_file else (brief or "")
        project = book_mgmt.add_book(path, title, text)
    except (BookforgeError, OSError) as e:
        _fail(e)
    typer.echo(f"added book {project.book} '{project.state.title}'; run it with `run {path} --book {project.book}`")


@app.command("title")
def title_cmd(path: Path = PathArg, title: str = typer.Argument(..., help="The new title"), book: str = BookOpt) -> None:
    """Give a book a title (its id, like b1, never changes)."""
    try:
        project = Project.open(path, book)
        typer.echo(f"{project.book}: '{book_mgmt.set_title(project, title)}'")
    except BookforgeError as e:
        _fail(e)


@app.command("rename-series")
def rename_series_cmd(path: Path = PathArg, new_name: str = typer.Argument(..., help="The new name (lowercase letters, digits, - and _)")) -> None:
    """Rename a series: its folder is moved to the new name, in the same place."""
    try:
        dest = book_mgmt.rename_series(Path(path).resolve().parent, Path(path).resolve().name, new_name)
    except BookforgeError as e:
        _fail(e)
    typer.echo(f"renamed to {dest}")


@app.command("redo")
def redo_cmd(
    path: Path = PathArg,
    layer: str = typer.Argument(..., help=f"The planning layer to write again, one of: {', '.join(ops.REDOABLE)}"),
    note: str = typer.Option("", "--note", help="What to change, in your words; the model sees it with the previous version"),
    cascade: bool = typer.Option(False, "--cascade", help="Also reset the later layers that were built on it"),
    book: str = BookOpt,
) -> None:
    """Have a planning layer written again (then `run`). Nothing is deleted: the current files are committed first."""
    try:
        project = Project.open(path, book)
        out = ops.redo_layer(project, layer, note, cascade)
    except BookforgeError as e:
        _fail(e)
    a = out["archived"]
    moved = f"\nresearch moved to research/archive/: {a['questions']} question(s), {a['facts']} fact(s), {a['needs']} undecided need(s); your own decisions stay" if any(a.values()) else ""
    typer.echo(f"reset: {', '.join(out['reset'])}" + ("; your note will be used" if out["note"] else "") + moved
               + f"\nthe checkpoints they belong to are pending again; run `run {path}` to write them")


@app.command("research-test")
def research_test_cmd(
    path: Path = PathArg,
    question: str = typer.Argument(..., help="A factual question, in plain words"),
    query: Optional[str] = typer.Option(None, "--query", help="What to search for (default: the question itself)"),
    setting: str = typer.Option("any time", "--setting", help="The time and place an answer must fit, like 'England, 1880s'"),
    book: str = BookOpt,
    show_pages: bool = typer.Option(False, "--show-pages", help="Also print, for each page, the text the model was shown and its raw reply"),
) -> None:
    """Try one research question end to end and show what was searched, read, kept and dropped. Stores nothing."""
    from .layers.runner import StepContext
    from .research import probe
    from .research.step import Question, answer_question
    try:
        project = Project.open(path, book)
        web = build_web_client(project)
        ctx = StepContext(project=project, layer="synopsis", llm=build_client(project), web=web)
        story = (project.root / "premise.md").read_text(encoding="utf-8") if (project.root / "premise.md").exists() else ""
        q = Question(question, query or question, False, setting)
        attempt = answer_question(ctx, web, q, story, set())
    except BookforgeError as e:
        _fail(e)
    for line in probe.describe(attempt, q, probe.source_of(web), show_pages):
        typer.echo(line)
    raise typer.Exit(0 if attempt.facts else 1)


@app.command("research-eval")
def research_eval_cmd(
    path: Path = PathArg,
    document: str = typer.Option("premise.md", "--document", help="Propose the needs from this file (relative to the series, or a full path): the premise, a north star, the synopsis"),
    recorded: bool = typer.Option(False, "--recorded", help="Run the lookup needs already recorded for the series and book instead of proposing new ones"),
    max_questions: int = typer.Option(8, "--max", help="At most this many needs"),
    realism: Optional[str] = typer.Option(None, "--realism", help="Propose the needs under this realism setting instead of the series' own, e.g. 'Hard SF: physics must hold'"),
    audit: bool = typer.Option(True, "--audit/--no-audit", help="Audit each kept claim against its quote with a separate model call"),
    book: str = BookOpt,
) -> None:
    """Judge the whole research stage: propose or take a story's needs, run every lookup, audit the claims. Stores nothing."""
    from .layers.runner import StepContext
    from .realism import realism_setting
    from .research import evaluate
    from .research.probe import source_of
    try:
        project = Project.open(path, book)
        doc_path = Path(document) if Path(document).is_absolute() else project.root / document
        try:
            text = doc_path.read_text(encoding="utf-8")
        except OSError:
            raise BookforgeError(f"cannot read {doc_path} (use --document to name the file the needs come from)") from None
        web = build_web_client(project)
        ctx = StepContext(project=project, layer="synopsis", llm=build_client(project), web=web)
        questions = evaluate.recorded_questions(project) if recorded else evaluate.propose(ctx, text, max_questions, realism)
        rows = evaluate.evaluate(ctx, web, questions[:max_questions], text, audit)
    except BookforgeError as e:
        _fail(e)
    for line in evaluate.describe(rows, source_of(web), realism if realism is not None else realism_setting(project), "recorded needs" if recorded else document):
        typer.echo(line)
    raise typer.Exit(0 if evaluate.bar_met(rows) else 1)


@app.command("delete")
def delete_cmd(
    path: Path = PathArg,
    book: Optional[str] = typer.Option(None, "--book", help="Delete only this book (default: the whole series, moved to the trash)"),
    yes: bool = typer.Option(False, "--yes", help="Do not ask"),
) -> None:
    """Delete a book (Git keeps its history), or move a whole series to the trash (`trash` restores or empties it)."""
    what = f"book {book} of {path.name} (its entries in the shared bible files go too)" if book else f"the series {path.name} (moved to {path.parent / deletion.TRASH})"
    if not yes and not typer.confirm(f"Delete {what}?"):
        raise typer.Exit(1)
    try:
        if book:
            r = deletion.delete_book(path, book)
            typer.echo(f"deleted book {book}: {r['track_entries_removed']} track entries, {r['timeline_removed']} timeline entries removed"
                       + (f"; {r['inactive_rules']} rule(s) were scoped to it and no longer apply" if r["inactive_rules"] else ""))
        else:
            dest = deletion.trash_series(path.parent, path.name)
            typer.echo(f"moved to {dest}\nRestore: python -m bookforge trash {path.parent} --restore {dest.name}")
    except BookforgeError as e:
        _fail(e)


@app.command("trash")
def trash_cmd(
    data_dir: Optional[Path] = typer.Argument(None, help="The bookforge data directory (default: data_dir from the config)"),
    restore: Optional[str] = typer.Option(None, "--restore", help="Move this trashed series back"),
    empty: bool = typer.Option(False, "--empty", help="Remove everything in the trash for good"),
) -> None:
    """List the trashed series, restore one, or empty the trash."""
    from .config import load_config
    try:
        base = data_dir or Path(load_config().data_dir)
        if restore:
            typer.echo(f"restored as {deletion.restore(base, restore)}")
        elif empty:
            typer.echo(f"removed {deletion.empty_trash(base)} item(s) from the trash")
        else:
            items = deletion.list_trash(base)
            for t in items:
                typer.echo(f"{t['name']}  (series {t['series']}, books: {', '.join(t['books']) or 'none'}, deleted {t['deleted'] or '?'})")
            if not items:
                typer.echo("the trash is empty")
    except BookforgeError as e:
        _fail(e)


@app.command()
def rewrite(
    path: Path = PathArg,
    targets: list[str] = typer.Argument(..., help="Scenes or chapters to write again, like b1.ch01.s1 or b1.ch01, or `all`"),
    book: str = BookOpt,
    force: bool = typer.Option(False, "--force", help="Also discard text you wrote yourself"),
    reset_voice: bool = typer.Option(False, "--reset-voice", help="Ask for the voice checkpoint again: the next run writes chapter 1 only (when chapter 1 is rewritten)"),
) -> None:
    """Throw away scenes (or a chapter) so the next `run` writes them again. Deleting files alone does not do this."""
    try:
        project = Project.open(path, book)
        result = ops.rewrite_scenes(project, list(targets), force, reset_voice)
    except BookforgeError as e:
        _fail(e)
    typer.echo(f"reset {len(result['reset'])} scene(s): {', '.join(result['reset']) or 'none'}")
    if result["kept"]:
        typer.secho(f"kept (text you wrote; use --force to discard): {', '.join(result['kept'])}", fg=typer.colors.YELLOW)
    if result["voice_reset"]:
        typer.echo("The voice checkpoint is pending again: the next run writes chapter 1 and waits for you.")
    if result["reset"]:
        typer.echo(f"Next: python -m bookforge run {project.root} --book {project.book}")


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
        result = ops.stale_pass(project, build_client(project) if fix else None, fix, list(accept or []), set(only) if only else None)
    except BookforgeError as e:
        _fail(e)
    report = result.report
    for r in result.fixes:
        typer.echo(f"{r.scene}: {r.action}" + (f" ({r.note})" if r.note else ""))
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


@app.command()
def report(
    path: Path = PathArg,
    book: str = BookOpt,
    write: bool = typer.Option(False, "--write", help="Save it under reports/ as well"),
) -> None:
    """Print the morning report: progress, what needs you, what is unsure, suggestions, facts to verify."""
    try:
        project = Project.open(path, book)
        typer.echo(morning_report.build_report(project))
        if write:
            saved = morning_report.write_report(project)
            if project.config.git.commit_each_step:
                vcs.commit(project.root, f"{project.book}: morning report", [saved])
            typer.echo(f"saved {saved}")
    except (BookforgeError, OSError) as e:
        _fail(e)


@app.command("assemble")
def assemble_cmd(
    path: Path = PathArg,
    book: str = BookOpt,
    partial: bool = typer.Option(False, "--partial", help="Write what is accepted so far to manuscript-partial.md (no tag, no checkpoint)"),
) -> None:
    """Join the accepted scenes into books/<book>/manuscript.md and reach the final checkpoint."""
    try:
        project = Project.open(path, book)
        result = assembly.assemble(project, partial)
    except BookforgeError as e:
        _fail(e)
    typer.echo(f"{result.path}: {result.words} words in {result.scenes} scenes" + (f", tagged {result.tag}" if result.tag else ""))
    if result.missing:
        typer.echo(f"left out (not accepted yet): {', '.join(result.missing)}")
    if not partial:
        typer.echo("Read it, then `approve final`.")


@app.command("export")
def export_cmd(
    path: Path = PathArg,
    book: str = BookOpt,
    fmt: Optional[list[str]] = typer.Option(None, "--format", "-f", help=f"{', '.join(exporting.FORMATS)} or all (repeatable; default all)"),
    draft: bool = typer.Option(False, "--draft", help="Export even though the final checkpoint is not approved (tagged as a draft)"),
) -> None:
    """Build DOCX, EPUB, print PDF and the companion book from the manuscript with Pandoc."""
    formats = None if not fmt or "all" in fmt else list(fmt)
    try:
        project = Project.open(path, book)
        result = exporting.export_book(project, formats, draft)
    except BookforgeError as e:
        _fail(e)
    typer.echo(f"{result.directory}" + (f" (tagged {result.tag})" if result.tag else ""))
    for f in result.files:
        typer.echo(f"  {f}")
    for k, why in result.skipped.items():
        typer.secho(f"  skipped {k}: {why}", fg=typer.colors.YELLOW)
    for w in result.warnings:
        typer.secho(f"  warning: {w}", fg=typer.colors.YELLOW)


@app.command()
def bench(
    path: Path = PathArg,
    book: str = BookOpt,
    only: Optional[list[str]] = typer.Option(None, "--only", help="Only this benchmark (repeatable)"),
    accept: bool = typer.Option(False, "--accept", help="Make this run the baseline (if it does not lose)"),
    force: bool = typer.Option(False, "--force", help="With --accept: even if the comparison lost"),
    no_judge: bool = typer.Option(False, "--no-judge", help="Skip the pairwise judgments (mechanical comparison only)"),
) -> None:
    """Redraft the benchmark scenes and compare them with the last accepted run."""
    try:
        project = Project.open(path, book)
        outcome = ops.bench_pass(project, build_client(project), list(only) if only else None, accept, force, not no_judge)
    except BookforgeError as e:
        _fail(e)
    run_, comparison, accepted = outcome.run, outcome.comparison, outcome.accepted
    typer.echo(f"{run_.name}: {len(run_.results)} benchmark scene(s) in workbench/experiments/{run_.name}/")
    for bid, r in run_.results.items():
        typer.echo(f"  {bid}: {r['words']} words, score {r['score']} ({r['blocking']} blocking, {r['warnings']} warning(s))")
    if comparison is None:
        typer.echo("no accepted baseline yet" + ("" if accepted else "; run with --accept to make this one"))
    else:
        if comparison["changed"]:
            typer.echo(f"changed since the baseline: {', '.join(comparison['changed'])}")
        for bid, row in comparison["rows"].items():
            extra = f" (score {row['score'][0]} -> {row['score'][1]})" if "score" in row else ""
            typer.echo(f"  {bid}: {row['verdict']}{extra}")
        for line in comparison["regressions"]:
            typer.echo(f"  REGRESSION {line}")
        typer.echo(f"{comparison['wins']} won, {comparison['losses']} lost, {comparison['ties']} tied: "
                   + ("it does not lose." if comparison["ships"] else "it loses; do not ship this change."))
    if accepted:
        typer.echo(f"accepted {run_.name} as the baseline")
    elif accept:
        typer.echo("not accepted: it loses (use --force to accept anyway)")
    raise typer.Exit(0 if comparison is None or comparison["ships"] else 1)


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
        if approve_id or reject_id:
            decided = ops.decide_change(project, approve_id or reject_id, bool(approve_id))
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


@app.command("needs")
def needs_cmd(
    path: Path = PathArg,
    book: str = BookOpt,
    approve_id: Optional[str] = typer.Option(None, "--approve", help="Approve this rule, assumption or deviation"),
    reject_id: Optional[str] = typer.Option(None, "--reject", help="Reject it (it will not be proposed again)"),
    edit_id: Optional[str] = typer.Option(None, "--edit", help="Change the stance and/or text of this need (it goes back to 'proposed')"),
    stance: Optional[str] = typer.Option(None, "--stance", help="ground, extrapolate, bend or invent"),
    rule: Optional[str] = typer.Option(None, "--rule", help="The rule, assumption or deviation, in your words"),
    applies_to: Optional[list[str]] = typer.Option(None, "--applies-to", help="Chapters or scenes it applies to, like b1.ch03 or b1.ch03.s2 (repeat the option); 'all' for the whole book"),
    show_all: bool = typer.Option(False, "--all", help="Also list lookups that need no decision"),
) -> None:
    """List what the story needs to know or decide, and approve, reject or edit a proposed rule, assumption or deviation."""
    try:
        project = Project.open(path, book)
        target = approve_id or reject_id or edit_id
        decided = None
        if target:
            if edit_id and not (stance or rule or applies_to):
                raise BookforgeError("--edit needs --stance, --rule and/or --applies-to")
            places = None if applies_to is None else [] if [a.casefold() for a in applies_to] == ["all"] else applies_to
            decided = ops.decide_need(project, target, True if approve_id else False if reject_id else None, stance, rule, places)
        needs = ops.list_needs(project)
    except BookforgeError as e:
        _fail(e)
    if decided:
        typer.echo(f"{decided.id}: {decided.status} ({decided.stance})")
    shown = [(scope, n) for scope, n in needs if show_all or n.status != "approved" or n.decided_by == "author"]
    if not shown:
        typer.echo("nothing waiting for you" if needs else "no needs recorded yet")
    for scope, n in shown:
        typer.echo(f"{n.id} [{n.stance}, {n.status}] {n.question}" + (f"\n    why: {n.reason}" if n.reason else "")
                   + (f"\n    proposed: {n.rule}" if n.rule else "") + (f"\n    applies to: {', '.join(n.applies_to)}" if n.applies_to else "") + (f"\n    facts: {', '.join(n.fact_ids)}" if n.fact_ids else ""))


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
