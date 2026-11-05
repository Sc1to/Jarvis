"""The rules panel's data: do's and don'ts in `workbench/rules.yaml`, and how each kind is enforced.

| type            | enforced by                                                                                      |
|-----------------|--------------------------------------------------------------------------------------------------|
| banned_phrase   | the mechanical checker (a phrase, or `re:` plus a regular expression); also told to the writer   |
| style_rule      | the writer's briefing and the critic's prompt (the critic scores against it)                     |
| hard_constraint | an extra continuity question for every scene the rule applies to                                  |
| character_voice | the writer's briefing and the critic's prompt, for scenes with that character                    |

Severity: `block` fails the check (and is revised), `warn` is reported in the morning report, `note` is only
recorded. Scope: `series` (every scene), `book` (one book), `character` (scenes where the character is present
or the viewpoint), `scene`. A rule that changes also changes the scenes' `deps.yaml`, so what it touches goes stale.
"""

import re
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .bible.models import Scene
from .errors import BookforgeError
from .project import Project
from .qc.mechanical import _banned_regex

RULE_TYPES = ("banned_phrase", "style_rule", "hard_constraint", "character_voice")
SEVERITIES = ("block", "warn", "note")
SCOPES = ("series", "book", "character", "scene")


class RuleError(BookforgeError):
    pass


class Rule(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,40}$")
    type: Literal["banned_phrase", "style_rule", "hard_constraint", "character_voice"]
    text: str = Field(min_length=1, max_length=500)  # the rule in plain words
    example: str = Field("", max_length=500)  # a bad (and/or good) example
    scope: Literal["series", "book", "character", "scene"] = "series"
    target: str = ""  # book id, character id or scene id, as the scope needs
    severity: Literal["block", "warn", "note"] = "warn"
    phrase: str = Field("", max_length=200)  # banned_phrase only
    enabled: bool = True

    @model_validator(mode="after")
    def _consistent(self):
        if self.type == "banned_phrase":
            if not self.phrase.strip():
                raise ValueError("a banned_phrase rule needs a phrase")
            if _banned_regex(self.phrase.strip()) is None:
                raise ValueError(f"the phrase is not a usable pattern: {self.phrase}")
        if self.scope in ("character", "scene") and not self.target:
            raise ValueError(f"scope '{self.scope}' needs a target (a {'character id' if self.scope == 'character' else 'scene id'})")
        if self.type == "character_voice" and self.scope != "character":
            raise ValueError("a character_voice rule must have scope 'character'")
        return self


def rules_path(project: Project):
    return project.root / "workbench" / "rules.yaml"


def load_rules(project: Project) -> list[Rule]:
    path = rules_path(project)
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        items = data.get("rules", []) if isinstance(data, dict) else []
        rules = [Rule.model_validate(r) for r in items]
    except (OSError, yaml.YAMLError, ValidationError) as e:
        raise RuleError(f"{path} is not valid: {e}") from e
    if len({r.id for r in rules}) != len(rules):
        raise RuleError(f"{path}: rule ids must be unique")
    return rules


def save_rules(project: Project, rules: list[Rule]) -> None:
    path = rules_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"rules": [r.model_dump() for r in rules]}, sort_keys=False, allow_unicode=True, width=100), encoding="utf-8")


def upsert(project: Project, rule: Rule) -> Rule:
    rules = load_rules(project)
    rules = [rule if r.id == rule.id else r for r in rules] if any(r.id == rule.id for r in rules) else rules + [rule]
    save_rules(project, rules)
    return rule


def delete(project: Project, rule_id: str) -> None:
    rules = load_rules(project)
    if not any(r.id == rule_id for r in rules):
        raise RuleError(f"no rule '{rule_id}'")
    save_rules(project, [r for r in rules if r.id != rule_id])


def applies(rule: Rule, project: Project, scene: Scene) -> bool:
    if not rule.enabled:
        return False
    if rule.scope == "series":
        return True
    if rule.scope == "book":
        return rule.target in ("", project.book)
    if rule.scope == "character":
        return rule.target == scene.pov or rule.target in scene.characters
    return rule.target == scene.id


def rules_for(project: Project, scene: Scene, types: tuple[str, ...] | None = None) -> list[Rule]:
    return [r for r in load_rules(project) if applies(r, project, scene) and (types is None or r.type in types)]


def phrase_rules(rules: list[Rule]) -> list[tuple[str, str, str]]:
    """(rule id, phrase, severity) for the banned-phrase rules."""
    return [(r.id, r.phrase.strip(), r.severity) for r in rules if r.type == "banned_phrase"]


def blocking_phrases(rules: list[Rule]) -> list[str]:
    return [r.phrase.strip() for r in rules if r.type == "banned_phrase" and r.severity == "block"]


_LEVEL = {"block": "MUST", "warn": "SHOULD", "note": "NOTE"}


