"""The workbench's routes (milestone 14.13), added to the same router as the rest of the API.

All under /api/series/{s}/books/{b}/workbench. What needs a model (testing a rule, proposing a rule from a comment,
the beat check of the X-ray, A/B tests) is a background job like a run: the result is in the job. Everything else
answers at once. Anything that writes needs an idle series (409 otherwise), like the other changes.
"""

from typing import Callable

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import ab, arc, calibration, milestones, rules, rules_ai, studio, xray
from .layers.runner import StepContext
from .project import Project

W = "/series/{series}/books/{book}/workbench"


class Helpers:
    """What the router needs from api.py (kept as plain callables so this module does not import it)."""

    def __init__(self, open_project: Callable, series_root: Callable, require_idle: Callable, start_job: Callable,
                 make_llm: Callable, ok: Callable, make_web: Callable | None = None):
        self.open_project, self.series_root, self.require_idle, self.start_job = open_project, series_root, require_idle, start_job
        self.make_llm, self.ok, self.make_web = make_llm, ok, make_web


class TestRuleBody(BaseModel):
    rule: rules.Rule


class ProposeBody(BaseModel):
    scene: str
    passage: str
    comment: str


class XrayBody(BaseModel):
    beats: bool = True


class AnswerBody(BaseModel):
    answer: str = Field(min_length=1, max_length=4000)


class StyleSuggestBody(BaseModel):
    replace: bool = False  # replace the guide you have (it is committed first)


class AcceptBody(BaseModel):
    stage: str
    code: str
    items: list[str] = []
    message: str = ""


class UnacceptBody(BaseModel):
    fingerprint: str


class PromptBody(BaseModel):
    text: str


class ABBody(BaseModel):
    template: str
    candidate: str
    only: list[str] | None = None
    judge: bool = True


class VoteBody(BaseModel):
    benchmark: str
    choice: str


class ScoresBody(BaseModel):
    scores: dict[str, int]


class TensionBody(BaseModel):
    chapter: str
    value: int
    apply: bool = False


class ThreadBody(BaseModel):
    note: str = ""
    setup: str
    payoff: str = ""


