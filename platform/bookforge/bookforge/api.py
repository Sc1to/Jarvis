"""HTTP API over the same library the command line uses (milestone 14.10).

Everything lives under /api (Caddy strips /bookforge). Responses use the platform envelope:
`{"data": ..., "status": "ok"}`, errors `{"error", "status": "error", "detail"}`.

    GET  /api/doctor                                  environment, model endpoints, web tool
    GET  /api/series                                  the series on disk
    POST /api/series                                  create one (name, premise, book)
    GET  /api/series/{s}/books/{b}/status             layers, checkpoints, scene counts, the running job
    GET  /api/series/{s}/books/{b}/scenes[/{id}]      scene list; one scene with plan, text, review
    GET  /api/series/{s}/books/{b}/report[s]          the morning report now / the saved ones
    GET  /api/series/{s}/books/{b}/manuscript         the assembled manuscript
    GET  /api/series/{s}/books/{b}/stale              what is out of date and why (changes nothing)
    GET  /api/series/{s}/books/{b}/changes            change requests
    POST /api/series/{s}/books/{b}/changes/{id}/approve|reject
    POST /api/series/{s}/books/{b}/approve/{checkpoint}
    POST /api/series/{s}/books/{b}/assemble           {partial}
    POST /api/series/{s}/books/{b}/run                {until}      -> a background job
    POST /api/series/{s}/books/{b}/stale/fix          {only, accept} -> a background job
    POST /api/series/{s}/books/{b}/bench              {only, judge, accept, force} -> a background job
    GET  /api/series/{s}/books/{b}/jobs[/{id}]
    GET  /api/series/{s}/books/{b}/structure          acts > chapters > scenes with status (the progress tree)
    GET  /api/series/{s}/books/{b}/tracks             state tracks with plan and observed, in story order
    GET  /api/series/{s}/books/{b}/research           facts with their sources and the scenes that cite them
    GET  /api/push/key, POST /api/push/subscribe|unsubscribe|test    Web Push for finished runs

A series runs one job at a time; while one is running, anything that would change the series' files
answers 409 (reads are always allowed). The model clients come from `make_llm` / `make_web`, which tests replace.
"""

import json
import logging
import re
from pathlib import Path
from typing import Callable

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import push, assemble as assembly, bench as benchmarks, changes as change_requests, ops, report as morning_report, scenefiles, stale as staleness
from .bible import store
from .constants import CHECKPOINTS, LAYER_ORDER
from .doctor import run_doctor
from .errors import BookforgeError
from .jobs import BusyError, JobManager
from .llm import build_client
from .project import BOOK_ID_RE, Project
from .research.search import build_web_client
from .research.notes import stores_for
from .state import Item

log = logging.getLogger("platform_bookforge.api")

SERIES_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
REPORT_RE = re.compile(r"^[0-9A-Za-z_-]+\.md$")

# Replaced in tests; the real clients need the colibri servers.
make_llm: Callable = build_client
make_web: Callable = lambda project: build_web_client(project) if project.config.research.enabled else None

jobs = JobManager()
push_sender: Callable | None = None  # replaced in tests; None sends for real with pywebpush


def notification_for(job) -> tuple[str, str] | None:
    """(title, body) for a job that ends in a way you should hear about, else None."""
    where = f"{job.series}/{job.book}"
    if job.status != "done":
        return f"Bookforge: {job.kind} failed", f"{where}: {job.error or job.status}"
    r = job.result or {}
    if job.kind == "run":
        if r.get("stopped") == "checkpoint":
            return "Bookforge: waiting for you", f"{where}: {r.get('detail', '').splitlines()[0] if r.get('detail') else 'a checkpoint was reached'}"
        if r.get("stopped") == "failed":
            return "Bookforge: needs you", f"{where}: {r.get('detail', 'a layer needs you')}"
        if r.get("stopped") == "complete":
            return "Bookforge: book finished", f"{where}: every layer is accepted" + (", manuscript assembled" if r.get("assembled") else "")
    if job.kind == "bench" and r.get("comparison") and not r["comparison"].get("ships"):
        return "Bookforge: benchmark loses", f"{where}: the change loses against the baseline"
    return None


