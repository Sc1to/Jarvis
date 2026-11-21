"""Change requests: a scene says something the plan does not, and the plan may need to follow.

When the extraction after a scene finds a gap (a tracked state the prose shows differently from the plan),
the gap is filed as a change request in `books/<book>/change-requests/cr-NNNN.yaml`: the proposing scene,
the track, what the plan says, what the prose shows, and the scenes the change would touch. Approving it adds
a plan entry to the track from that scene on (the track's version goes up), which marks the scenes that
depend on the track stale. Rejecting it means the plan stands and the scene's prose has to follow it: the
scene is then listed as stale until `stale --fix` has patched the passage. Dismissing it means the difference is
not worth a decision: the prose stays as written, the plan stays as planned, and nothing is marked stale. (The request
is kept, so the same scene and track are not proposed again.)

A request whose affected scenes are all in the proposing scene's chapter is applied at once when
`qc.critic_may_accept` is `within_chapter` (the default). Anything that reaches another chapter waits for you.
"""

import logging
import re
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from .bible import store
from .bible.lookup import state_at
from .bible.models import PlanEntry, Scene, Track
from .bible.positions import parse_position
from .errors import BookforgeError
from .project import Project
from .state import now

log = logging.getLogger("platform_bookforge.changes")

Status = Literal["pending", "applied", "rejected", "dismissed"]
MAX_VALUE_CHARS = 300  # PlanEntry.value limit


class ChangeError(BookforgeError):
    pass


class ChangeRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    status: Status = "pending"
    kind: Literal["state", "entity", "event"] = "state"  # a tracked state differs from the plan | the prose brings in a new person, place or thing | a development no beat contains
    proposal: dict = {}  # entity: {id, name, entity_kind, facts, same_as}; event: {text}
    proposed_by: str  # the scene
    track: str = ""
    entity: str = ""
    reason: str
    planned: str  # what the plan says
    observed: str  # what the prose shows (and the new plan value if applied)
    evidence: str = ""  # a quotation from the scene
    affects: list[str] = []  # scenes whose state for this track would change, the proposer included
    scope: Literal["within_chapter", "later_chapters"] = "within_chapter"
    created: str = ""
    decided: str | None = None
    decided_by: str | None = None  # auto | author
    fixed: bool = False  # rejected, and the scene's prose has since been brought back in line with the plan

    def message(self) -> str:
        if self.kind == "entity":
            return (f"the scene brings in {self.observed}, who or which is not in the plan or the cast: take them out, or use someone or something that is already in the cast")
        if self.kind == "event":
            return f"the scene tells something the plan does not contain ({self.observed}): leave it out, so the scene tells only its planned beats"
        return (f"the scene shows '{self.observed}' but the plan for {self.entity or self.track} says '{self.planned}': "
                f"make the passage agree with the plan")


def change_dir(project: Project):
    return project.book_dir / "change-requests"


def request_path(project: Project, cr_id: str):
    return change_dir(project) / f"{cr_id}.yaml"


def save(project: Project, cr: ChangeRequest) -> None:
    path = request_path(project, cr.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(cr.model_dump(), sort_keys=False, allow_unicode=True, width=100), encoding="utf-8")


def list_requests(project: Project) -> list[ChangeRequest]:
    out = []
    for p in sorted(change_dir(project).glob("cr-*.yaml")):
        try:
            out.append(ChangeRequest.model_validate(yaml.safe_load(p.read_text(encoding="utf-8"))))
        except (OSError, yaml.YAMLError, ValidationError) as e:
            raise ChangeError(f"{p} is not a valid change request: {e}") from e
    return out


def get(project: Project, cr_id: str) -> ChangeRequest:
    for cr in list_requests(project):
        if cr.id == cr_id:
            return cr
    raise ChangeError(f"no change request '{cr_id}' (see `changes`)")


def _next_id(existing: list[ChangeRequest]) -> str:
    n = max((int(c.id.split("-")[1]) for c in existing if c.id.split("-")[-1].isdigit()), default=0)
    return f"cr-{n + 1:04d}"