def register(router: APIRouter, h: Helpers) -> None:
    def job_ctx(root, book: str, make_llm: Callable) -> tuple[Project, StepContext]:
        project = Project.open(root, book)
        return project, StepContext(project=project, layer="prose", llm=make_llm(project))

    # ── rules ────────────────────────────────────────────────────────────────

    @router.get(W + "/rules")
    def rules_list(series: str, book: str):
        p = h.open_project(series, book)
        return h.ok({"rules": [r.model_dump() for r in rules.load_rules(p)], "stats": rules.stats(p), "health": rules.health(p)})

    @router.put(W + "/rules/{rule_id}")
    def rules_save(series: str, book: str, rule_id: str, rule: rules.Rule):
        p = h.open_project(series, book)
        if rule.id != rule_id:
            raise HTTPException(422, "the rule's id must match the address")
        h.require_idle(series)
        return h.ok(rules.upsert(p, rule).model_dump())

    @router.delete(W + "/rules/{rule_id}")
    def rules_delete(series: str, book: str, rule_id: str):
        p = h.open_project(series, book)
        h.require_idle(series)
        rules.delete(p, rule_id)
        return h.ok({"deleted": rule_id})

    @router.post(W + "/rules-test", status_code=202)
    def rules_test(series: str, book: str, body: TestRuleBody):
        h.open_project(series, book)
        root = h.series_root(series)

        def job() -> dict:
            _, ctx = job_ctx(root, book, h.make_llm())
            return rules_ai.test_rule(ctx, body.rule)

        return h.start_job(series, book, "rule-test", {"rule": body.rule.id}, job)

    @router.post(W + "/rules-propose", status_code=202)
    def rules_propose(series: str, book: str, body: ProposeBody):
        h.open_project(series, book)
        root = h.series_root(series)

        def job() -> dict:
            _, ctx = job_ctx(root, book, h.make_llm())
            return rules_ai.propose_rule(ctx, body.scene, body.passage, body.comment)

        return h.start_job(series, book, "rule-propose", {"scene": body.scene}, job)

    # ── the suggested style guide ────────────────────────────────────────────

    S = "/series/{series}/books/{book}/style"

    @router.get(S)
    def style_state(series: str, book: str):
        """What the last style suggestion was based on (genre, checked titles, sources), and whether the series has a guide of its own."""
        from . import style
        p = h.open_project(series, book)
        return h.ok({"has_guide": not style.guide_is_empty(p), "suggestion": style.load_suggestion(p)})

    @router.post(S + "/suggest", status_code=202)
    def style_suggest(series: str, book: str, body: StyleSuggestBody):
        """Suggest a style guide (a background job: it searches the web and reads pages). A guide you have is kept unless `replace`."""
        from . import style
        h.open_project(series, book)
        root = h.series_root(series)

        def job() -> dict:
            project = Project.open(root, book)
            web = h.make_web(project) if h.make_web else None
            ctx = StepContext(project=project, layer="synopsis", llm=h.make_llm()(project), web=web)
            s = style.suggest_style_guide(ctx, web, body.replace)
            return {"file": s.path, "words": s.words, "verified": s.verified, "web": s.web, "problems": s.problems}

        return h.start_job(series, book, "style-suggest", {"replace": body.replace}, job)

    # ── stage checks and the ledger ──────────────────────────────────────────

    @router.get(W + "/validation")
    def validation(series: str, book: str):
        """What the validators found at each planning stage and in the prose, as saved by the last run of that stage."""
        from .validators import store as findings_store
        p = h.open_project(series, book)
        from .validators import accepted
        return h.ok({"stages": {st: findings_store.load(p, st) for st in ("ledger", "acts", "chapters", "scenes", "prose")},
                     "accepted": [{"fingerprint": fp, **rec} for fp, rec in accepted.load(p).items()]})

    @router.post(W + "/validation/accept")
    def validation_accept(series: str, book: str, body: AcceptBody):
        """Accept a hard finding you judge to be a false alarm: it stays in the report, marked accepted, and stops blocking the stage."""
        from .validators import accepted
        p = h.open_project(series, book)
        h.require_idle(series)
        if body.stage not in ("ledger", "acts", "chapters", "scenes", "prose"):
            raise HTTPException(422, "unknown stage")
        return h.ok({"fingerprint": accepted.accept(p, body.stage, body.code, body.items, body.message)})

    @router.post(W + "/validation/unaccept")
    def validation_unaccept(series: str, book: str, body: UnacceptBody):
        from .validators import accepted
        p = h.open_project(series, book)
        h.require_idle(series)
        if not accepted.unaccept(p, body.fingerprint):
            raise HTTPException(404, "that finding is not accepted")
        return h.ok({"removed": body.fingerprint})

    @router.get(W + "/ledger")
    def ledger_view(series: str, book: str):
        from .bible import store as bible_store
        p = h.open_project(series, book)
        led = bible_store.load_ledger(p)
        return h.ok(led.model_dump() if led else None)

    @router.post(W + "/ledger/questions/{question_id}/answer")
    def ledger_answer(series: str, book: str, question_id: str, body: AnswerBody):
        """Answer a ledger question; the next run revises the ledger from the answer."""
        from .errors import BookforgeError
        from .layers.ledger import answer_question
        p = h.open_project(series, book)
        h.require_idle(series)
        try:
            led = answer_question(p, question_id, body.answer)
        except BookforgeError as e:
            raise HTTPException(422, str(e))
        return h.ok(led.model_dump())

    # ── the briefing ─────────────────────────────────────────────────────────

    @router.get(W + "/briefing/{scene_id}")
    def briefing(series: str, book: str, scene_id: str, tokens: int | None = None):
        return h.ok(xray.preview(h.open_project(series, book), scene_id, tokens))

    @router.get(W + "/xray/{scene_id}")
    def xray_inputs(series: str, book: str, scene_id: str):
        p = h.open_project(series, book)
        findings = xray.input_findings(p, scene_id)
        return h.ok({"scene": scene_id, "findings": findings, "beats": None, "beats_error": None, "diagnosis": xray.diagnose(p, scene_id, findings, None)})

    @router.post(W + "/xray/{scene_id}", status_code=202)
    def xray_beats(series: str, book: str, scene_id: str, body: XrayBody | None = None):
        h.open_project(series, book)
        root = h.series_root(series)

        def job() -> dict:
            _, ctx = job_ctx(root, book, h.make_llm())
            return xray.xray(ctx, scene_id, beats=(body.beats if body else True))

        return h.start_job(series, book, "xray", {"scene": scene_id}, job)

    # ── prompts and experiments ──────────────────────────────────────────────

    @router.get(W + "/prompts")
    def prompts(series: str, book: str):
        return h.ok(studio.list_templates(h.open_project(series, book)))

    @router.get(W + "/prompts/{name}")
    def prompt(series: str, book: str, name: str):
        return h.ok(studio.get_template(h.open_project(series, book), name))

    @router.post(W + "/prompts/{name}/check")
    def prompt_check(series: str, book: str, name: str, body: PromptBody):
        h.open_project(series, book)
        return h.ok(studio.check_candidate(name, body.text))

    @router.put(W + "/prompts/{name}")
    def prompt_save(series: str, book: str, name: str, body: PromptBody):
        p = h.open_project(series, book)
        h.require_idle(series)
        return h.ok(studio.save_override(p, name, body.text))

    @router.delete(W + "/prompts/{name}")
    def prompt_delete(series: str, book: str, name: str):
        p = h.open_project(series, book)
        h.require_idle(series)
        studio.delete_override(p, name)
        return h.ok({"deleted": name})

    @router.post(W + "/ab", status_code=202)
    def ab_run(series: str, book: str, body: ABBody):
        p = h.open_project(series, book)
        check = studio.check_candidate(body.template, body.candidate) if body.template in ab.TESTABLE else None
        if check is None:
            raise HTTPException(422, f"only {', '.join(ab.TESTABLE)} can be tested on the benchmarks")
        if check["errors"]:
            raise HTTPException(422, "; ".join(check["errors"]))
        root = h.series_root(series)
        del p

        def job() -> dict:
            _, ctx = job_ctx(root, book, h.make_llm())
            return ab.run_ab(ctx, body.template, body.candidate, body.only, body.judge)

        return h.start_job(series, book, "ab-test", {"template": body.template, "only": body.only}, job)

    @router.get(W + "/experiments")
    def experiments(series: str, book: str):
        return h.ok(ab.list_experiments(h.open_project(series, book)))

    @router.get(W + "/experiments/{name}")
    def experiment(series: str, book: str, name: str):
        return h.ok(ab.view(h.open_project(series, book), name))

    @router.post(W + "/experiments/{name}/vote")
    def experiment_vote(series: str, book: str, name: str, body: VoteBody):
        p = h.open_project(series, book)
        h.require_idle(series)
        return h.ok(ab.vote(p, name, body.benchmark, body.choice))

    @router.post(W + "/experiments/{name}/promote")
    def experiment_promote(series: str, book: str, name: str):
        p = h.open_project(series, book)
        h.require_idle(series)
        return h.ok(ab.promote(p, name))

    # ── calibration and the arc ──────────────────────────────────────────────

    @router.get(W + "/calibration")
    def calibration_report(series: str, book: str):
        return h.ok(calibration.report(h.open_project(series, book)))

    @router.put(W + "/calibration/{scene_id}")
    def calibration_save(series: str, book: str, scene_id: str, body: ScoresBody):
        p = h.open_project(series, book)
        h.require_idle(series)
        calibration.record(p, scene_id, body.scores)
        return h.ok(calibration.report(p))

    @router.get(W + "/arc")
    def arc_view(series: str, book: str):
        p = h.open_project(series, book)
        return h.ok({"tension": arc.tension(p), "threads": arc.thread_map(p), "milestones": arc.milestones(p)})

    @router.post(W + "/arc/milestones/refresh", status_code=202)
    def arc_milestones_refresh(series: str, book: str):
        h.open_project(series, book)
        root = h.series_root(series)

        def job() -> dict:
            project, ctx = job_ctx(root, book, h.make_llm())
            record = milestones.refresh(ctx, force=True)
            return {"milestones": len(record["items"])}

        return h.start_job(series, book, "milestones", {}, job)

    @router.post(W + "/arc/tension")
    def arc_tension(series: str, book: str, body: TensionBody):
        p = h.open_project(series, book)
        if body.apply:
            h.require_idle(series)
        return h.ok(arc.set_tension(p, body.chapter, body.value, body.apply))

    @router.put(W + "/arc/threads/{thread_id}")
    def arc_thread_save(series: str, book: str, thread_id: str, body: ThreadBody):
        p = h.open_project(series, book)
        h.require_idle(series)
        arc.upsert_thread(p, thread_id, body.note, body.setup, body.payoff)
        return h.ok(arc.thread_map(p))

    @router.delete(W + "/arc/threads/{thread_id}")
    def arc_thread_delete(series: str, book: str, thread_id: str):
        p = h.open_project(series, book)
        h.require_idle(series)
        arc.delete_thread(p, thread_id)
        return h.ok(arc.thread_map(p))