def ok(data) -> dict:
    return {"data": data, "status": "ok"}


class NewSeries(BaseModel):
    name: str
    premise: str
    book: str = "b1"


class RunBody(BaseModel):
    until: str | None = None


class FixBody(BaseModel):
    only: list[str] | None = None
    accept: list[str] = Field(default_factory=list)


class BenchBody(BaseModel):
    only: list[str] | None = None
    judge: bool = True
    accept: bool = False
    force: bool = False


class PushKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscription(BaseModel):
    endpoint: str
    keys: PushKeys


class PushUnsubscribe(BaseModel):
    endpoint: str


class AssembleBody(BaseModel):
    partial: bool = False


def create_router(get_data_dir: Callable[[], str]) -> APIRouter:
    router = APIRouter(prefix="/api")

    def push_db() -> Path:
        return Path(get_data_dir()) / "push.db"

    def notify(job) -> None:
        message = notification_for(job)
        if message:
            push.send(push_db(), message[0], message[1], f"/bookforge/#/series/{job.series}/{job.book}", push_sender)

    jobs.on_finish = notify

    # ── helpers ──────────────────────────────────────────────────────────────

    def series_root(series: str) -> Path:
        if not SERIES_RE.match(series):
            raise HTTPException(404, f"no series '{series}'")
        root = Path(get_data_dir()) / series
        if not (root / "premise.md").is_file():
            raise HTTPException(404, f"no series '{series}'")
        return root

    def open_project(series: str, book: str) -> Project:
        if not BOOK_ID_RE.match(book):
            raise HTTPException(404, f"no book '{book}'")
        root = series_root(series)
        if not (root / "books" / book / "state.json").is_file():
            raise HTTPException(404, f"no book '{book}' in series '{series}'")
        return Project.open(root, book)

    def require_idle(series: str) -> None:
        job = jobs.busy(series)
        if job:
            raise HTTPException(409, f"series '{series}' is busy: {job.kind} job {job.id} is running")

    def scene_ids(project: Project) -> list[str]:
        return [s.id for s in store.load_scenes(project)] if store.scenes_path(project).exists() else []

    def start_job(series: str, book: str, kind: str, params: dict, fn: Callable[[], dict]) -> dict:
        try:
            job = jobs.start(series_root(series), series, book, kind, params, fn)
        except BusyError as e:
            raise HTTPException(409, str(e)) from e
        return ok(job.to_dict())

    # ── environment ──────────────────────────────────────────────────────────

    @router.get("/doctor")
    def doctor(offline: bool = False, series: str | None = None, book: str = "b1"):
        root = series_root(series) if series else None
        return ok([{"name": c.name, "level": c.level, "detail": c.detail} for c in run_doctor(root, book, online=not offline)])

    # ── series ───────────────────────────────────────────────────────────────

    @router.get("/series")
    def list_series():
        base = Path(get_data_dir())
        out = []
        for d in sorted(base.iterdir()) if base.is_dir() else []:
            if d.is_dir() and SERIES_RE.match(d.name) and (d / "premise.md").is_file():
                books = sorted(p.name for p in (d / "books").iterdir() if (p / "state.json").is_file()) if (d / "books").is_dir() else []
                busy = jobs.busy(d.name)
                out.append({"name": d.name, "books": books, "busy": busy.to_dict() if busy else None})
        return ok(out)

    @router.post("/series", status_code=201)
    def create_series(body: NewSeries):
        if not SERIES_RE.match(body.name):
            raise HTTPException(422, "the series name must be lowercase letters, digits, '-' or '_' (up to 64 characters)")
        root = Path(get_data_dir()) / body.name
        if root.exists():
            raise HTTPException(409, f"series '{body.name}' already exists")
        project = Project.create(root, body.premise, body.book)
        return ok({"name": body.name, "book": project.book})

    # ── a book ───────────────────────────────────────────────────────────────

    @router.get("/series/{series}/books/{book}/status")
    def book_status(series: str, book: str):
        project = open_project(series, book)
        state = project.state
        counts: dict[str, int] = {}
        ids = scene_ids(project)
        for sid in ids:
            status = state.items.get(sid, Item()).status
            counts[status] = counts.get(status, 0) + 1
        busy = jobs.busy(series)
        return ok({
            "series": series, "book": book,
            "layers": [{"name": n, "status": state.layers[n].status, "version": state.layers[n].version, "note": state.layers[n].note,
                        "checkpoint": project.config.layers[n].checkpoint} for n in LAYER_ORDER],
            "checkpoints": {n: state.checkpoints[n].status for n in CHECKPOINTS},
            "scenes": {"total": len(ids), **counts},
            "pending_changes": sum(c.status == "pending" for c in change_requests.list_requests(project)),
            "manuscript": assembly.manuscript_path(project).exists(),
            "job": busy.to_dict() if busy else None,
        })

    @router.get("/series/{series}/books/{book}/scenes")
    def scenes(series: str, book: str):
        project = open_project(series, book)
        out = []
        for s in store.load_scenes(project) if store.scenes_path(project).exists() else []:
            item = project.state.items.get(s.id, Item())
            text = scenefiles.read(scenefiles.final_path(project, s.id))
            out.append({"id": s.id, "chapter": s.chapter, "purpose": s.purpose, "status": item.status, "version": item.version,
                        "note": item.note, "words": len(text.split()) if text else 0})
        return ok(out)

    @router.get("/series/{series}/books/{book}/scenes/{scene_id}")
    def scene(series: str, book: str, scene_id: str):
        project = open_project(series, book)
        found = next((s for s in store.load_scenes(project) if s.id == scene_id), None) if store.scenes_path(project).exists() else None
        if found is None:
            raise HTTPException(404, f"no scene '{scene_id}'")
        item = project.state.items.get(scene_id, Item())
        raw = scenefiles.read(scenefiles.review_path(project, scene_id))
        try:
            review = json.loads(raw) if raw else None
        except ValueError:
            review = None
        return ok({
            "plan": found.model_dump(), "status": item.status, "version": item.version, "note": item.note,
            "text": scenefiles.best_text(project, scene_id), "summary": scenefiles.read(scenefiles.summary_path(project, scene_id)),
            "review": review,
            "drafts": {p.stem: p.read_text(encoding="utf-8") for p in sorted(scenefiles.scene_dir(project, scene_id).glob("draft-*.md"))},
            "change_requests": [c.model_dump() for c in change_requests.list_requests(project) if c.proposed_by == scene_id],
        })

    @router.get("/series/{series}/books/{book}/report")
    def report_now(series: str, book: str):
        return ok({"markdown": morning_report.build_report(open_project(series, book))})

    @router.get("/series/{series}/books/{book}/reports")
    def reports(series: str, book: str):
        project = open_project(series, book)
        d = project.book_dir / "reports"
        return ok(sorted((p.name for p in d.glob("*.md")), reverse=True) if d.is_dir() else [])

    @router.get("/series/{series}/books/{book}/reports/{name}")
    def saved_report(series: str, book: str, name: str):
        project = open_project(series, book)
        path = project.book_dir / "reports" / name
        if not REPORT_RE.match(name) or not path.is_file():
            raise HTTPException(404, f"no report '{name}'")
        return ok({"name": name, "markdown": path.read_text(encoding="utf-8")})

    @router.get("/series/{series}/books/{book}/manuscript")
    def manuscript(series: str, book: str, partial: bool = False):
        project = open_project(series, book)
        path = assembly.manuscript_path(project, partial)
        if not path.is_file():
            raise HTTPException(404, "the manuscript has not been assembled yet")
        return ok({"markdown": path.read_text(encoding="utf-8")})

    @router.get("/series/{series}/books/{book}/stale")
    def stale_list(series: str, book: str):
        report = staleness.scan(open_project(series, book))
        return ok({
            "scenes": [{"scene": s.scene, "level": s.level, "reasons": s.why()} for s in report.scenes],
            "plan": [{"id": p.id, "kind": p.kind, "reason": p.reason} for p in report.plan],
            "problems": report.problems,
        })

    @router.get("/series/{series}/books/{book}/changes")
    def changes(series: str, book: str):
        return ok([c.model_dump() for c in change_requests.list_requests(open_project(series, book))])

    # ── decisions (quick, change the files, need an idle series) ─────────────

    @router.post("/series/{series}/books/{book}/changes/{cr_id}/{decision}")
    def decide(series: str, book: str, cr_id: str, decision: str):
        if decision not in ("approve", "reject"):
            raise HTTPException(404, "expected approve or reject")
        project = open_project(series, book)
        require_idle(series)
        return ok(ops.decide_change(project, cr_id, decision == "approve").model_dump())

    @router.post("/series/{series}/books/{book}/approve/{checkpoint}")
    def approve(series: str, book: str, checkpoint: str):
        project = open_project(series, book)
        require_idle(series)
        ops.approve_checkpoint(project, checkpoint)
        return ok({"checkpoint": checkpoint, "status": "approved"})

    @router.post("/series/{series}/books/{book}/assemble")
    def assemble(series: str, book: str, body: AssembleBody | None = None):
        project = open_project(series, book)
        require_idle(series)
        result = assembly.assemble(project, bool(body and body.partial))
        return ok({"path": result.path, "words": result.words, "scenes": result.scenes, "missing": result.missing, "tag": result.tag})

    # ── long operations (background jobs) ────────────────────────────────────

    @router.post("/series/{series}/books/{book}/run", status_code=202)
    def run(series: str, book: str, body: RunBody | None = None):
        open_project(series, book)
        until = body.until if body else None
        if until is not None and until not in LAYER_ORDER:
            raise HTTPException(422, f"unknown layer '{until}' (expected one of: {', '.join(LAYER_ORDER)})")
        root = series_root(series)

        def job() -> dict:
            project = Project.open(root, book)
            out = ops.run_pipeline(project, make_llm(project), make_web(project), until)
            s = out.summary
            return {"stopped": s.stopped, "detail": s.detail, "exit_code": s.exit_code, "ran": s.ran, "notes": s.notes,
                    "assembled": vars(out.assembled) if out.assembled else None, "report": out.report_path, "report_error": out.report_error}

        return start_job(series, book, "run", {"until": until}, job)

    @router.post("/series/{series}/books/{book}/stale/fix", status_code=202)
    def stale_fix(series: str, book: str, body: FixBody | None = None):
        open_project(series, book)
        body = body or FixBody()
        root = series_root(series)

        def job() -> dict:
            project = Project.open(root, book)
            res = ops.stale_pass(project, make_llm(project), True, body.accept, set(body.only) if body.only else None)
            return {"fixes": [vars(f) for f in res.fixes],
                    "still_stale": [{"scene": s.scene, "reasons": s.why()} for s in res.report.scenes],
                    "plan": [vars(p) for p in res.report.plan], "problems": res.report.problems}

        return start_job(series, book, "stale-fix", {"only": body.only, "accept": body.accept}, job)

    @router.post("/series/{series}/books/{book}/bench", status_code=202)
    def bench(series: str, book: str, body: BenchBody | None = None):
        open_project(series, book)
        body = body or BenchBody()
        root = series_root(series)
        try:
            benchmarks.load_benchmarks(Project.open(root, book), body.only)  # a typo fails now, not after the queue
        except BookforgeError as e:
            raise HTTPException(422, str(e)) from e

        def job() -> dict:
            project = Project.open(root, book)
            out = ops.bench_pass(project, make_llm(project), body.only, body.accept, body.force, body.judge)
            return {"run": out.run.name, "results": out.run.results, "comparison": out.comparison, "accepted": out.accepted,
                    "accept_refused": out.accept_refused}

        return start_job(series, book, "bench", body.model_dump(), job)

    @router.get("/series/{series}/books/{book}/structure")
    def structure(series: str, book: str):
        project = open_project(series, book)
        acts = store.load_acts(project) if store.acts_path(project).exists() else []
        chapters = store.load_chapters(project) if store.chapters_path(project).exists() else []
        scenes_ = store.load_scenes(project) if store.scenes_path(project).exists() else []

        def scene_row(s):
            item = project.state.items.get(s.id, Item())
            return {"id": s.id, "purpose": s.purpose, "status": item.status, "note": item.note}

        def chapter_row(c):
            return {"id": c.id, "title": c.title, "tension": c.tension, "scenes": [scene_row(s) for s in scenes_ if s.chapter == c.id]}

        out = [{"id": a.id, "title": a.title, "chapters": [chapter_row(c) for c in chapters if c.act == a.id]} for a in acts]
        loose = [chapter_row(c) for c in chapters if c.act not in {a.id for a in acts}]
        if loose:
            out.append({"id": "", "title": "Chapters", "chapters": loose})
        return ok(out)

    @router.get("/series/{series}/books/{book}/tracks")
    def tracks(series: str, book: str):
        project = open_project(series, book)
        names = {e.id: e.name for e in store.load_constants(project).entities}
        order = [{"id": s.id, "chapter": s.chapter} for s in (store.load_scenes(project) if store.scenes_path(project).exists() else [])]
        out = [{"id": t.id, "entity": t.entity, "entity_name": names.get(t.entity, t.entity), "kind": t.kind, "version": t.version,
                "plan": [{"from": e.from_, "value": e.value, "must_show": e.must_show} for e in t.plan], "observed": t.observed}
               for t in store.load_tracks(project)]
        return ok({"scenes": order, "chapters": [c.id for c in (store.load_chapters(project) if store.chapters_path(project).exists() else [])], "tracks": out})

    @router.get("/series/{series}/books/{book}/research")
    def research(series: str, book: str):
        project = open_project(series, book)
        chapters = {c.id: c for c in store.load_chapters(project)} if store.chapters_path(project).exists() else {}
        cited: dict[str, list[str]] = {}
        for s in store.load_scenes(project) if store.scenes_path(project).exists() else []:
            for fid in s.research + (chapters[s.chapter].research if s.chapter in chapters else []):
                if s.id not in cited.setdefault(fid, []):
                    cited[fid].append(s.id)
        return ok([{**vars(f), "used_in": cited.get(f.id, [])} for st in stores_for(project).values() for f in st.facts()])

    @router.get("/push/key")
    def push_key():
        return ok({"public_key": push.public_key(push_db()), "subscriptions": push.subscription_count(push_db())})

    @router.post("/push/subscribe")
    def push_subscribe(body: PushSubscription):
        push.subscribe(push_db(), body.endpoint, body.keys.p256dh, body.keys.auth)
        return ok({"subscriptions": push.subscription_count(push_db())})

    @router.post("/push/unsubscribe")
    def push_unsubscribe(body: PushUnsubscribe):
        push.unsubscribe(push_db(), body.endpoint)
        return ok({"subscriptions": push.subscription_count(push_db())})

    @router.post("/push/test")
    def push_test():
        return ok({"delivered": push.send(push_db(), "Bookforge", "Notifications are working.", "/bookforge/", push_sender)})

    @router.get("/series/{series}/books/{book}/jobs")
    def job_list(series: str, book: str):
        open_project(series, book)
        return ok(jobs.list(series_root(series), series, book))

    @router.get("/series/{series}/books/{book}/jobs/{job_id}")
    def job_get(series: str, book: str, job_id: str):
        open_project(series, book)
        if not re.match(r"^[0-9a-f-]+$", job_id):
            raise HTTPException(404, f"no job '{job_id}'")
        found = jobs.get(series_root(series), series, book, job_id)
        if found is None:
            raise HTTPException(404, f"no job '{job_id}'")
        return ok(found)

    return router
