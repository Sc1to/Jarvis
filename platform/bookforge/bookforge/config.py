"""Configuration: built-in defaults < host config.yaml < series config.yaml.

Unknown keys are errors so typos do not silently fall back to defaults.
"""

import logging
import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .constants import CHECKPOINTS, LAYER_ORDER
from .errors import ConfigError

log = logging.getLogger("platform_bookforge.config")

SERVICE_DIR = Path(__file__).resolve().parent.parent
HOST_CONFIG_ENV = "BOOKFORGE_CONFIG"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


RESERVED_BODY_KEYS = {"model", "messages", "stream", "temperature", "max_tokens", "top_p", "stop", "seed"}


class ModelEndpoint(_Strict):
    base_url: str
    model: str = ""  # id from `c/coli status`; doctor warns while empty
    temperature: float | list[float] = 0.2
    manage_service: str | None = None
    timeout_seconds: float = 600  # max wait for one reply; the big model can be very slow
    # Start every request with a unique first line. Ollama was seen to carry leftover state from the previous request
    # into the next when both began with the same words (answers about the wrong task). Costs speed on long prompts.
    isolate_requests: bool = True
    # Extra fields added to every request body, for things a model needs that bookforge does not know about. The case that
    # matters: reasoning models (Qwen3 and others) spend the whole token budget on hidden thinking and return an empty reply;
    # `{reasoning_effort: none}` turns that off on Ollama's OpenAI-compatible endpoint.
    extra_body: dict[str, Any] = Field(default_factory=dict)

    @field_validator("extra_body")
    @classmethod
    def _not_reserved(cls, v: dict[str, Any]) -> dict[str, Any]:
        reserved = sorted(set(v) & RESERVED_BODY_KEYS)
        if reserved:
            raise ValueError(f"extra_body cannot set {', '.join(reserved)}: bookforge sets those itself")
        return v


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
    max_tokens: int | None = Field(None, gt=0)  # most tokens one draft may use; unset = words[1] x 1.6 + 300. Set it to shorten `words` without shrinking this
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


DEFAULT_SKIP_DOMAINS = [
    "facebook.com", "instagram.com", "tiktok.com", "pinterest.com", "twitter.com", "x.com", "youtube.com", "youtu.be",
    "amazon.com", "ebay.com", "etsy.com", "reddit.com", "quora.com",
    "jstor.org", "researchgate.net", "academia.edu", "newspapers.com", "ancestry.com", "ancestry.co.uk", "findagrave.com",
    "rootsweb.com", "sova.si.edu",
]  # no readable text, shopping, paywalls and archive records, or answers nobody checked


class Research(_Strict):
    enabled: bool = True
    required: bool = False  # True: a layer fails if none of its research questions could be answered
    search: Literal["playwright_web_tool"] = "playwright_web_tool"  # how pages are reached: always the platform web tool
    # Where search results come from. searxng: your own SearXNG metasearch instance (docs/STACK.md), the real web.
    # wikipedia: Wikipedia's API only. auto: searxng if it answers, otherwise wikipedia. duckduckgo: reads a results page,
    # which search engines block for headless browsers (kept for networks where it works).
    source: Literal["auto", "searxng", "wikipedia", "duckduckgo"] = "auto"
    searxng_url: str = "http://127.0.0.1:8060"  # localhost only: the one address the web wrapper may reach on this machine
    search_language: str = Field("en", pattern=r"^(all|[a-z]{2,3}(-[A-Za-z0-9]+)?)$")  # language of the results SearXNG asks for
    wikipedia_language: str = Field("en", pattern=r"^[a-z]{2,8}(-[a-z0-9]+)?$")  # which Wikipedia to search (en, de, fr, ...)
    results_per_question: int = Field(10, gt=0)  # search results considered per question
    max_questions: int = Field(6, gt=0)  # questions asked per layer
    pages_per_question: int = Field(5, gt=0)  # pages read per question (at most; a page with no readable text does not count)
    facts_per_question: int = Field(3, gt=0)  # stop reading pages for a question once this many facts are kept...
    sources_per_question: int = Field(2, gt=0)  # ...and they come from at least this many different pages
    model_pick: bool = True  # a model chooses which results to read from their titles and excerpts (one small call per question)
    skip_domains: list[str] = Field(default_factory=lambda: list(DEFAULT_SKIP_DOMAINS))  # results from these sites are not read
    notes_model: Literal["writer", "critic"] = "writer"  # reads pages and extracts facts
    check_relevance: bool = True  # a second look: drop facts that do not answer the question for the story's time and place
    check_support: bool = True  # an audit: drop a fact whose claim says more than its quote (one small call per page with facts)
    notes_max_chars: int = Field(6000, gt=0)  # research notes included in a prompt
    page_max_chars: int = Field(12000, gt=0)  # page text given to the model (the parts of a long page that mention the question)
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
    critic_may_accept: Literal["within_chapter", "never"] = "within_chapter"  # change requests applied without you
    dialogue_ratio: tuple[float, float] = (0.05, 0.75)  # share of words inside quotes; outside it is a warning
    sentence_variation_min: float = 0.45  # stdev / mean of sentence length; below it the rhythm is flagged as monotone
    overused_word_percent: float = 1.0  # a content word above this share of the scene is flagged (names excluded)
    overused_word_min_count: int = 8
    repeat_ngram_size: int = 5  # words in a phrase checked for repetition across scenes
    repeat_ngram_scenes: int = 2  # earlier scenes that must contain a phrase before it is flagged
    # the model-based layers; switch any off to make a run cheaper
    judge_drafts: bool = True  # choose between drafts with the pairwise judge (otherwise by mechanical score)
    continuity_check: bool = True  # yes/no questions about the story state, the cast and the world
    revise_flagged: bool = True  # a flagged scene is first revised from its saved text with what was found; only then written again
    critic_rewrite: bool = True  # beats_covered or pacing below the minimum: write the scene again once, with the critic's notes, instead of patching three lines
    critic_check: bool = True  # the rubric critique
    extract_observed: bool = True  # record what each accepted scene says about the tracked states
    review_structure: bool = True  # critic review of acts, chapters and scene plans against their parents
    continuity_batch_size: int = Field(8, gt=0)  # questions per model call
    continuity_max_questions: int = Field(40, gt=0)  # per scene


class ExportSettings(_Strict):
    """What `export` needs that is not in the story (docs/BOOKFORGE.md, Output and export)."""
    title: str = ""  # falls back to the series folder's name, with a warning
    subtitle: str = ""
    author: str = ""
    rights: str = ""  # a copyright line for the title page metadata
    pdf_engine: Literal["auto", "typst", "xelatex", "lualatex"] = "auto"  # auto: the first one installed
    page_width_in: float = Field(6.0, gt=0)  # print interior; 6 x 9 in is a common trade size
    page_height_in: float = Field(9.0, gt=0)
    margin_in: float = Field(0.8, gt=0)
    font_size_pt: float = Field(11.0, gt=0)
    reference_docx: str = ""  # a Word file whose styles replace the built-in manuscript format (path in the series)
    cover_image: str = ""  # for the EPUB (path in the series)


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
    export: ExportSettings = ExportSettings()
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
