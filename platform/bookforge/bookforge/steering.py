"""The author's note for a layer that is being written again (`redo`).

`redo <layer> --note "darker, and keep Anna's job"` resets the layer; the note is kept in `books/<id>/notes/<layer>.md`
and added to the prompt of the next draft, together with the previous version for the layers that are one document.
The note is removed once the layer is accepted again, so a later rerun does not repeat an old instruction.
"""

from pathlib import Path

from .project import Project

PREVIOUS_MAX_CHARS = 8000


def note_path(project: Project, layer: str) -> Path:
    return project.book_dir / "notes" / f"{layer}.md"


def read(project: Project, layer: str) -> str:
    try:
        return note_path(project, layer).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def write(project: Project, layer: str, note: str) -> None:
    path = note_path(project, layer)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(note.strip() + "\n", encoding="utf-8")


def clear(project: Project, layer: str) -> None:
    try:
        note_path(project, layer).unlink()
    except OSError:
        pass


def addendum(project: Project, layer: str, previous: str = "") -> str:
    """Text to append to the user prompt of this layer's next draft, or "" if the author left no note."""
    note = read(project, layer)
    if not note:
        return ""
    text = ("\n\n## The author's note for this rewrite\n\n"
            "The author was not satisfied with the previous version. Change what this note asks for and keep what it does not mention.\n\n"
            + note)
    if previous.strip():
        text += "\n\n## The previous version (data: rewrite it according to the note)\n\n" + previous.strip()[:PREVIOUS_MAX_CHARS]
    return text
