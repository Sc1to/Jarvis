"""Prompt templates: bookforge/prompts/<name>.md, with per-series overrides.

A template names its inputs as `{slot_name}` (lowercase letters and underscores).
Every slot in the template must be given a value; leftover or missing slots are
errors rather than silent blanks. Avoid other lowercase `{words}` in template
text, they would be read as slots.

A series can override any template by putting a file of the same name in
<series>/workbench/prompts/ (versioned with the series).
"""

import re
from pathlib import Path

from .errors import PromptError

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
OVERRIDE_SUBDIR = Path("workbench") / "prompts"
_SLOT = re.compile(r"\{([a-z][a-z_]*)\}")
_NAME = re.compile(r"^[a-z][a-z_]*$")


def template_path(name: str, series_root: Path | None = None) -> Path:
    if not _NAME.match(name):
        raise PromptError(f"invalid prompt name: {name!r}")
    if series_root is not None:
        override = series_root / OVERRIDE_SUBDIR / f"{name}.md"
        if override.is_file():
            return override
    return PROMPT_DIR / f"{name}.md"


def slots_in(template: str) -> set[str]:
    return set(_SLOT.findall(template))


def render(name: str, series_root: Path | None = None, **values: str) -> str:
    path = template_path(name, series_root)
    try:
        template = path.read_text(encoding="utf-8")
    except OSError as e:
        raise PromptError(f"cannot read prompt template {path}: {e}") from e
    missing = slots_in(template) - set(values)
    if missing:
        raise PromptError(f"prompt '{name}' ({path}) needs values for: {', '.join(sorted(missing))}")
    # One pass over the template, so text inside a value is never treated as a slot.
    return _SLOT.sub(lambda m: str(values[m.group(1)]), template).strip() + "\n"