def _with_entry(tracks: list[Track], track_id: str, at: str, value: str) -> list[Track]:
    """A copy of the tracks with a plan entry from `at` (replacing one that starts there)."""
    out = [t.model_copy(deep=True) for t in tracks]
    track = next((t for t in out if t.id == track_id), None)
    if track is None:
        raise ChangeError(f"the track '{track_id}' no longer exists")
    entries = {e.from_: e for e in track.plan}
    entries[at] = PlanEntry(**{"from": at, "value": value[:MAX_VALUE_CHARS], "must_show": False})
    track.plan = sorted(entries.values(), key=lambda e: parse_position(e.from_).key)
    track.version += 1
    return out


def affected_scenes(tracks: list[Track], scenes: list[Scene], track_id: str, at: str, value: str) -> list[str]:
    """Scenes from `at` on whose state for the track would differ if the plan followed `value` from `at`."""
    after = _with_entry(tracks, track_id, at, value)
    start = parse_position(at).key
    out = []
    for s in scenes:
        if parse_position(s.id).key < start:
            continue
        a = [x.value for x in state_at(tracks, s.id) if x.track_id == track_id]
        b = [x.value for x in state_at(after, s.id) if x.track_id == track_id]
        if a != b:
            out.append(s.id)
    return out


def _apply_entity(project: Project, cr: ChangeRequest) -> None:
    from . import cast
    p = cr.proposal
    if p.get("same_as"):
        return  # it was another name for someone who is in the cast already: nothing to add
    eid = p.get("id") or re.sub(r"[^a-z0-9]+", "-", cr.observed.lower()).strip("-")
    if not any(e.id == eid for e in store.load_constants(project).entities):
        cast.add(project, eid, p.get("entity_kind", "character"), p.get("name") or cr.observed, list(p.get("facts") or []) or [cr.evidence[:240] or "Introduced by a scene."])


def _apply_event(project: Project, cr: ChangeRequest) -> None:
    from . import intake
    scene = next(s for s in store.load_scenes(project) if s.id == cr.proposed_by)
    chapter = next(c for c in store.load_chapters(project) if c.id == scene.chapter)
    ledger = store.active_ledger(project)
    by_id = {e.id: e for e in ledger.events} if ledger else {}
    parents = [x for x in chapter.events_covered if x in by_id and not by_id[x].parent]
    if not parents:
        raise ChangeError("this chapter tells no event of its own that a complication could belong to: redo the ledger instead")
    added = intake.register_events(project, [{"scene": scene.id, "parent": parents[-1], "text": cr.proposal.get("text") or cr.observed}])
    cr.proposal = {**cr.proposal, "event_id": added[0]}  # so an undo knows which event this was


def apply(project: Project, cr: ChangeRequest, by: str) -> None:
    """Write the change (a track entry, a cast entry, or a registered development) and mark the request applied."""
    if cr.kind == "entity":
        _apply_entity(project, cr)
        cr.status, cr.decided, cr.decided_by = "applied", now(), by
        save(project, cr)
        return
    if cr.kind == "event":
        _apply_event(project, cr)
        cr.status, cr.decided, cr.decided_by = "applied", now(), by
        save(project, cr)
        return
    tracks = store.load_tracks(project)
    store.save_tracks(project, _with_entry(tracks, cr.track, cr.proposed_by, cr.observed))
    cr.status, cr.decided, cr.decided_by = "applied", now(), by
    save(project, cr)


def file_gaps(project: Project, scene: Scene, scenes: list[Scene], gaps: list[dict]) -> list[ChangeRequest]:
    """File a change request for each gap that has none yet. Returns the requests created (applied ones included)."""
    existing = list_requests(project)
    tracks = store.load_tracks(project)
    by_id = {t.id: t for t in tracks}
    rule = project.config.qc.critic_may_accept
    created: list[ChangeRequest] = []
    for gap in gaps:
        track = by_id.get(gap["track"])
        observed = " ".join(str(gap.get("observed") or "").split())[:MAX_VALUE_CHARS]
        if track is None or not observed:
            continue
        if any(c.proposed_by == scene.id and c.track == track.id for c in existing + created):
            continue  # one request per scene and track; a decided one is not reopened
        affects = affected_scenes(tracks, scenes, track.id, scene.id, observed)
        scope = "within_chapter" if all(s.rsplit(".", 1)[0] == scene.chapter for s in affects) else "later_chapters"
        cr = ChangeRequest(
            id=_next_id(existing + created), proposed_by=scene.id, track=track.id, entity=track.entity,
            reason="the prose shows something different from the plan", planned=str(gap.get("planned") or ""),
            observed=observed, evidence=str(gap.get("evidence") or ""), affects=affects, scope=scope, created=now())
        save(project, cr)
        if rule == "within_chapter" and scope == "within_chapter":
            apply(project, cr, "auto")
            tracks = store.load_tracks(project)
            by_id = {t.id: t for t in tracks}
        created.append(cr)
    return created


