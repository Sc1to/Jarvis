"""Extraction: what the finished scene actually says about the tracked states.

After a scene is accepted the fast model reports, for every track that has a state at the scene,
what the prose shows. The answers go to the scene's extracted.yaml and into the track's `observed`
list. A track whose observed state clearly differs from the plan is a gap: reported, not blocking.
A deliberate change of plan becomes a change request (milestone 14.8). A claim of evidence that is
not in the scene is discarded, so `observed` only holds what the text supports.
"""

from dataclasses import dataclass, field

from ..bible import store
from ..bible.lookup import scene_entities, state_at
from ..bible.models import Scene
from ..errors import BookforgeError
from .support import ask_json, quote_in_page


@dataclass
class Extraction:
    observations: list[dict] = field(default_factory=list)
    gaps: list[dict] = field(default_factory=list)
    error: str | None = None


def extract_observed(ctx, scene: Scene, scenes: list[Scene], text: str) -> Extraction:
    project = ctx.project
    constants = store.load_constants(project)
    names = {e.id: e.name for e in constants.entities}
    tracks = store.load_tracks(project)
    states = state_at(tracks, scene.id, scene_entities(scenes, scene.id))
    if not states:
        return Extraction()
    by_id = {s.track_id: s for s in states}
    listing = "\n".join(f"- {s.track_id} ({names.get(s.entity, s.entity)}, {s.kind}): planned: {s.value}" for s in states)

    def check(data: dict) -> list[str]:
        obs = data.get("observations")
        if not isinstance(obs, list):
            return ["'observations' must be a list"]
        problems, seen = [], set()
        for i, o in enumerate(obs):
            if not isinstance(o, dict) or o.get("track") not in by_id:
                problems.append(f"observations[{i}].track must be one of: {', '.join(by_id)}")
                continue
            seen.add(o["track"])
            if o.get("matches_plan") not in (True, False, None):
                problems.append(f"{o['track']}: 'matches_plan' must be true, false or null")
        problems += [f"no observation for track {t}" for t in by_id if t not in seen]
        return problems

    try:
        data = ask_json(ctx, f"{scene.id} extraction", "extraction", "extract", check, max_tokens=300 + 150 * len(states),
                        text=text, tracks=listing)
    except BookforgeError as e:
        return Extraction(error=str(e))
    result = Extraction()
    for o in data["observations"]:
        evidence = " ".join(str(o.get("evidence") or "").split())
        if evidence and not quote_in_page(evidence, text):
            evidence = ""  # not in the scene: do not keep it
        matches = o.get("matches_plan")
        if matches is not None and not evidence:
            matches = None  # a verdict needs quotable support
        record = {"track": o["track"], "planned": by_id[o["track"]].value, "observed": str(o.get("observed") or "").strip(),
                  "matches_plan": matches, "evidence": evidence}
        result.observations.append(record)
        if matches is False:
            result.gaps.append(record)
    return result


def record_observed(project, scene_id: str, extraction: Extraction) -> None:
    """Write the scene's observations into the tracks (replacing any earlier ones for this scene)."""
    if not extraction.observations:
        return
    tracks = store.load_tracks(project)
    by_id = {t.id: t for t in tracks}
    for o in extraction.observations:
        t = by_id.get(o["track"])
        if t is None:
            continue
        t.observed = [x for x in t.observed if x.get("at") != scene_id]
        t.observed.append({"at": scene_id, "value": o["observed"], "matches_plan": o["matches_plan"], "evidence": o["evidence"]})
    store.save_tracks(project, tracks)
