"""Which models are running, who uses which, and choosing another one (model_admin.py)."""

import json

import httpx
import pytest

from bookforge import model_admin
from bookforge.config import Config, ConfigError, load_config

OLLAMA = "http://127.0.0.1:11434/v1"
GB = 1024 ** 3


class Backends:
    """Mock Ollama (11434) and colibri writer (8040); records the unload requests."""

    def __init__(self, loaded=("qwen3.5:35b",), colibri="up"):
        self.loaded, self.colibri, self.unloaded = set(loaded), colibri, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        if url.port == 11434:
            if url.path == "/api/tags":
                return httpx.Response(200, json={"models": [{"name": "qwen3.5:35b", "size": 24 * GB}, {"name": "llama3.3:70b", "size": 43 * GB}]})
            if url.path == "/api/ps":
                return httpx.Response(200, json={"models": [{"name": n} for n in sorted(self.loaded)]})
            if url.path == "/api/generate":
                body = json.loads(request.content)
                assert body["keep_alive"] == 0
                self.unloaded.append(body["model"])
                self.loaded.discard(body["model"])
                return httpx.Response(200, json={"done": True})
        if url.port == 8040:
            if self.colibri == "loading":
                return httpx.Response(503, json={"status": "restarting"})
            if self.colibri == "up":
                if url.path == "/health":
                    return httpx.Response(200, json={"status": "ok"})
                if url.path == "/v1/models":
                    return httpx.Response(200, json={"data": [{"id": "qwen3.6-colibri"}]})
        return httpx.Response(404)


@pytest.fixture
def backends():
    return Backends()


@pytest.fixture
def transport(backends):
    return httpx.MockTransport(backends)


@pytest.fixture(autouse=True)
def plenty_of_memory(monkeypatch):
    monkeypatch.setattr(model_admin, "memory", lambda: {"total_gb": 128.0, "available_gb": 60.0})


def test_ollama_is_told_apart_from_colibri(transport):
    ollama = model_admin.probe(OLLAMA, transport)
    assert ollama["backend"] == "ollama" and ollama["state"] == "ready"
    assert {(m["id"], m["loaded"]) for m in ollama["models"]} == {("qwen3.5:35b", True), ("llama3.3:70b", False)}
    colibri = model_admin.probe("http://127.0.0.1:8040/v1", transport)
    assert colibri["backend"] == "colibri" and colibri["models"] == [{"id": "qwen3.6-colibri", "size_gb": None, "loaded": True}]


def test_a_colibri_engine_that_is_starting_is_loading_not_down(backends, transport):
    backends.colibri = "loading"
    p = model_admin.probe("http://127.0.0.1:8040/v1", transport)
    assert p["state"] == "loading" and p["reachable"]
    backends.colibri = "down"
    assert model_admin.probe("http://127.0.0.1:8040/v1", transport)["state"] == "down"


def test_overview_lists_every_name_and_marks_the_loaded_model(transport):
    config = Config()
    config.models.writer.base_url, config.models.writer.model = OLLAMA, "qwen3.5:35b"
    config.models.critic.base_url = "http://127.0.0.1:8040/v1"
    o = model_admin.overview(config, transport)
    names = {n["name"]: n for n in o["names"]}
    assert set(names) == {"writer", "critic", "research", "extraction"}
    assert names["writer"]["loaded"] and names["writer"]["backend"] == "ollama"
    assert names["research"]["is_alias"] and names["research"]["model"] == "qwen3.5:35b"  # follows the writer
    assert names["writer"]["layers"] == ["prose"]
    assert {(a["id"], a["backend"]) for a in o["available"]} >= {("qwen3.5:35b", "ollama"), ("llama3.3:70b", "ollama"), ("qwen3.6-colibri", "colibri")}


def test_a_model_that_will_not_fit_is_warned_about(monkeypatch, transport):
    monkeypatch.setattr(model_admin, "memory", lambda: {"total_gb": 128.0, "available_gb": 20.0})
    o = model_admin.overview(Config(), transport)
    big = next(a for a in o["available"] if a["id"] == "llama3.3:70b")
    assert "needs about 51.6 GB" in big["warning"]  # 43 GB x 1.2; 20 free + 24 that would be unloaded = 44
    assert next(a for a in o["available"] if a["id"] == "qwen3.5:35b")["warning"] == ""  # already loaded