def file_new(project: Project, scene: Scene, found: list[dict]) -> list[ChangeRequest]:
    """File a change request for each new entity or event the prose brought in (never applied by itself: they change the cast and the ledger). One per scene and thing;
    a name already decided or waiting (by any scene) is not proposed again."""
    existing = list_requests(project)
    created: list[ChangeRequest] = []
    for item in found:
        if item["kind"] == "entity":
            name = item["name"]
            if any(c.kind == "entity" and c.observed.lower() == name.lower() for c in existing + created):
                continue
            eid = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
            cr = ChangeRequest(id=_next_id(existing + created), kind="entity", proposed_by=scene.id, entity=eid,
                               reason="the prose introduces a person, place or thing the cast does not have",
                               planned="(not in the cast)", observed=name, evidence=item["quote"], created=now(),
                               proposal={"id": eid, "name": name, "entity_kind": item["entity_kind"], "facts": item["facts"], "same_as": item["same_as"]})
        else:
            if any(c.kind == "event" and c.proposed_by == scene.id and c.observed == item["text"] for c in existing + created):
                continue
            cr = ChangeRequest(id=_next_id(existing + created), kind="event", proposed_by=scene.id, reason="the prose tells a development no beat contains",
                               planned="(not in the plan)", observed=item["text"], evidence=item["quote"], created=now(), proposal={"text": item["text"]})
        save(project, cr)
        _settle_as_tool(project, cr, item)
        created.append(cr)
    return created


OUTCOME = {"entity": "intake_entity", "event": "intake_event"}
_AUTO_KINDS = ("character", "place", "object")


def _tool_may_apply(project: Project, cr: ChangeRequest, item: dict) -> bool:
    """The book's mode and the outcome's record decide whether the tool applies a request it has just filed: assist settles a verified new cast entry (or an alias),
    auto also registers a minor development; an outcome you keep overriding is only suggested."""
    from . import answers, resolve
    mode = answers.load(project)["mode"]
    if mode == "shadow" or OUTCOME[cr.kind] in resolve.demoted(project):
        return False
    if cr.kind == "event":
        return mode == "auto"
    if item.get("same_as"):
        return True  # another name for someone in the cast: nothing to add
    if item.get("entity_kind") not in _AUTO_KINDS or not item.get("quote") or not item.get("facts"):
        return False
    toks = {t for t in re.split(r"[^a-z0-9]+", cr.observed.lower()) if len(t) >= 3}
    for e in store.load_constants(project).entities:
        if toks & {t for t in re.split(r"[^a-z0-9]+", (e.id + " " + e.name).lower()) if len(t) >= 3}:
            return False  # a name that overlaps an entity already in the cast may be another name for it: yours to say
    return True


def _settle_as_tool(project: Project, cr: ChangeRequest, item: dict) -> None:
    from . import resolve
    if not _tool_may_apply(project, cr, item):
        return
    try:
        apply(project, cr, "tool")
    except BookforgeError as e:  # a cast or ledger check refused it: it waits for you, with the reason
        cr.reason = f"{cr.reason} (the tool tried to apply it and could not: {e})"
        save(project, cr)
        log.info("%s not applied by the tool: %s", cr.id, e)
        return
    resolve.log_outcome(project, cr.id, OUTCOME[cr.kind], "applied", "tool decision")


