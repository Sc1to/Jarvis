"""The model-backed parts of the rules panel: testing a rule on written scenes, and turning a comment into a rule."""

import re

from . import rules, scenefiles
from .bible import store
from .errors import BookforgeError
from .prompts import render
from .qc.mechanical import _banned_regex
from .qc.support import ask_json, quote_in_page

TEST_SCENES = 5


class RuleTestError(BookforgeError):
    pass


def test_scenes(project) -> list:
    """The scenes a new rule is tried on: the written scenes of the first chapter (up to five), else the first written ones."""
    scenes = store.load_scenes(project) if store.scenes_path(project).exists() else []
    written = [s for s in scenes if scenefiles.read(scenefiles.final_path(project, s.id))]
    if not written:
        raise RuleTestError("no scene has been written yet; there is nothing to test the rule on")
    first = written[0].chapter
    return ([s for s in written if s.chapter == first] or written)[:TEST_SCENES]


def test_rule(ctx, rule: rules.Rule) -> dict:
    """What the rule would catch in chapter 1. Banned phrases are matched exactly; other types ask the planner model."""
    project = ctx.project
    results = []
    for s in test_scenes(project):
        text = scenefiles.read(scenefiles.final_path(project, s.id)) or ""
        row = {"scene": s.id, "applies": rules.applies(rule, project, s), "hits": [], "error": None}
        if rule.type == "banned_phrase":
            rx = _banned_regex(rule.phrase.strip())
            row["hits"] = [" ".join(text[max(0, m.start() - 40): m.end() + 40].split()) for m in rx.finditer(text)] if rx else []
        else:
            def check(data: dict, text=text) -> list[str]:
                if not isinstance(data.get("violates"), bool):
                    return ['"violates" must be true or false']
                return []

            try:
                data = ask_json(ctx, f"{s.id} rule test", "critic", "rule_test", check, max_tokens=300, severity=rule.severity, rule=rule.text,
                                example=f"Example: {rule.example}" if rule.example else "", text=text)
                evidence = " ".join(str(data.get("evidence") or "").split())
                if data["violates"] and evidence and quote_in_page(evidence, text):
                    row["hits"] = [evidence]
            except BookforgeError as e:
                row["error"] = str(e)
        results.append(row)
    return {"rule": rule.id, "scenes": results, "total_hits": sum(len(r["hits"]) for r in results)}


def propose_rule(ctx, scene_id: str, passage: str, comment: str) -> dict:
    """A suggested rule for an annotated passage. Not saved: the author edits and saves it."""
    project = ctx.project
    scene = next((s for s in store.load_scenes(project) if s.id == scene_id), None)
    if scene is None:
        raise RuleTestError(f"no scene '{scene_id}'")
    if not passage.strip() or not comment.strip():
        raise RuleTestError("give the passage and your comment")

    def check(data: dict) -> list[str]:
        problems = []
        if data.get("type") not in rules.RULE_TYPES:
            problems.append(f"'type' must be one of: {', '.join(rules.RULE_TYPES)}")
        if data.get("scope") not in rules.SCOPES:
            problems.append(f"'scope' must be one of: {', '.join(rules.SCOPES)}")
        if data.get("severity") not in rules.SEVERITIES:
            problems.append(f"'severity' must be one of: {', '.join(rules.SEVERITIES)}")
        if not str(data.get("text") or "").strip():
            problems.append("'text' must be the rule in one sentence")
        return problems

    data = ask_json(ctx, f"{scene_id} rule from feedback", "critic", "rule_from_feedback", check, max_tokens=500, passage=passage.strip(),
                    comment=comment.strip(), characters=", ".join(scene.characters))
    scope, target = data["scope"], str(data.get("target") or "")
    if scope == "scene":
        target = scene_id
    if scope == "book":
        target = project.book
    if data["type"] == "character_voice":
        scope, target = "character", target if target in scene.characters else scene.pov
    if scope == "character" and target not in scene.characters:
        target = scene.pov
    slug = re.sub(r"[^a-z0-9]+", "-", str(data["text"]).lower()).strip("-")[:30].strip("-") or "rule"
    existing = {r.id for r in rules.load_rules(project)}
    rid, n = slug, 1
    while rid in existing:
        n += 1
        rid = f"{slug}-{n}"
    return {"id": rid, "type": data["type"], "scope": scope, "target": target, "severity": data["severity"], "text": str(data["text"]).strip(),
            "example": str(data.get("example") or "").strip(), "phrase": str(data.get("phrase") or "").strip() if data["type"] == "banned_phrase" else "", "enabled": True}
