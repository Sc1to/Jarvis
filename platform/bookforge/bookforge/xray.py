"""Briefing preview and X-ray: what the model was given for a scene, and where the input is thin.

`preview` is the exact assembled briefing with the token size of each part. `xray` adds findings and a
diagnosis that separates the three causes of a bad result: missing input (the briefing lacked something the
scene needed), a weak prompt (the inputs were complete but the template is one you rewrote) and model
limits (complete inputs, shipped prompt, and the model still did not do it). With `beats=True` and a written
scene, the planner model also checks which planned beats are really on the page ("beat 3 never happened").
"""

import json

from . import rules, scenefiles
from .bible import store
from .bible.lookup import scene_entities, state_at
from .briefing import build_briefing
from .errors import BookforgeError
from .project import Project
from .prompts import template_path
from .qc.support import ask_json, quote_in_page


def preview(project: Project, scene_id: str, tokens: int | None = None) -> dict:
    b = build_briefing(project, scene_id, tokens)
    return {"scene": scene_id, "tokens": b.tokens, "budget": b.budget, "trimmed": b.trimmed,
            "sections": [{"heading": s.heading, "tokens": s.tokens, "text": s.body} for s in b.sections]}


def _overridden(project: Project, name: str) -> bool:
    return template_path(name, project.root).parent != template_path(name, None).parent


def input_findings(project: Project, scene_id: str) -> list[dict]:
    """Gaps in what the writer was given. severity: problem (it will hurt the result), warn, info."""
    b = build_briefing(project, scene_id)
    scenes = store.load_scenes(project)
    scene = next(s for s in scenes if s.id == scene_id)
    constants = store.load_constants(project)
    known = {e.id for e in constants.entities}
    sections = {s.heading: s.body for s in b.sections}
    out: list[dict] = []

    def add(severity: str, kind: str, message: str) -> None:
        out.append({"severity": severity, "kind": kind, "message": message})

    for eid in dict.fromkeys([scene.pov, scene.setting, *scene.characters]):
        if eid not in known:
            add("problem", "unknown_entity", f"'{eid}' is in the scene plan but not in the cast: the writer was given no facts about it")
    if sections.get("Style guide", "").startswith("(no style guide"):
        add("warn", "no_style_guide", "there is no style guide: the writer follows only the tone of the north stars")
    if not any(h.startswith("Sample passages") for h in sections):
        add("warn", "no_samples", "there are no sample passages to match the voice against")
    if scenes and scenes[0].id != scene_id and not any(h.startswith("The end of the previous scene") for h in sections):
        add("warn", "no_previous_text", "the previous scene has no text yet, so nothing links this scene to it")
    if not any(h == "When this scene happens" for h in sections):
        add("warn", "no_timeline", "the scene has no timeline entry: the writer does not know when it happens")
    states = state_at(store.load_tracks(project), scene_id, scene_entities(scenes, scene_id))
    if not states:
        add("info", "no_states", "no tracked state applies at this scene")
    for st in states:
        if st.must_show:
            add("info", "must_show", f"this change must happen on the page: {st.value}")
    if not any(h.startswith("Research notes") for h in sections):
        add("info", "no_research", "the scene cites no research facts")
    for note in b.trimmed:
        add("warn" if "style guide" in note or "sample" in note else "info", "trimmed", f"cut to fit the token budget: {note}")
    if b.tokens > 0.9 * b.budget:
        add("info", "budget", f"the briefing uses {b.tokens} of {b.budget} tokens")
    n_rules = len(rules.rules_for(project, scene))
    add("info", "rules", f"{n_rules} rule(s) from the rules panel apply to this scene")
    return out


def beat_coverage(ctx, scene_id: str) -> list[dict]:
    """For a written scene: which planned beats are on the page, each with a quotation. Raises BookforgeError."""
    project = ctx.project
    scene = next(s for s in store.load_scenes(project) if s.id == scene_id)
    text = scenefiles.best_text(project, scene_id)
    if not text:
        raise BookforgeError(f"{scene_id} has no text yet")
    n = len(scene.beats)

    def check(data: dict) -> list[str]:
        items = data.get("beats")
        if not isinstance(items, list):
            return ["'beats' must be a list"]
        seen, problems = set(), []
        for i, it in enumerate(items):
            if not isinstance(it, dict) or not isinstance(it.get("n"), int) or not 1 <= it["n"] <= n:
                problems.append(f"beats[{i}].n must be a beat number from 1 to {n}")
                continue
            seen.add(it["n"])
            if not isinstance(it.get("happens"), bool):
                problems.append(f"beat {it['n']}: 'happens' must be true or false")
        problems += [f"no entry for beat {k}" for k in range(1, n + 1) if k not in seen]
        return problems

    data = ask_json(ctx, f"{scene_id} beats", "critic", "xray_beats", check, max_tokens=300 + 100 * n,
                    text=text, beats="\n".join(f"{i}. {b}" for i, b in enumerate(scene.beats, 1)))
    by_n = {it["n"]: it for it in data["beats"]}
    out = []
    for i, beat in enumerate(scene.beats, 1):
        it = by_n[i]
        evidence = " ".join(str(it.get("evidence") or "").split())
        happens = bool(it["happens"]) and bool(evidence) and quote_in_page(evidence, text)  # a claim needs a quotation that is really there
        out.append({"n": i, "beat": beat, "happens": happens, "evidence": evidence if happens else ""})
    return out


def diagnose(project: Project, scene_id: str, findings: list[dict], beats: list[dict] | None) -> dict:
    """Which of the three causes the evidence points to, with the reasons."""
    problems = [f for f in findings if f["severity"] in ("problem", "warn")]
    missing = [b for b in (beats or []) if not b["happens"]]
    critic = None
    raw = scenefiles.read(scenefiles.review_path(project, scene_id))
    if raw:
        try:
            critic = ((json.loads(raw).get("critic") or {}).get("scores") or {}).get("beats_covered")
        except ValueError:
            critic = None
    reasons: list[str] = []
    if problems:
        cause = "missing_input"
        reasons += [f["message"] for f in problems]
    elif missing:
        weak = [n for n in ("prose", "prose_system") if _overridden(project, n)]
        if weak:
            cause = "weak_prompt"
            reasons.append(f"the inputs are complete but you have rewritten {', '.join(weak)}: try the shipped prompt on the benchmarks (A/B)")
        else:
            cause = "model_limit"
            reasons.append("the inputs are complete and the prompts are the shipped ones: likely a limit of the writer model; try another draft or a stronger model")
    else:
        cause = "none"
        reasons.append("nothing points to a problem" + ("" if beats is not None else " (beat coverage was not checked)"))
    if missing:
        reasons.append("beats not on the page: " + ", ".join(str(b["n"]) for b in missing))
    if critic is not None and critic <= 2:
        reasons.append(f"the critic scored beats_covered {critic}")
    return {"cause": cause, "reasons": reasons}


def xray(ctx, scene_id: str, beats: bool = False) -> dict:
    project = ctx.project
    findings = input_findings(project, scene_id)
    coverage = None
    error = None
    if beats and ctx.llm is not None:
        try:
            coverage = beat_coverage(ctx, scene_id)
        except BookforgeError as e:
            error = str(e)
    return {"scene": scene_id, "findings": findings, "beats": coverage, "beats_error": error,
            "diagnosis": diagnose(project, scene_id, findings, coverage)}
