"""HTTP API over the same library the command line uses (milestone 14.10).

Everything lives under /api (Caddy strips /bookforge). Responses use the platform envelope:
`{"data": ..., "status": "ok"}`, errors `{"error", "status": "error", "detail"}`.

    GET  /api/doctor                                  environment, model endpoints, web tool
    GET  /api/models[?series=]                        backends, loaded and available models, who uses which (model_admin.py)
    PUT  /api/series/{s}/models                       {target, base_url, model} give a role or layer another model
    GET  /api/series                                  the series on disk
    POST /api/series                                  create one (name, premise, book)
    DELETE /api/series/{s}                            move a series to the trash (restorable)
    DELETE /api/series/{s}/books/{b}                  delete a book and its entries in the shared bible files
    GET /api/trash, POST /api/trash/{name}/restore, POST /api/trash/empty
    GET  /api/series/{s}/books/{b}/status             layers, checkpoints, scene counts, the running job
    GET  /api/series/{s}/books/{b}/scenes[/{id}]      scene list; one scene with plan, text, review
    GET  /api/series/{s}/books/{b}/documents[/{key}]  the files you review (north stars, synopsis, plans, bible, style), read-only
    GET  /api/series/{s}/books/{b}/report[s]          the morning report now / the saved ones
    GET  /api/series/{s}/books/{b}/manuscript         the assembled manuscript
    GET  /api/series/{s}/books/{b}/stale              what is out of date and why (changes nothing)
    GET  /api/series/{s}/books/{b}/changes            change requests
    POST /api/series/{s}/books/{b}/changes/{id}/approve|reject|dismiss
    POST /api/series/{s}/books/{b}/approve/{checkpoint}
    POST /api/series/{s}/books/{b}/rewrite            {targets, force} scenes or a chapter to write again
    POST /api/series/{s}/books/{b}/assemble           {partial}
    POST /api/series/{s}/books/{b}/run                {until}      -> a background job
    POST /api/series/{s}/books/{b}/stale/fix          {only, accept} -> a background job
    POST /api/series/{s}/books/{b}/bench              {only, judge, accept, force} -> a background job
    POST /api/series/{s}/books/{b}/export             {formats, draft} -> a background job (Pandoc)
    GET  /api/series/{s}/books/{b}/exports[/{name}/{file}]   what was exported; download a file
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
from datetime import datetime, timezone
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import model_admin, books as book_mgmt, deletion, documents, push, assemble as assembly, export as exporting, bench as benchmarks, changes as change_requests, ops, report as morning_report, scenefiles, stale as staleness
from .bible import store
from .constants import CHECKPOINTS, LAYER_ORDER
from .doctor import run_doctor
from .errors import BookforgeError
from .jobs import BusyError, JobManager
from .llm import build_client
from .project import BOOK_ID_RE, SERIES_NAME_RE, Project
from .research.search import build_web_client
from .qc import critic as critic_mod, scene_notes
from .research.notes import stores_for, waiting_decisions
from .state import Item

log = logging.getLogger("platform_bookforge.api")

SERIES_RE = SERIES_NAME_RE
REPORT_RE = re.compile(r"^[0-9A-Za-z_-]+\.md$")
SAFE_NAME = re.compile(r"^[0-9A-Za-z][0-9A-Za-z_.-]*$")  # an export folder or file name: no slash, no leading dot

# Replaced in tests; the real clients need the colibri servers.
make_llm: Callable = build_client
make_web: Callable = lambda project: build_web_client(project) if project.config.research.enabled else None

jobs = JobManager()
push_sender: Callable | None = None  # replaced in tests; None sends for real with pywebpush


def notification_for(job) -> tuple[str, str] | None:
    """(title, body) for a job that ends in a way you should hear about, else None."""
    where = f"{job.series}/{job.book}"
    if job.status == "cancelled":
        return None  # you asked for it: no need to tell you
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


class ModelChoice(BaseModel):
    target: str  # writer | critic | research | extraction | qc | notes | layer:<name>
    base_url: str | None = None  # both empty on a layer: back to its default
    model: str | None = None


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


class ExportBody(BaseModel):
    formats: list[str] | None = None
    draft: bool = False


class NeedBody(BaseModel):
    action: str | None = None  # approve | reject; leave out to only edit
    stance: str | None = None
    rule: str | None = None
    applies_to: list[str] | None = None  # chapter or scene ids; [] = the whole book


class AddBook(BaseModel):
    title: str
    brief: str


class RenameBody(BaseModel):
    name: str


class TitleBody(BaseModel):
    title: str


class RedoBody(BaseModel):
    layer: str
    note: str = ""
    cascade: bool = False


class AcceptBody(BaseModel):
    key: str
    note: str = ""


class FindingBody(BaseModel):
    question: str
    action: str  # dismiss | instruct | clear
    text: str = ""


class DocBody(BaseModel):
    text: str


class RewriteBody(BaseModel):
    targets: list[str]  # scene ids, chapter ids, or "all"
    force: bool = False
    reset_voice: bool = False  # ask for the voice checkpoint again (when chapter 1 is rewritten)


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
        # The first job for a series after another series (or after a restart) starts on freshly loaded models: a model
        # that stayed loaded answered one series with the other's story. Same series again: nothing to reset.
        switched = jobs.last_series != series

        def run_clean() -> dict:
            if switched:
                from .config import load_config
                try:
                    model_admin.unload_all(load_config(series_root(series)))
                except Exception:  # a failed unload must not stop the run
                    log.warning("could not unload models before the job", exc_info=True)
            return fn()

        try:
            job = jobs.start(series_root(series), series, book, kind, params, run_clean)
        except BusyError as e:
            raise HTTPException(409, str(e)) from e
        return ok(job.to_dict())

    # ── environment ──────────────────────────────────────────────────────────

    @router.get("/doctor")
    def doctor(offline: bool = False, series: str | None = None, book: str = "b1"):
        root = series_root(series) if series else None
        return ok([{"name": c.name, "level": c.level, "detail": c.detail} for c in run_doctor(root, book, online=not offline)])

    # ── models ───────────────────────────────────────────────────────────────

    @router.get("/models")
    def models(series: str | None = None):
        from .config import load_config
        return ok(model_admin.overview(load_config(series_root(series) if series else None)))

    @router.put("/series/{series}/models")
    def choose_model(series: str, body: ModelChoice):
        root = series_root(series)
        require_idle(series)  # a model unloaded under a running job would fail its next call
        return ok(model_admin.choose(root, body.target, body.base_url, body.model))

    # ── series ───────────────────────────────────────────────────────────────

    @router.get("/series")
    def list_series():
        base = Path(get_data_dir())
        out = []
        for d in sorted(base.iterdir()) if base.is_dir() else []:
            if d.is_dir() and SERIES_RE.match(d.name) and (d / "premise.md").is_file():
                books = sorted(p.name for p in (d / "books").iterdir() if (p / "state.json").is_file()) if (d / "books").is_dir() else []
                busy = jobs.busy(d.name)
                out.append({"name": d.name, "books": books, "titles": book_mgmt.titles(d), "busy": busy.to_dict() if busy else None})
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

    @router.post("/series/{series}/rename")
    def rename_series(series: str, body: RenameBody):
        series_root(series)
        require_idle(series)
        dest = book_mgmt.rename_series(Path(get_data_dir()), series, body.name)
        return ok({"name": dest.name})

    @router.post("/series/{series}/books", status_code=201)
    def add_book(series: str, body: AddBook):
        root = series_root(series)
        require_idle(series)
        project = book_mgmt.add_book(root, body.title, body.brief)
        return ok({"book": project.book, "title": project.state.title})

    @router.delete("/series/{series}")
    def delete_series(series: str):
        series_root(series)
        require_idle(series)
        dest = deletion.trash_series(Path(get_data_dir()), series)
        return ok({"series": series, "trash": dest.name})

    @router.get("/trash")
    def trash_list():
        return ok(deletion.list_trash(Path(get_data_dir())))

    @router.post("/trash/empty")
    def trash_empty():
        return ok({"removed": deletion.empty_trash(Path(get_data_dir()))})

    @router.post("/trash/{name}/restore")
    def trash_restore(name: str):
        if not SAFE_NAME.match(name):
            raise HTTPException(404, "nothing in the trash with that name")
        return ok({"series": deletion.restore(Path(get_data_dir()), name)})

    # ── a book ───────────────────────────────────────────────────────────────

    @router.delete("/series/{series}/books/{book}")
    def delete_book(series: str, book: str):
        open_project(series, book)
        require_idle(series)
        return ok(deletion.delete_book(series_root(series), book))

    @router.put("/series/{series}/books/{book}/title")
    def set_title(series: str, book: str, body: TitleBody):
        project = open_project(series, book)
        require_idle(series)
        return ok({"title": book_mgmt.set_title(project, body.title)})

    @router.get("/series/{series}/books/{book}/redo/{layer}")
    def redo_plan(series: str, book: str, layer: str):
        project = open_project(series, book)
        return ok({"layer": layer, "also_resets": ops.redo_plan(project, layer)})

    @router.post("/series/{series}/books/{book}/redo")
    def redo(series: str, book: str, body: RedoBody):
        project = open_project(series, book)
        require_idle(series)
        return ok(ops.redo_layer(project, body.layer, body.note, body.cascade))

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
            "title": project.state.title,
            "server_time": datetime.now(timezone.utc).isoformat(timespec="seconds"),  # so the page can time a call without trusting its own clock
            "pending_changes": sum(c.status == "pending" for c in change_requests.list_requests(project)),
            "pending_needs": len(waiting_decisions(project)),
            "manuscript": assembly.manuscript_path(project).exists(),
            "job": busy.to_dict() if busy else None,
            "resume": ops.resume_point(project), "resume_text": ops.resume_text(ops.resume_point(project)),
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
            "findings": scene_notes.read(project, scene_id),
            "critic_min_score": project.config.qc.critic_min_score,
            "reasons": ops.flag_reasons(project, scene_id) if item.status == "flagged" else [],
            "rubric": {c: critic_mod.rubric_line(project, c) for c in critic_mod.CRITERIA},
            "drafts": {p.stem: p.read_text(encoding="utf-8") for p in sorted(scenefiles.scene_dir(project, scene_id).glob("draft-*.md"))},
            "change_requests": [c.model_dump() for c in change_requests.list_requests(project) if c.proposed_by == scene_id],
        })

    @router.post("/series/{series}/books/{book}/scenes/{scene_id}/accept-reason")
    def accept_reason(series: str, book: str, scene_id: str, body: AcceptBody):
        project = open_project(series, book)
        require_idle(series)
        return ok(ops.accept_reason(project, scene_id, body.key, body.note))

    @router.delete("/series/{series}/books/{book}/scenes/{scene_id}/accept-reason")
    def undo_accept_reason(series: str, book: str, scene_id: str, key: str = Query(...)):
        project = open_project(series, book)
        require_idle(series)
        ops.undo_accept_reason(project, scene_id, key)
        return ok({"scene": scene_id, "key": key, "accepted": False})

    @router.post("/series/{series}/books/{book}/scenes/{scene_id}/findings")
    def scene_finding(series: str, book: str, scene_id: str, body: FindingBody):
        project = open_project(series, book)
        require_idle(series)
        return ok(ops.decide_finding(project, scene_id, body.question, body.action, body.text))

    @router.get("/series/{series}/books/{book}/documents")
    def document_list(series: str, book: str):
        project = open_project(series, book)
        out = []
        for d in documents.catalog(project):
            text, _ = documents.read(d) if d.exists else ("", False)
            out.append({"key": d.key, "title": d.title, "group": d.group, "kind": d.kind, "exists": d.exists, "words": len(text.split()),
                        "editable": documents.editable(d)})
        return ok(out)

    @router.get("/series/{series}/books/{book}/documents/{key}")
    def document_get(series: str, book: str, key: str):
        project = open_project(series, book)
        doc = documents.find(project, key)
        if doc is None:
            raise HTTPException(404, f"no document '{key}'")
        text, truncated = documents.read(doc)
        return ok({"key": doc.key, "title": doc.title, "group": doc.group, "kind": doc.kind, "exists": doc.exists, "text": text, "truncated": truncated,
                    "editable": documents.editable(doc)})

    @router.put("/series/{series}/books/{book}/documents/{key}")
    def document_save(series: str, book: str, key: str, body: DocBody):
        project = open_project(series, book)
        doc = documents.find(project, key)
        if doc is None:
            raise HTTPException(404, f"no document '{key}'")
        require_idle(series)
        documents.save(project, doc, body.text)
        return ok({"key": doc.key, "saved": True})

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

    @router.get("/series/{series}/books/{book}/needs")
    def needs(series: str, book: str):
        return ok([{"scope": scope, **asdict(n)} for scope, n in ops.list_needs(open_project(series, book))])

    # ── decisions (quick, change the files, need an idle series) ─────────────

    @router.post("/series/{series}/books/{book}/needs/{need_id}")
    def decide_need(series: str, book: str, need_id: str, body: NeedBody):
        project = open_project(series, book)
        require_idle(series)
        if body.action not in (None, "approve", "reject"):
            raise HTTPException(422, "action must be approve or reject")
        approve = None if body.action is None else body.action == "approve"
        return ok(asdict(ops.decide_need(project, need_id, approve, body.stance, body.rule, body.applies_to)))

    @router.post("/series/{series}/books/{book}/changes/{cr_id}/{decision}")
    def decide(series: str, book: str, cr_id: str, decision: str):
        if decision not in ("approve", "reject", "dismiss"):
            raise HTTPException(404, "expected approve, reject or dismiss")
        project = open_project(series, book)
        require_idle(series)
        return ok(ops.decide_change(project, cr_id, decision == "approve", dismiss=decision == "dismiss").model_dump())

    @router.post("/series/{series}/books/{book}/approve/{checkpoint}")
    def approve(series: str, book: str, checkpoint: str):
        project = open_project(series, book)
        require_idle(series)
        ops.approve_checkpoint(project, checkpoint)
        return ok({"checkpoint": checkpoint, "status": "approved"})

    @router.post("/series/{series}/books/{book}/rewrite")
    def rewrite(series: str, book: str, body: RewriteBody):
        project = open_project(series, book)
        require_idle(series)
        return ok(ops.rewrite_scenes(project, body.targets, body.force, body.reset_voice))

    @router.get("/series/{series}/books/{book}/rewrite-plan")
    def rewrite_preview(series: str, book: str, targets: list[str] = Query(...), force: bool = False):
        return ok(ops.rewrite_plan(open_project(series, book), targets, force))

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

    @router.post("/series/{series}/books/{book}/export", status_code=202)
    def export(series: str, book: str, body: ExportBody | None = None):
        open_project(series, book)
        body = body or ExportBody()
        bad = [f for f in body.formats or [] if f not in exporting.FORMATS]
        if bad:
            raise HTTPException(422, f"unknown format {', '.join(bad)} (expected: {', '.join(exporting.FORMATS)})")
        root = series_root(series)

        def job() -> dict:
            r = exporting.export_book(Project.open(root, book), body.formats, body.draft)
            return {"name": r.name, "tag": r.tag, "files": r.files, "skipped": r.skipped, "warnings": r.warnings, "draft": r.draft}

        return start_job(series, book, "export", body.model_dump(), job)

    @router.get("/series/{series}/books/{book}/exports")
    def exports(series: str, book: str):
        return ok(exporting.list_exports(open_project(series, book)))

    @router.get("/series/{series}/books/{book}/exports/{name}/{filename}")
    def export_file(series: str, book: str, name: str, filename: str):
        project = open_project(series, book)
        if not (SAFE_NAME.match(name) and SAFE_NAME.match(filename)):
            raise HTTPException(404, "no such file")
        path = project.book_dir / "exports" / name / filename
        if not path.is_file() or path.name == "export.json":
            raise HTTPException(404, "no such file")
        return FileResponse(path, filename=filename)

    @router.get("/series/{series}/books/{book}/jobs")
    def job_list(series: str, book: str):
        open_project(series, book)
        return ok(jobs.list(series_root(series), series, book))

    @router.post("/series/{series}/books/{book}/jobs/{job_id}/cancel")
    def job_cancel(series: str, book: str, job_id: str):
        open_project(series, book)
        return ok(jobs.cancel(series_root(series), series, job_id).to_dict())

    @router.get("/series/{series}/books/{book}/jobs/{job_id}")
    def job_get(series: str, book: str, job_id: str):
        open_project(series, book)
        if not re.match(r"^[0-9a-f-]+$", job_id):
            raise HTTPException(404, f"no job '{job_id}'")
        found = jobs.get(series_root(series), series, book, job_id)
        if found is None:
            raise HTTPException(404, f"no job '{job_id}'")
        return ok(found)

    from . import api_workbench
    api_workbench.register(router, api_workbench.Helpers(open_project, series_root, require_idle, start_job, lambda: make_llm, ok))

    return router
