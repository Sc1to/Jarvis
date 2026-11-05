"""Change requests: a scene says something the plan does not, and the plan may need to follow.

When the extraction after a scene finds a gap (a tracked state the prose shows differently from the plan),
the gap is filed as a change request in `books/<book>/change-requests/cr-NNNN.yaml`: the proposing scene,
the track, what the plan says, what the prose shows, and the scenes the change would touch. Approving it adds
a plan entry to the track from that scene on (the track's version goes up), which marks the scenes that
depend on the track stale. Rejecting it means the plan stands and the scene's prose has to follow it: the
scene is then listed as stale until `stale --fix` has patched the passage.

A request whose affected scenes are all in the proposing scene's chapter is applied at once when
`qc.critic_may_accept` is `within_chapter` (the default). Anything that reaches another chapter waits for you.
"""

import logging
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

Status = Literal["pending", "applied", "rejected"]
MAX_VALUE_CHARS = 300  # PlanEntry.value limit


class ChangeError(BookforgeError):
    pass


class ChangeRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    status: Status = "pending"
    proposed_by: str  # the scene
    track: str
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


def apply(project: Project, cr: ChangeRequest, by: str) -> None:
    """Write the change into the track and mark the request applied."""
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


def open_rejections(project: Project) -> dict[str, list[ChangeRequest]]:
    """Rejected requests whose scene has not been brought back in line with the plan yet, by scene."""
    out: dict[str, list[ChangeRequest]] = {}
    for cr in list_requests(project):
        if cr.status == "rejected" and not cr.fixed:
            out.setdefault(cr.proposed_by, []).append(cr)
    return out


def paths(project: Project, crs: list[ChangeRequest]) -> list:
    return [request_path(project, c.id) for c in crs] + [project.root / "bible" / "tracks.yaml"]
