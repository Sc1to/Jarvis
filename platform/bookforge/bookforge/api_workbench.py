"""The workbench's routes (milestone 14.13), added to the same router as the rest of the API.

All under /api/series/{s}/books/{b}/workbench. What needs a model (testing a rule, proposing a rule from a comment,
the beat check of the X-ray, A/B tests) is a background job like a run: the result is in the job. Everything else
answers at once. Anything that writes needs an idle series (409 otherwise), like the other changes.
"""

from typing import Callable

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import ab, arc, calibration, rules, rules_ai, studio, xray
from .layers.runner import StepContext
from .project import Project

W = "/series/{series}/books/{book}/workbench"


class Helpers:
    """What the router needs from api.py (kept as plain callables so this module does not import it)."""

    def __init__(self, open_project: Callable, series_root: Callable, require_idle: Callable, start_job: Callable,
                 make_llm: Callable, ok: Callable):
        self.open_project, self.series_root, self.require_idle, self.start_job = open_project, series_root, require_idle, start_job
        self.make_llm, self.ok = make_llm, ok


class TestRuleBody(BaseModel):
    rule: rules.Rule


class ProposeBody(BaseModel):
    scene: str
    passage: str
    comment: str


class XrayBody(BaseModel):
    beats: bool = True


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
        return h.ok({"tension": arc.tension(p), "threads": arc.thread_map(p)})

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
