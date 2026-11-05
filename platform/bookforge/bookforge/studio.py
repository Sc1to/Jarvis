"""Prompt studio: the prompt templates, their slots, and series-specific overrides in `workbench/prompts/`.

A template is a Markdown file with named slots like `{north_star}`. An override must only use slots the shipped
template has (the code gives values for exactly those); leaving one out is allowed and reported.
"""

import difflib
from pathlib import Path

from .errors import BookforgeError
from .project import Project
from .prompts import OVERRIDE_SUBDIR, PROMPT_DIR, slots_in, template_path


class StudioError(BookforgeError):
    pass


def names() -> list[str]:
    return sorted(p.stem for p in PROMPT_DIR.glob("*.md"))


def _default(name: str) -> str:
    if name not in names():
        raise StudioError(f"no prompt template '{name}'")
    return (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")


def override_path(project: Project, name: str) -> Path:
    return project.root / OVERRIDE_SUBDIR / f"{name}.md"


def list_templates(project: Project) -> list[dict]:
    out = []
    for n in names():
        d = _default(n)
        out.append({"name": n, "slots": sorted(slots_in(d)), "overridden": override_path(project, n).is_file(), "words": len(d.split())})
    return out


def get_template(project: Project, name: str) -> dict:
    d = _default(name)
    p = override_path(project, name)
    o = p.read_text(encoding="utf-8") if p.is_file() else None
    return {"name": name, "slots": sorted(slots_in(d)), "default": d, "override": o, "effective": o if o is not None else d,
            "diff": unified_diff(d, o) if o is not None else ""}


def unified_diff(a: str, b: str, from_label: str = "shipped", to_label: str = "yours") -> str:
    return "".join(difflib.unified_diff(a.splitlines(True), b.splitlines(True), from_label, to_label))


def check_candidate(name: str, text: str) -> dict:
    """(errors, warnings) for a candidate template: unknown slots break rendering, dropped slots lose information."""
    d = _default(name)
    known, used = slots_in(d), slots_in(text)
    errors = []
    if not text.strip():
        errors.append("the template is empty")
    unknown = sorted(used - known)
    if unknown:
        errors.append(f"unknown slot(s) {', '.join('{' + u + '}' for u in unknown)}: the code gives values only for {', '.join('{' + k + '}' for k in sorted(known)) or 'no slots'}")
    return {"errors": errors, "warnings": [f"the slot {{{m}}} is not used any more: the model will not see that information" for m in sorted(known - used)]}


def save_override(project: Project, name: str, text: str) -> dict:
    result = check_candidate(name, text)
    if result["errors"]:
        raise StudioError("; ".join(result["errors"]))
    p = override_path(project, name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
    return result


def delete_override(project: Project, name: str) -> None:
    _default(name)
    p = override_path(project, name)
    if not p.is_file():
        raise StudioError(f"'{name}' has no override")
    p.unlink()


def effective_text(project: Project, name: str) -> str:
    return template_path(name, project.root).read_text(encoding="utf-8")
