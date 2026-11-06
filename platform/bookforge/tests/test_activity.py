"""What a running job is doing now: filled in by the pipeline, returned with the job, harmless when nothing is bound."""

import threading

import httpx
import pytest

from bookforge import activity
from bookforge.calllog import CallLog
from bookforge.jobs import JobManager
from bookforge.llm import HttpLLMClient
from conftest import RuleLLM
from test_llm_http import MSGS, config, ok
from test_prose_qc import book, go, qc_rules  # noqa: F401


@pytest.fixture(autouse=True)
def unbound():
    activity.bind(None)
    yield
    activity.bind(None)


def test_nothing_happens_when_nothing_is_bound():
    activity.set(scene="b1.ch01.s1")
    activity.add("calls")
    activity.call_started("writer", "Write the scene")
    activity.call_finished()  # no error, nothing recorded anywhere


def test_a_bound_state_is_filled_in():
    state: dict = {}
    activity.bind(state)
    activity.set(layer="prose", scene="b1.ch03.s2", step="writing drafts")
    activity.add("scenes_done")
    activity.add("scenes_done")
    activity.call_started("writer", "  Write the scene   described below.\n\n## Series north star  " + "x" * 200)
    assert state["layer"] == "prose" and state["scene"] == "b1.ch03.s2" and state["step"] == "writing drafts" and state["scenes_done"] == 2
    assert state["calls"] == 1 and state["call_role"] == "writer" and "call_started" in state
    assert state["call_label"].startswith("Write the scene described below. ## Series north star") and len(state["call_label"]) == activity.LABEL_CHARS
    activity.call_finished()
    assert "call_started" not in state and "call_label" not in state and "last_call_finished" in state and state["calls"] == 1


def test_each_thread_has_its_own_state():
    mine: dict = {}
    activity.bind(mine)
    other: dict = {}

    def work():
        activity.bind(other)
        activity.set(scene="theirs")

    t = threading.Thread(target=work)
    t.start()
    t.join()
    activity.set(scene="mine")
    assert mine == {"scene": "mine"} and other == {"scene": "theirs"}


def test_a_request_to_the_model_is_counted_and_visible_while_it_runs(tmp_path):
    state: dict = {}
    seen = []

    def handler(req):
        seen.append(dict(state))  # what the dashboard would see in the middle of the call
        return ok("A reply.")

    activity.bind(state)
    c = HttpLLMClient(config(), CallLog(tmp_path / "calls.jsonl"), transport=httpx.MockTransport(handler), sleep=lambda s: None)
    c.complete("critic", MSGS)
    assert seen[0]["calls"] == 1 and seen[0]["call_label"] == "Review this." and seen[0]["call_role"] == "critic" and "call_started" in seen[0]
    assert "call_started" not in state and state["calls"] == 1 and "last_call_finished" in state


def test_the_call_is_cleared_even_when_the_request_fails(tmp_path):
    state: dict = {}
    activity.bind(state)
    c = HttpLLMClient(config(), CallLog(tmp_path / "calls.jsonl"), attempts=1,
                      transport=httpx.MockTransport(lambda req: httpx.Response(400, text="bad")), sleep=lambda s: None)
    with pytest.raises(Exception):
        c.complete("critic", MSGS)
    assert "call_started" not in state and state["calls"] == 1


def test_a_running_job_shows_what_it_is_doing_and_is_unbound_afterwards(tmp_path):
    jobs = JobManager()
    working, release = threading.Event(), threading.Event()

    def work():
        activity.set(layer="prose", scene="b1.ch01.s1", step="checking continuity")
        activity.add("scenes_done")
        working.set()
        release.wait(5)
        return {}

    job = jobs.start(tmp_path, "s", "b1", "run", {}, work)
    assert working.wait(5)
    live = job.to_dict()["activity"]
    assert live == {"layer": "prose", "scene": "b1.ch01.s1", "step": "checking continuity", "scenes_done": 1}
    release.set()
    jobs.wait(job.id, 5)
    assert job.status == "done" and activity._state() is None  # unbound in the main thread, and the thread's binding is gone
    assert jobs.get(tmp_path, "s", "b1", job.id)["activity"]["scenes_done"] == 1  # the last snapshot is kept with the record


def test_the_prose_layer_reports_the_scene_the_step_and_the_scenes_done(book):
    state: dict = {}
    activity.bind(state)
    go(book, RuleLLM(qc_rules()))
    assert state["layer"] == "prose" and state["scenes_done"] >= 1
    assert state["scene"].startswith("b1.ch0") and state["step"] == "recording what the scene shows"


# ── tokens spent by a run ───────────────────────────────────────────────────

def test_the_tokens_a_reply_reports_are_added_up():
    state: dict = {}
    activity.bind(state)
    activity.usage({"prompt_tokens": 1200, "completion_tokens": 300, "total_tokens": 1500})
    activity.usage({"prompt_tokens": 800, "completion_tokens": 100})
    assert state["prompt_tokens"] == 2000 and state["completion_tokens"] == 400


def test_a_reply_without_usage_adds_nothing_and_odd_values_are_ignored():
    state: dict = {}
    activity.bind(state)
    for odd in (None, {}, "x", {"prompt_tokens": "12"}, {"prompt_tokens": True}, {"prompt_tokens": -5}, [1]):
        activity.usage(odd)
    assert state == {}
    activity.bind(None)
    activity.usage({"prompt_tokens": 5})  # unbound: nothing happens


def test_a_request_adds_its_tokens_to_the_job_and_a_cut_off_reply_counts_too(tmp_path):
    state: dict = {}
    activity.bind(state)
    replies = iter([
        httpx.Response(200, json={"choices": [{"message": {"content": "partial text"}, "finish_reason": "length"}],
                                  "usage": {"prompt_tokens": 1000, "completion_tokens": 500}}),
        httpx.Response(200, json={"choices": [{"message": {"content": "whole reply"}, "finish_reason": "stop"}],
                                  "usage": {"prompt_tokens": 1000, "completion_tokens": 900}}),
    ])
    c = HttpLLMClient(config(), CallLog(tmp_path / "calls.jsonl"), transport=httpx.MockTransport(lambda req: next(replies)), sleep=lambda s: None)
    assert c.complete("critic", MSGS, max_tokens=500) == "whole reply"  # cut off once, asked again with a larger limit
    assert state["prompt_tokens"] == 2000 and state["completion_tokens"] == 1400 and state["calls"] == 2


def test_a_cut_off_call_keeps_its_usage_in_the_call_log_so_the_morning_report_counts_it(tmp_path):
    import json
    from bookforge.llm import LLMError
    c = HttpLLMClient(config(), CallLog(tmp_path / "calls.jsonl"), sleep=lambda s: None, transport=httpx.MockTransport(
        lambda req: httpx.Response(200, json={"choices": [{"message": {"content": "partial"}, "finish_reason": "length"}],
                                              "usage": {"prompt_tokens": 700, "completion_tokens": 300}})))
    try:
        c.complete("critic", MSGS, max_tokens=500, grow=False)
    except LLMError:
        pass
    rec = json.loads((tmp_path / "calls.jsonl").read_text().splitlines()[0])
    assert rec["ok"] is False and rec["usage"] == {"prompt_tokens": 700, "completion_tokens": 300}
