import httpx
import pytest

from bookforge.config import ModelEndpoint
from bookforge.doctor import check_decide_endpoint, check_models_endpoint, check_web, run_doctor
from bookforge.research.search import FakeWebClient

MODELS = httpx.Response(200, json={"data": [{"id": "qwen36-35b"}, {"id": "other"}]})


def transport(handler):
    return httpx.MockTransport(handler)


def endpoint(model="qwen36-35b"):
    return ModelEndpoint(base_url="http://127.0.0.1:8040/v1", model=model)


def by_name(checks):
    return {c.name: c for c in checks}


def test_endpoint_ok_when_the_model_is_served():
    seen = []
    c = check_models_endpoint("writer", endpoint(), transport(lambda r: (seen.append(str(r.url)), MODELS)[1]))
    assert c.level == "pass" and "qwen36-35b" in c.detail
    assert seen == ["http://127.0.0.1:8040/v1/models"]


def test_endpoint_fails_when_the_model_is_not_served():
    c = check_models_endpoint("writer", endpoint("missing"), transport(lambda r: MODELS))
    assert c.level == "fail" and "missing" in c.detail and "qwen36-35b" in c.detail


def test_unset_model_warns_and_lists_what_is_available():
    c = check_models_endpoint("writer", endpoint(""), transport(lambda r: MODELS))
    assert c.level == "warn" and "qwen36-35b, other" in c.detail


def test_unreachable_endpoint_fails_and_names_the_unit():
    def refuse(req):
        raise httpx.ConnectError("refused", request=req)

    c = check_models_endpoint("critic", endpoint(), transport(refuse))
    assert c.level == "fail" and "platform-colibri-critic" in c.detail


@pytest.mark.parametrize("response", [httpx.Response(500), httpx.Response(200, text="not json"), httpx.Response(200, json={"x": 1})])
def test_unusable_endpoint_replies_fail(response):
    assert check_models_endpoint("writer", endpoint(), transport(lambda r: response)).level == "fail"


def test_decide_endpoint_levels():
    assert check_decide_endpoint("http://x/v1/systemone", transport(lambda r: httpx.Response(200))).level == "pass"
    assert check_decide_endpoint("http://x/v1/systemone", transport(lambda r: httpx.Response(404))).level == "warn"

    def refuse(req):
        raise httpx.ConnectError("refused", request=req)

    assert check_decide_endpoint("http://x/v1/systemone", transport(refuse)).level == "warn"


def test_web_checks_with_a_working_client():
    checks = by_name(check_web(FakeWebClient(pages={"https://example.com": "Example Domain"})))
    assert checks["web_tool"].level == "pass"
    assert checks["web_fetch"].level == "pass" and "14 chars" in checks["web_fetch"].detail


def test_web_fetch_failure_is_a_fail():
    checks = by_name(check_web(FakeWebClient()))
    assert checks["web_fetch"].level == "fail"


def test_web_checks_without_fetch():
    assert "web_fetch" not in by_name(check_web(FakeWebClient(), fetch=False))


def test_missing_playwright_is_reported(monkeypatch):
    from bookforge import doctor
    monkeypatch.setattr(doctor, "playwright_installed", lambda: False)
    assert by_name(check_web(None))["playwright"].level == "fail"


def test_run_doctor_online_runs_every_check(project_with_ledger, tmp_path):
    project = project_with_ledger
    host = tmp_path / "_host_config.yaml"
    host.write_text("models:\n  writer:\n    model: qwen36-35b\n  critic:\n    model: other\n", encoding="utf-8")
    result = by_name(run_doctor(project.root, transport=transport(lambda r: MODELS if r.url.path.endswith("/models") else httpx.Response(200)),
                                web_client=FakeWebClient(pages={"https://example.com": "ok"})))
    for name in ("endpoint_writer", "endpoint_critic", "endpoint_decide", "web_tool", "web_fetch", "series_state", "series_git"):
        assert result[name].level == "pass", (name, result[name])


def test_run_doctor_offline_makes_no_network_calls(project):
    def forbidden(req):
        pytest.fail("offline doctor must not call out")

    result = by_name(run_doctor(project.root, online=False, transport=transport(forbidden), web_client=FakeWebClient()))
    assert result["network"].level == "warn"
    assert "endpoint_writer" not in result and "web_fetch" not in result
    assert result["web_tool"].level == "pass"
    assert result["model_writer"].level == "warn"  # model id not set


def test_run_doctor_with_a_broken_config_skips_network_checks(project):
    (project.root / "config.yaml").write_text("bogus: 1\n")
    result = by_name(run_doctor(project.root, transport=transport(lambda r: pytest.fail("no calls")), web_client=FakeWebClient()))
    assert result["config"].level == "fail" and "endpoint_writer" not in result
