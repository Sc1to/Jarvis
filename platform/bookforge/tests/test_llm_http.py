import json

import httpx
import pytest

from bookforge.calllog import CallLog
from bookforge.config import Config
from bookforge.llm import HttpLLMClient, LLMError, build_client

MSGS = [{"role": "system", "content": "You are a critic."}, {"role": "user", "content": "Review this."}]


def config(**model_overrides) -> Config:
    cfg = Config()
    cfg.models.writer.model = "qwen-test"
    cfg.models.critic.model = "glm-test"
    for k, v in model_overrides.items():
        setattr(cfg.models.writer, k, v)
    return cfg


def ok(text="A reply.", finish="stop", usage=None):
    body = {"choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": finish}]}
    if usage:
        body["usage"] = usage
    return httpx.Response(200, json=body)


def client(handler, tmp_path, **kw):
    sleeps = []
    c = HttpLLMClient(config(), CallLog(tmp_path / "calls.jsonl"), transport=httpx.MockTransport(handler),
                      sleep=sleeps.append, **kw)
    c.sleeps = sleeps
    return c


def records(tmp_path):
    f = tmp_path / "calls.jsonl"
    return [json.loads(line) for line in f.read_text().splitlines()] if f.exists() else []


def test_request_shape_and_reply(tmp_path):
    seen = []

    def handler(req):
        seen.append((str(req.url), json.loads(req.content)))
        return ok("Hello.", usage={"prompt_tokens": 12, "completion_tokens": 3})

    c = client(handler, tmp_path)
    assert c.complete("critic", MSGS) == "Hello."
    url, body = seen[0]
    assert url == "http://127.0.0.1:8041/v1/chat/completions"
    assert body == {"model": "glm-test", "messages": MSGS, "stream": False, "temperature": 0.2}


def test_writer_goes_to_the_writer_port(tmp_path):
    urls = []
    c = client(lambda req: (urls.append(str(req.url)), ok())[1], tmp_path)
    c.complete("writer", MSGS)
    assert urls == ["http://127.0.0.1:8040/v1/chat/completions"]


def test_temperature_per_draft_and_overrides(tmp_path):
    temps = []
    c = client(lambda req: (temps.append(json.loads(req.content)["temperature"]), ok())[1], tmp_path)
    c.complete("writer", MSGS)                    # default: first
    c.complete("writer", MSGS, draft=1)           # second draft
    c.complete("writer", MSGS, draft=4)           # wraps around
    c.complete("writer", MSGS, temperature=0.1)   # explicit wins
    assert temps == [0.7, 0.85, 0.85, 0.1]


def test_passthrough_options(tmp_path):
    bodies = []
    c = client(lambda req: (bodies.append(json.loads(req.content)), ok())[1], tmp_path)
    c.complete("critic", MSGS, max_tokens=500, stop=["END"], seed=7, top_p=0.9)
    assert (bodies[0]["max_tokens"], bodies[0]["stop"], bodies[0]["seed"], bodies[0]["top_p"]) == (500, ["END"], 7, 0.9)


@pytest.mark.parametrize("role,kwargs,msg", [
    ("narrator", {}, "unknown model role"),
    ("critic", {"logit_bias": {}}, "unsupported option"),
])
def test_bad_calls_fail_before_any_request(tmp_path, role, kwargs, msg):
    c = client(lambda req: pytest.fail("no request expected"), tmp_path)
    with pytest.raises(LLMError, match=msg):
        c.complete(role, MSGS, **kwargs)


def test_unset_model_and_bad_messages(tmp_path):
    c = HttpLLMClient(Config(), transport=httpx.MockTransport(lambda r: pytest.fail("no request")))
    with pytest.raises(LLMError, match="models.writer.model is not set"):
        c.complete("writer", MSGS)
    c2 = client(lambda r: pytest.fail("no request"), tmp_path)
    with pytest.raises(LLMError, match="non-empty list"):
        c2.complete("critic", [])
    with pytest.raises(LLMError, match="non-empty list"):
        c2.complete("critic", [{"role": "user"}])


