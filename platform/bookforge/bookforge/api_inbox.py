"""The Inbox routes: what stops a stage and waits for you, answered from the web page.

GET  /api/series/{s}/books/{b}/inbox          every item (questions and hard findings), blocking first, with the last run's changes and dismissal stats
POST /api/series/{s}/books/{b}/inbox/answer   {id, answer}: answer a question, or give an instruction for a finding's stage; again to edit, until a run applies it
POST /api/series/{s}/books/{b}/inbox/dismiss  {id, reason?}: a false alarm; the reason counts toward the dismissal rate of its kind
Running again is the ordinary POST .../run; approving as it is is POST .../approve/{checkpoint} (refused while blocking items remain, unless skip_open).
All writes call the same functions as the command line (bookforge/ops.py) and wait for an idle series.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import answers, canon, inbox, ops, resolve
from .project import Project

I = "/series/{series}/books/{book}/inbox"


class AnswerItem(BaseModel):
    id: str
    answer: str = Field(min_length=1, max_length=4000)


class UndoItem(BaseModel):
    id: str


class ModeBody(BaseModel):
    mode: str


class AcceptItem(BaseModel):
    id: str


class ReenableBody(BaseModel):
    outcome: str


class PolicyBody(BaseModel):
    world_facts: str = ""  # research | extrapolate | invent; empty: derive it from the realism statement


class DismissItem(BaseModel):
    id: str
    reason: str = Field("", max_length=300)


def register(router: APIRouter, h) -> None:
    def view(project) -> dict:
        return {"items": inbox.collect(project), "summary": inbox.summary(project), "last_run": inbox.last_run(project), "stats": inbox.dismissal_stats(project),
                "proposal_stats": resolve.decision_stats(project), "canon": canon.active(project), "demoted": resolve.demoted(project), "mode": answers.load(project)["mode"], "policy": answers.policy_for(project)}

    @router.get(I)
    def inbox_list(series: str, book: str):
        return h.ok(view(h.open_project(series, book)))

    @router.post(I + "/answer")
    def inbox_answer(series: str, book: str, body: AnswerItem):
        project = h.open_project(series, book)
        h.require_idle(series)
        kind, _, key = body.id.partition(":")
        resolve.record_decision(project, body.id, "answer", body.answer)
        if kind == "question":
            try:
                llm = h.make_llm()(project)
            except Exception:  # no model at hand: the answer is recorded, nothing is extracted from it
                llm = None
            ops.answer_question(project, key, body.answer, llm)
        elif kind == "finding":
            found = inbox.find_finding(project, key)
            if not found:
                raise HTTPException(404, "that finding is no longer reported")
            ops.answer_finding(project, found[0], found[1]["code"], found[1].get("items", []), body.answer)
        else:
            raise HTTPException(422, "an item id looks like question:q1 or finding:<fingerprint>")
        return h.ok(view(project))

    @router.post(I + "/dismiss")
    def inbox_dismiss(series: str, book: str, body: DismissItem):
        project = h.open_project(series, book)
        h.require_idle(series)
        kind, _, key = body.id.partition(":")
        resolve.record_decision(project, body.id, "dismiss")
        if kind == "question":
            ops.dismiss_question(project, key, body.reason)
        elif kind == "finding":
            found = inbox.find_finding(project, key)
            if not found:
                raise HTTPException(404, "that finding is no longer reported")
            ops.dismiss_finding(project, found[0], found[1]["code"], found[1].get("items", []), body.reason)
        else:
            raise HTTPException(422, "an item id looks like question:q1 or finding:<fingerprint>")
        return h.ok(view(project))

    @router.post(I + "/propose", status_code=202)
    def inbox_propose(series: str, book: str):
        """Work out what the tool would answer for the open items (a background job: it may call the model). Nothing is applied."""
        h.open_project(series, book)
        root = h.series_root(series)

        def job() -> dict:
            project = Project.open(root, book)
            made = resolve.propose_all(project, h.make_llm()(project), h.make_web(project) if h.make_web else None)
            return {"proposals": len(made)}

        return h.start_job(series, book, "propose", {}, job)

    @router.post(I + "/undo")
    def inbox_undo(series: str, book: str, body: UndoItem):
        """Take back something the tool decided: it is no longer applied and the tool leaves that sentence alone from now on."""
        project = h.open_project(series, book)
        h.require_idle(series)
        resolve.undo(project, body.id)
        return h.ok(view(project))

    @router.put(I + "/mode")
    def inbox_mode(series: str, book: str, body: ModeBody):
        """shadow: the tool only suggests. assist: it also settles housekeeping (each decision marked, with undo)."""
        project = h.open_project(series, book)
        h.require_idle(series)
        answers.set_mode(project, body.mode)
        return h.ok(view(project))

    @router.put(I + "/policy")
    def inbox_policy(series: str, book: str, body: PolicyBody):
        """How a fact about the world is answered: research (look it up), extrapolate (ground it and extend it) or invent. Empty: read it from the realism statement."""
        project = h.open_project(series, book)
        h.require_idle(series)
        answers.set_policy(project, body.world_facts)
        return h.ok(view(project))

    @router.post(I + "/canon/undo")
    def inbox_canon_undo(series: str, book: str, body: UndoItem):
        """Take back what an answer of yours introduced (its cast entries and rules)."""
        project = h.open_project(series, book)
        h.require_idle(series)
        canon.undo(project, body.id)
        return h.ok(view(project))

    @router.post(I + "/reenable")
    def inbox_reenable(series: str, book: str, body: ReenableBody):
        """Switch back on an outcome the tool stopped deciding because you kept overriding it: only decisions from now on count against it."""
        project = h.open_project(series, book)
        h.require_idle(series)
        answers.reenable(project, body.outcome)
        return h.ok(view(project))

    @router.post(I + "/accept")
    def inbox_accept(series: str, book: str, body: AcceptItem):
        """Accept the tool's housekeeping suggestion as it is (waive the sentence, or attach it to the event it elaborates)."""
        project = h.open_project(series, book)
        h.require_idle(series)
        resolve.accept(project, body.id)
        return h.ok(view(project))