def prose_rules_text(project: Project, scene: Scene) -> str:
    """The style and voice rules for the writer and the critic, one line each, ready for a prompt."""
    names = {}
    try:
        from .bible import store
        names = {e.id: e.name for e in store.load_constants(project).entities}
    except BookforgeError:
        pass
    lines = []
    for r in rules_for(project, scene, ("style_rule", "character_voice")):
        who = f" ({names.get(r.target, r.target)})" if r.type == "character_voice" else ""
        ex = f" Example: {r.example}" if r.example else ""
        lines.append(f"- {_LEVEL[r.severity]}{who}: {r.text}{ex}")
    return "\n".join(lines)


def fingerprint_parts(project: Project, scene: Scene) -> tuple[list, list]:
    """What the scene depends on: (style-like rules, hard constraints), as plain data for `deps.py` fingerprints."""
    mine = rules_for(project, scene)
    return ([r.model_dump() for r in mine if r.type != "hard_constraint"], [r.model_dump() for r in mine if r.type == "hard_constraint"])


# ── how often each rule fired ─────────────────────────────────────────────────

MEASURED = ("banned_phrase", "hard_constraint")
CONSTANT_SHARE = 0.8
MIN_SCENES = 5
HITS_SHOWN = 5


def stats(project: Project) -> list[dict]:
    """Per rule: the scenes it applies to, how many of them it fired in, and the latest hits (read from review.json).

    Banned phrases are measured on the final text of each scene and hard constraints on the continuity check;
    style rules and character voices are judged by the critic and have no count.
    """
    import json

    from . import scenefiles
    from .bible import store

    rules = load_rules(project)
    scenes = store.load_scenes(project) if store.scenes_path(project).exists() else []
    out = {r.id: {"id": r.id, "applicable": 0, "written": 0, "fired": 0, "hits": []} for r in rules}
    for s in scenes:
        raw = scenefiles.read(scenefiles.review_path(project, s.id))
        review = json.loads(raw) if raw else None
        for r in rules:
            if not applies(r, project, s):
                continue
            out[r.id]["applicable"] += 1
            if not review:
                continue
            out[r.id]["written"] += 1
            hits = []
            for issue in (review.get("final_mechanical") or {}).get("issues", []):
                if issue.get("rule") == r.id:
                    hits.append(issue.get("excerpt") or issue.get("message"))
            cont = review.get("continuity") or {}
            hits += [f.get("question") for f in cont.get("flags", []) if f.get("rule") == r.id]
            hits += [u.get("question") for u in cont.get("unsure", []) if u.get("rule") == r.id and u.get("answer") == "yes"]
            if hits:
                out[r.id]["fired"] += 1
                out[r.id]["hits"].append({"scene": s.id, "what": hits[0]})
    for v in out.values():
        v["hits"] = v["hits"][-HITS_SHOWN:]
    return [out[r.id] | {"measured": r.type in MEASURED} for r in rules]


def health(project: Project) -> list[dict]:
    """Rules that never fire, fire in almost every scene, or contradict another rule or the style samples."""
    rules = [r for r in load_rules(project) if r.enabled]
    by_id = {s["id"]: s for s in stats(project)}
    problems: list[dict] = []
    for r in rules:
        s = by_id[r.id]
        if r.type in MEASURED and s["written"] >= MIN_SCENES:
            if s["fired"] == 0:
                problems.append({"rule": r.id, "problem": "never_fires", "detail": f"it applied to {s['written']} written scenes and never fired: is it still needed, or too narrow?"})
            elif s["fired"] / s["written"] >= CONSTANT_SHARE:
                problems.append({"rule": r.id, "problem": "fires_constantly", "detail": f"it fired in {s['fired']} of {s['written']} scenes: the writer is not following it, or it is too broad"})
    phrases = [r for r in rules if r.type == "banned_phrase"]
    samples = ""
    sdir = project.root / "style" / "samples"
    for p in sorted(sdir.glob("*.md")) if sdir.is_dir() else []:
        samples += p.read_text(encoding="utf-8") + "\n"
    for r in phrases:
        rx = _banned_regex(r.phrase.strip())
        if rx is None:
            continue
        if samples and rx.search(samples):
            problems.append({"rule": r.id, "problem": "contradicts", "detail": "the phrase appears in your own sample passages, which the writer is told to match"})
        for other in rules:
            if other.id != r.id and other.example and rx.search(other.example) and other.type != "banned_phrase":
                problems.append({"rule": r.id, "problem": "contradicts", "detail": f"the phrase appears in the example of rule {other.id}"})
    seen: dict[str, str] = {}
    for r in phrases:
        key = r.phrase.strip().lower()
        if key in seen:
            problems.append({"rule": r.id, "problem": "duplicate", "detail": f"same phrase as rule {seen[key]}"})
        seen[key] = r.id
    return problems
