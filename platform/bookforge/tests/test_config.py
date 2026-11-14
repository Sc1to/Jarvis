from pathlib import Path

import pytest
import yaml

from bookforge.config import Config, load_config
from bookforge.errors import ConfigError

EXAMPLE = Path(__file__).resolve().parent.parent / "config.example.yaml"


def test_defaults_are_valid():
    cfg = load_config()
    assert cfg.models.writer.base_url.endswith(":8040/v1")
    assert cfg.models.critic.base_url.endswith(":8041/v1")
    assert cfg.research.search == "playwright_web_tool"


def test_example_file_matches_built_in_defaults():
    example = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    assert Config.model_validate(example) == Config()


def test_host_config_merges_deeply(tmp_path):
    host = tmp_path / "host.yaml"
    host.write_text("models:\n  writer:\n    model: qwen36-35b\n", encoding="utf-8")
    cfg = load_config(host_path=host)
    assert cfg.models.writer.model == "qwen36-35b"
    assert cfg.models.writer.base_url.endswith(":8040/v1")  # untouched sibling key survives


def test_series_config_overrides_host(tmp_path):
    host = tmp_path / "host.yaml"
    host.write_text("book:\n  target_words: 50000\n  tense: past\n", encoding="utf-8")
    series = tmp_path / "s"
    series.mkdir()
    (series / "config.yaml").write_text("book:\n  target_words: 70000\n", encoding="utf-8")
    cfg = load_config(series, host_path=host)
    assert cfg.book.target_words == 70000
    assert cfg.book.tense == "past"


def test_unknown_key_is_an_error(tmp_path):
    host = tmp_path / "host.yaml"
    host.write_text("qc:\n  max_revison_rounds: 3\n", encoding="utf-8")  # typo
    with pytest.raises(ConfigError):
        load_config(host_path=host)


def test_invalid_yaml_and_missing_host_file(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("models: [unclosed", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(host_path=bad)
    with pytest.raises(ConfigError):
        load_config(host_path=tmp_path / "missing.yaml")


def test_top_level_must_be_a_mapping(tmp_path):
    host = tmp_path / "host.yaml"
    host.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(host_path=host)


def test_layers_must_be_complete_and_known():
    layers = {k: v.model_dump() for k, v in Config().layers.items()}
    only_acts = Config(layers={"acts": layers["acts"]})  # a config written before a layer existed: the missing layers take their defaults
    assert set(only_acts.layers) == set(Config().layers)
    with pytest.raises(ValueError):
        Config(layers={**layers, "epilogue": layers["acts"]})


def test_checkpoint_layers_in_run_order():
    cfg = Config()
    assert cfg.checkpoint_layers("direction") == ["series_north_star", "book_north_star", "synopsis"]
    assert cfg.checkpoint_layers("structure") == ["acts", "chapters", "scenes"]
    assert cfg.checkpoint_layers("voice") == []