def undo(project: Project, cr_id: str) -> ChangeRequest:
    """Take back what the tool applied: the cast entry or the registered development goes, and the request is yours to decide again."""
    from . import intake, resolve
    cr = get(project, cr_id)
    if cr.status != "applied" or cr.decided_by != "tool" or cr.kind not in OUTCOME:
        raise ChangeError(f"{cr_id} was not applied by the tool")
    try:
        if cr.kind == "entity" and not cr.proposal.get("same_as"):
            from . import cast
            cast.delete(project, cr.proposal.get("id") or cr.entity)
        elif cr.kind == "event":
            intake.unregister_event(project, cr.proposal.get("event_id", ""))
    except BookforgeError as e:
        raise ChangeError(f"cannot take {cr_id} back: {e}") from e
    cr.proposal = {k: v for k, v in cr.proposal.items() if k != "event_id"}
    cr.status, cr.decided, cr.decided_by = "pending", None, None
    save(project, cr)
    resolve.log_outcome(project, cr.id, OUTCOME[cr.kind], "undone", "tool decision")
    return cr


def impact(project: Project, cr: ChangeRequest) -> list[str]:
    """What approving this request changes, in plain lines (no model): shown before you press the button, and kept as the record of what the tool did."""
    if cr.kind == "entity":
        p = cr.proposal
        if p.get("same_as"):
            return [f"{p.get('name') or cr.observed} is another name for {p['same_as']}: nothing is added to the cast"]
        facts = "; ".join(p.get("facts") or [])
        return [f"Add {p.get('name') or cr.observed} ({p.get('entity_kind', 'character')}) to the cast" + (f", fixed facts: {facts}" if facts else ""),
                f"Scenes that name {p.get('name') or cr.observed} become consistent with the cast"]
    if cr.kind == "event":
        try:
            scene = next(s for s in store.load_scenes(project) if s.id == cr.proposed_by)
            chapter = next(c for c in store.load_chapters(project) if c.id == scene.chapter)
            ledger = store.active_ledger(project)
            by_id = {e.id: e for e in ledger.events} if ledger else {}
            parents = [x for x in chapter.events_covered if x in by_id and not by_id[x].parent]
        except StopIteration:
            return []
        built = sum(1 for s in store.load_scenes(project) if s.chapter == chapter.id and project.state.items.get(s.id) and project.state.items[s.id].status in ("accepted", "checked", "drafted"))
        return ([f"Register a minor complication under {parents[-1]}: {cr.proposal.get('text') or cr.observed}"] if parents else ["This chapter has no event of its own to attach it to: redo the ledger instead"]) + \
               [f"Added to {chapter.id} and {scene.id}, so the ledger checks cover it"] + ([f"{built} written scene(s) of {chapter.id} were built on the old plan and will be marked out of date"] if built else [])
    return [f"{len(cr.affects)} scene(s) from {cr.proposed_by} on get '{cr.observed}' for {cr.entity or cr.track}"]


def approve(project: Project, cr_id: str) -> ChangeRequest:
    cr = get(project, cr_id)
    if cr.status != "pending":
        raise ChangeError(f"{cr_id} is already {cr.status}")
    apply(project, cr, "author")
    return cr


def reject(project: Project, cr_id: str) -> ChangeRequest:
    cr = get(project, cr_id)
    if cr.status != "pending":
        raise ChangeError(f"{cr_id} is already {cr.status}")
    cr.status, cr.decided, cr.decided_by = "rejected", now(), "author"
    save(project, cr)
    return cr


def dismiss(project: Project, cr_id: str) -> ChangeRequest:
    """Accept the prose as it is and leave the plan alone: the difference does not matter."""
    cr = get(project, cr_id)
    if cr.status != "pending":
        raise ChangeError(f"{cr_id} is already {cr.status}")
    cr.status, cr.decided, cr.decided_by = "dismissed", now(), "author"
    save(project, cr)
    return cr


def open_rejections(project: Project) -> dict[str, list[ChangeRequest]]:
    """Rejected requests whose scene has not been brought back in line with the plan yet, by scene."""
    out: dict[str, list[ChangeRequest]] = {}
    for cr in list_requests(project):
        if cr.status == "rejected" and not cr.fixed:
            out.setdefault(cr.proposed_by, []).append(cr)
    return out


def paths(project: Project, crs: list[ChangeRequest]) -> list:
    return [request_path(project, c.id) for c in crs] + [store.tracks_path(project)]
