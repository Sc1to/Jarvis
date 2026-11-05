"""Where a scene's prose lives: books/<book>/scenes/ch05/s1/{draft-N.md, final.md, summary.md, review.json, deps.yaml}."""

from pathlib import Path

from .bible.models import Scene
from .bible.positions import parse_position
from .project import Project


def scene_dir(project: Project, scene_id: str) -> Path:
    p = parse_position(scene_id)
    return project.book_dir / "scenes" / f"ch{p.chapter:02d}" / f"s{p.scene}"


def final_path(project: Project, scene_id: str) -> Path:
    return scene_dir(project, scene_id) / "final.md"


def summary_path(project: Project, scene_id: str) -> Path:
    return scene_dir(project, scene_id) / "summary.md"


def review_path(project: Project, scene_id: str) -> Path:
    return scene_dir(project, scene_id) / "review.json"


def deps_path(project: Project, scene_id: str) -> Path:
    return scene_dir(project, scene_id) / "deps.yaml"


def draft_path(project: Project, scene_id: str, n: int) -> Path:
    return scene_dir(project, scene_id) / f"draft-{n}.md"


def read(path: Path) -> str | None:
    """The file's text, or None if it is missing or empty."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    return text if text.strip() else None


def previous_scene(scenes: list[Scene], scene_id: str) -> Scene | None:
    for i, s in enumerate(scenes):
        if s.id == scene_id:
            return scenes[i - 1] if i else None
    return None


def best_text(project: Project, scene_id: str) -> str | None:
    """The scene's accepted text, or else the draft chosen for it (a flagged scene still has one)."""
    final = read(final_path(project, scene_id))
    if final:
        return final
    import json
    review = read(review_path(project, scene_id))
    if review:
        try:
            chosen = json.loads(review).get("chosen")
        except ValueError:
            chosen = None
        if chosen:
            return read(scene_dir(project, scene_id) / f"{chosen}.md")
    return None


def rel(project: Project, path: Path) -> str:
    return str(path.relative_to(project.root))