def test_transient_errors_are_retried_with_backoff(tmp_path):
    answers = iter([httpx.Response(503, text="loading"), httpx.Response(429, text="busy"), ok("finally")])
    c = client(lambda req: next(answers), tmp_path)
    assert c.complete("critic", MSGS) == "finally"
    assert c.sleeps == [2.0, 4.0]
    rec = records(tmp_path)[0]
    assert rec["ok"] is True and rec["attempts"] == 3


def test_gives_up_after_the_last_attempt(tmp_path):
    calls = []
    c = client(lambda req: (calls.append(1), httpx.Response(500, text="boom"))[1], tmp_path)
    with pytest.raises(LLMError, match="after 3 attempts.*HTTP 500"):
        c.complete("critic", MSGS)
    assert len(calls) == 3 and c.sleeps == [2.0, 4.0]
    rec = records(tmp_path)[0]
    assert rec["ok"] is False and "HTTP 500" in rec["error"] and rec["attempts"] == 3


def test_connection_refused_is_retried_and_names_the_service(tmp_path):
    def handler(req):
        raise httpx.ConnectError("refused", request=req)

    c = client(handler, tmp_path)
    with pytest.raises(LLMError, match="colibri service running"):
        c.complete("writer", MSGS)
    assert len(c.sleeps) == 2


def test_timeout_is_retried(tmp_path):
    n = []

    def handler(req):
        n.append(1)
        if len(n) < 2:
            raise httpx.ReadTimeout("slow", request=req)
        return ok("done")

    c = client(handler, tmp_path)
    assert c.complete("critic", MSGS) == "done"


def test_attempts_are_configurable(tmp_path):
    calls = []
    c = client(lambda req: (calls.append(1), httpx.Response(502))[1], tmp_path, attempts=1)
    with pytest.raises(LLMError, match="after 1 attempts"):
        c.complete("critic", MSGS)
    assert len(calls) == 1 and c.sleeps == []


@pytest.mark.parametrize("status,needle", [(404, "not found"), (400, "HTTP 400"), (401, "HTTP 401")])
def test_client_errors_are_not_retried(tmp_path, status, needle):
    calls = []
    c = client(lambda req: (calls.append(1), httpx.Response(status, text="nope"))[1], tmp_path)
    with pytest.raises(LLMError, match=needle):
        c.complete("critic", MSGS)
    assert len(calls) == 1 and c.sleeps == []


def test_404_message_names_the_model(tmp_path):
    c = client(lambda req: httpx.Response(404, text="no such model"), tmp_path)
    with pytest.raises(LLMError, match="glm-test"):
        c.complete("critic", MSGS)


@pytest.mark.parametrize("response,needle", [
    (ok("   "), "empty reply"),
    (ok("partial", finish="length"), "cut off"),
    (httpx.Response(200, json={"choices": []}), "unexpected response shape"),
    (httpx.Response(200, json={"nope": 1}), "unexpected response shape"),
    (httpx.Response(200, text="<html>proxy error</html>"), "did not return JSON"),
])
def test_bad_replies_are_errors_not_text(tmp_path, response, needle):
    c = client(lambda req: response, tmp_path)
    with pytest.raises(LLMError, match=needle):
        c.complete("critic", MSGS)
    assert records(tmp_path)[0]["ok"] is False


def test_call_log_has_prompt_reply_and_usage(tmp_path):
    c = client(lambda req: ok("Reply.", usage={"prompt_tokens": 5, "completion_tokens": 2}), tmp_path)
    c.complete("critic", MSGS)
    rec = records(tmp_path)[0]
    assert rec["kind"] == "llm" and rec["role"] == "critic" and rec["model"] == "glm-test"
    assert rec["messages"] == MSGS and rec["response"] == "Reply."
    assert rec["usage"] == {"prompt_tokens": 5, "completion_tokens": 2}
    assert rec["finish_reason"] == "stop" and rec["duration_seconds"] >= 0 and "ts" in rec


def test_a_broken_call_log_never_fails_the_call(tmp_path):
    bad_log = CallLog(tmp_path)  # a directory: appending raises OSError
    c = HttpLLMClient(config(), bad_log, transport=httpx.MockTransport(lambda r: ok("fine")))
    assert c.complete("critic", MSGS) == "fine"


def test_build_client_logs_inside_the_book(project):
    c = build_client(project)
    assert c._log.path == project.book_dir / "logs" / "calls.jsonl"
