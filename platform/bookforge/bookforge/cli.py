"""Command line: new, run, status, approve, doctor."""

import json
import logging
from pathlib import Path
from typing import Optional

import typer

from . import vcs
from .constants import CHECKPOINTS, LAYER_ORDER
from .doctor import run_doctor
from .errors import BookforgeError
from .layers import HANDLERS
from .layers.runner import run as run_layers
from .llm import build_client
from .project import Project

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
        summary = run_layers(project, llm=build_client(project), handlers=HANDLERS, until=until)
    except BookforgeError as e:
        _fail(e)
    for layer in summary.ran:
        typer.echo(f"accepted: {layer}")
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
