"""Configuration: built-in defaults < host config.yaml < series config.yaml.

Unknown keys are errors so typos do not silently fall back to defaults.
"""

import logging
import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .constants import CHECKPOINTS, LAYER_ORDER
from .errors import ConfigError

log = logging.getLogger("platform_bookforge.config")

SERVICE_DIR = Path(__file__).resolve().parent.parent
HOST_CONFIG_ENV = "BOOKFORGE_CONFIG"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelEndpoint(_Strict):
    base_url: str
    model: str = ""  # id from `c/coli status`; doctor warns while empty
    temperature: float | list[float] = 0.2
    manage_service: str | None = None
    timeout_seconds: float = 600  # max wait for one reply; the big model can be very slow


class DecideEndpoint(_Strict):
    url: str = "http://127.0.0.1:8041/v1/systemone"


class Models(_Strict):
    writer: ModelEndpoint = ModelEndpoint(base_url="http://127.0.0.1:8040/v1", temperature=[0.7, 0.85, 1.0])
    critic: ModelEndpoint = ModelEndpoint(
        base_url="http://127.0.0.1:8041/v1", temperature=0.2, manage_service="platform-colibri-critic",
        timeout_seconds=1800,
    )
    decide: DecideEndpoint = DecideEndpoint()


class LayerSettings(_Strict):
    model: Literal["writer", "critic"]
    checkpoint: Literal["direction", "structure"] | None = None
    count: tuple[int, int] | None = None
    per_chapter: tuple[int, int] | None = None
    drafts: int | None = None
    words: tuple[int, int] | None = None
    temperature: float | None = None  # overrides the model's own temperature for this layer


def _default_layers() -> dict[str, LayerSettings]:
    return {
        "series_north_star": LayerSettings(model="critic", checkpoint="direction"),
        "book_north_star": LayerSettings(model="critic", checkpoint="direction"),
        "synopsis": LayerSettings(model="critic", checkpoint="direction"),
        "acts": LayerSettings(model="critic", count=(3, 4), checkpoint="structure"),
        "chapters": LayerSettings(model="critic", count=(25, 35), checkpoint="structure"),
        "scenes": LayerSettings(model="critic", per_chapter=(2, 4), checkpoint="structure"),
        "prose": LayerSettings(model="writer", drafts=2, words=(1500, 3000)),
    }


class Research(_Strict):
    enabled: bool = True
    required: bool = False  # True: a layer fails if none of its research questions could be answered
    search: Literal["playwright_web_tool"] = "playwright_web_tool"
    results_per_question: int = Field(5, gt=0)  # search results considered per question
    max_questions: int = Field(6, gt=0)  # questions asked per layer
    pages_per_question: int = Field(2, gt=0)  # pages read per question
    notes_model: Literal["writer", "critic"] = "writer"  # reads pages and extracts facts
    notes_max_chars: int = Field(6000, gt=0)  # research notes included in a prompt
    page_max_chars: int = Field(12000, gt=0)  # page text given to the model
    scene_questions: int = Field(2, ge=0)  # questions researched per chapter before its scenes are planned (0 = none)


class BookSettings(_Strict):
    target_words: int = 90000
    pov: str = "third-limited"
    tense: str = "past"
    language: str = "English"  # language of the book; section headings stay in English


class Briefing(_Strict):
    max_tokens: int = Field(16000, gt=0)  # estimated (about 3.5 characters per token); see briefing.py
    previous_scene_words: int = Field(1500, gt=0)  # tail of the previous scene given verbatim
    sample_passages: int = Field(2, ge=0)  # style/samples/*.md files included
    recent_chapters_full: int = Field(2, ge=0)  # chapters before this one summarised scene by scene; older ones in a line each


class QC(_Strict):
    continuity_flag_threshold: float = 0.3
    critic_min_score: int = 3
    max_revision_rounds: int = 2
    banned_phrases: str = "style/banned.txt"
    critic_may_accept: str = "within_chapter"
    dialogue_ratio: tuple[float, float] = (0.05, 0.75)  # share of words inside quotes; outside it is a warning
    sentence_variation_min: float = 0.45  # stdev / mean of sentence length; below it the rhythm is flagged as monotone
    overused_word_percent: float = 1.0  # a content word above this share of the scene is flagged (names excluded)
    overused_word_min_count: int = 8
    repeat_ngram_size: int = 5  # words in a phrase checked for repetition across scenes
    repeat_ngram_scenes: int = 2  # earlier scenes that must contain a phrase before it is flagged


class GitSettings(_Strict):
    commit_each_step: bool = True
    tag_checkpoints: bool = True


class Config(_Strict):
    data_dir: str = "/opt/platform/data/bookforge"
    models: Models = Models()
    layers: dict[str, LayerSettings] = _default_layers()
    research: Research = Research()
    book: BookSettings = BookSettings()
    briefing: Briefing = Briefing()
    qc: QC = QC()
    git: GitSettings = GitSettings()

    @field_validator("layers")
    @classmethod
    def _layers_complete(cls, v: dict[str, LayerSettings]) -> dict[str, LayerSettings]:
        unknown = set(v) - set(LAYER_ORDER)
        missing = set(LAYER_ORDER) - set(v)
        if unknown:
            raise ValueError(f"unknown layers: {sorted(unknown)}")
        if missing:
            raise ValueError(f"missing layers: {sorted(missing)}")
        for name, s in v.items():
            if s.checkpoint is not None and s.checkpoint not in CHECKPOINTS:
                raise ValueError(f"layer {name}: unknown checkpoint {s.checkpoint}")
        return v

    def checkpoint_layers(self, checkpoint: str) -> list[str]:
        """Layers (in run order) that must be accepted before this checkpoint is reached."""
        return [name for name in LAYER_ORDER if self.layers[name].checkpoint == checkpoint]


def _read_yaml(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as e:
        raise ConfigError(f"cannot read {path}: {e}") from e
    except yaml.YAMLError as e:
        raise ConfigError(f"invalid YAML in {path}: {e}") from e
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a mapping at the top level")
    return data


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def host_config_path() -> Path | None:
    """BOOKFORGE_CONFIG if set, else platform/bookforge/config.yaml if it exists."""
    env = os.environ.get(HOST_CONFIG_ENV)
    if env:
        return Path(env)
    p = SERVICE_DIR / "config.yaml"
    return p if p.exists() else None


def load_config(series_root: Path | None = None, host_path: Path | None = None) -> Config:
    """Merge defaults, the host config and (if given) the series' own config.yaml."""
    merged = Config().model_dump(mode="json")
    host = host_path if host_path is not None else host_config_path()
    if host is not None:
        if not host.exists():
            raise ConfigError(f"host config not found: {host}")
        merged = _deep_merge(merged, _read_yaml(host))
    if series_root is not None:
        series_cfg = series_root / "config.yaml"
        if series_cfg.exists():
            merged = _deep_merge(merged, _read_yaml(series_cfg))
    try:
        return Config.model_validate(merged)
    except ValidationError as e:
        raise ConfigError(f"invalid configuration: {e}") from e
