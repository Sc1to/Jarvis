"""The Inbox routes: what stops a stage and waits for you, answered from the web page.

GET  /api/series/{s}/books/{b}/inbox          every item (questions and hard findings), blocking first, with the last run's changes and dismissal stats
POST /api/series/{s}/books/{b}/inbox/answer   {id, answer}: answer a question, or give an instruction for a finding's stage; again to edit, until a run applies it
POST /api/series/{s}/books/{b}/inbox/dismiss  {id, reason?}: a false alarm; the reason counts toward the dismissal rate of its kind
Running again is the ordinary POST .../run; approving as it is is POST .../approve/{checkpoint} (refused while blocking items remain, unless skip_open).
All writes call the same functions as the command line (bookforge/ops.py) and wait for an idle series.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import inbox, ops, resolve
from .project import Project

I = "/series/{series}/books/{book}/inbox"


class AnswerItem(BaseModel):
    id: str
    answer: str = Field(min_length=1, max_length=4000)


class DismissItem(BaseModel):
    id: str
    reason: str = Field("", max_length=300)


def register(router: APIRouter, h) -> None:
    def view(project) -> dict:
        return {"items": inbox.collect(project), "summary": inbox.summary(project), "last_run": inbox.last_run(project), "stats": inbox.dismissal_stats(project),
                "proposal_stats": resolve.decision_stats(project)}

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
            ops.answer_question(project, key, body.answer)
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
            made = resolve.propose_all(project, h.make_llm()(project))
            return {"proposals": len(made)}

        return h.start_job(series, book, "propose", {}, job)
