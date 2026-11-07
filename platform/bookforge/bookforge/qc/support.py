"""Small helpers shared by the model-based quality checks."""

from ..ask import ask_until_valid
from ..bible.models import Scene
from ..prompts import render
from ..research.step import parse_json_object, quote_in_page  # noqa: F401  (re-exported)
from .. import scenefiles

VOICE_GUIDE_CHARS = 2500
VOICE_SAMPLE_CHARS = 1200


def voice_excerpt(project) -> str:
    """The style guide and the first sample passage: what a judge or critic needs to hear the voice. Not the bible."""
    guide = scenefiles.read(project.root / "style" / "guide.md") or ""
    if all(not line.strip() or line.lstrip().startswith("#") for line in guide.splitlines()):
        guide = ""
    parts = [guide.strip()[:VOICE_GUIDE_CHARS]] if guide else []
    samples = sorted((project.root / "style" / "samples").glob("*.md")) if (project.root / "style" / "samples").is_dir() else []
    for p in samples[:1]:
        text = scenefiles.read(p)
        if text:
            parts.append("Sample passage:\n" + text.strip()[:VOICE_SAMPLE_CHARS])
    return "\n\n".join(parts) or "(no style guide or samples yet: judge the voice against the tone in the book north star)"


def scene_brief(project, scene: Scene) -> str:
    beats = "\n".join(f"{i}. {b}" for i, b in enumerate(scene.beats, 1))
    cfg = project.config.book
    return (f"Purpose: {scene.purpose}\nPoint of view: {cfg.pov}. Tense: {cfg.tense}.\nBeats, in order:\n{beats}")


def messages(project, template: str, **slots) -> list[dict]:
    return [{"role": "system", "content": render("qc_system", project.root)},
            {"role": "user", "content": render(template, project.root, **slots)}]


def qc_role(project) -> str:
    """The model role that answers the checks inside the prose layer (qc.model)."""
    return project.config.qc.model


def qc_options(project) -> dict:
    """Call options for those checks: on the writer model the checks use qc.temperature instead of a drafting temperature."""
    return {"temperature": project.config.qc.temperature} if project.config.qc.model != "critic" else {}


def ask_json(ctx, label: str, role: str, template: str, check, max_tokens: int = 1500, call_options: dict | None = None, **slots) -> dict:
    """Ask for a JSON object; `check(data)` returns problems, which are sent back for correction."""
    msgs = messages(ctx.project, template, **slots)

    def validate(text: str) -> list[str]:
        data = parse_json_object(text)
        return ["the reply must be a single JSON object in exactly the requested shape"] if data is None else check(data)

    text = ask_until_valid(ctx, label, role, msgs, validate, {"max_tokens": max_tokens, **(call_options or {})}, strip_preamble=False)
    return parse_json_object(text) or {}