def test_choosing_a_model_for_a_role_is_saved_and_used(project, transport):
    out = model_admin.choose(project.root, "writer", OLLAMA, "qwen3.5:35b", transport)
    assert (project.root / "models.local.yaml").is_file()
    ep = load_config(project.root).models.writer
    assert (ep.base_url, ep.model) == (OLLAMA, "qwen3.5:35b")
    assert ep.temperature == [0.7, 0.85, 1.0]  # what was not chosen is kept
    assert next(n for n in out["names"] if n["name"] == "writer")["model"] == "qwen3.5:35b"


def test_a_new_backend_drops_the_old_one_s_extra_request_fields(project, transport):
    (project.root / "config.yaml").write_text("models:\n  writer:\n    base_url: " + OLLAMA + "\n    model: qwen3.5:35b\n    extra_body: {reasoning_effort: none}\n"
                                              "  critic:\n    base_url: http://127.0.0.1:8040/v1\n    model: qwen3.6-colibri\n")  # colibri is configured, so it is listed
    out = model_admin.choose(project.root, "writer", "http://127.0.0.1:8040/v1", "qwen3.6-colibri", transport)
    assert load_config(project.root).models.writer.extra_body == {}
    assert any("reasoning_effort" in n for n in out["notes"])


def test_a_model_the_backends_do_not_list_cannot_be_chosen(project, transport):
    with pytest.raises(model_admin.ModelChoiceError, match="not served"):
        model_admin.choose(project.root, "writer", OLLAMA, "no-such-model", transport)
    with pytest.raises(model_admin.ModelChoiceError, match="not served"):
        model_admin.choose(project.root, "writer", "http://169.254.169.254/v1", "x", transport)  # the page cannot point bookforge at any address
    assert not (project.root / "models.local.yaml").exists()


def test_a_layer_can_use_its_own_model_and_be_put_back(project, transport):
    model_admin.choose(project.root, "layer:series_north_star", OLLAMA, "llama3.3:70b", transport)
    cfg = load_config(project.root)
    name = cfg.layers["series_north_star"].model
    assert name == "llama3.3-70b" and cfg.endpoint(name).model == "llama3.3:70b" and cfg.endpoint(name).base_url == OLLAMA
    assert cfg.layers["book_north_star"].model == "critic"  # the others are untouched
    model_admin.choose(project.root, "layer:series_north_star", None, None, transport)
    assert load_config(project.root).layers["series_north_star"].model == "critic"


def test_a_model_already_assigned_to_a_role_is_reused_not_duplicated(project, transport):
    model_admin.choose(project.root, "writer", OLLAMA, "qwen3.5:35b", transport)
    model_admin.choose(project.root, "layer:acts", OLLAMA, "qwen3.5:35b", transport)
    cfg = load_config(project.root)
    assert cfg.layers["acts"].model == "writer" and cfg.models.extra == {}


def test_research_extraction_and_the_prose_checks_can_each_have_a_model(project, transport):
    for target in ("research", "extraction", "qc"):
        model_admin.choose(project.root, target, OLLAMA, "llama3.3:70b", transport)
    cfg = load_config(project.root)
    assert cfg.endpoint("research").model == cfg.endpoint("extraction").model == cfg.endpoint(cfg.qc.model).model == "llama3.3:70b"
    assert cfg.endpoint("writer").model == ""  # the writer itself did not change


def test_the_model_a_role_leaves_behind_is_unloaded(project, backends, transport):
    model_admin.choose(project.root, "writer", OLLAMA, "qwen3.5:35b", transport)
    assert backends.unloaded == []  # nothing was left behind
    out = model_admin.choose(project.root, "writer", OLLAMA, "llama3.3:70b", transport)
    assert backends.unloaded == ["qwen3.5:35b"] and out["unloaded"] == ["qwen3.5:35b"]


def test_a_model_still_used_by_another_role_stays_loaded(project, backends, transport):
    model_admin.choose(project.root, "writer", OLLAMA, "qwen3.5:35b", transport)
    model_admin.choose(project.root, "critic", OLLAMA, "qwen3.5:35b", transport)
    model_admin.choose(project.root, "writer", OLLAMA, "llama3.3:70b", transport)
    assert backends.unloaded == []


def test_a_bad_choice_file_is_rolled_back(project, transport):
    (project.root / "models.local.yaml").write_text("layers:\n  acts: {model: gone}\n")
    with pytest.raises(ConfigError):
        load_config(project.root)
    with pytest.raises(ConfigError):
        model_admin.choose(project.root, "writer", OLLAMA, "qwen3.5:35b", transport)  # cannot start from a broken file


def test_unknown_names_are_a_config_error():
    with pytest.raises(ValueError, match="unknown model name"):
        Config.model_validate({"layers": {**{k: v.model_dump() for k, v in Config().layers.items()}, "acts": {"model": "gone"}}})
