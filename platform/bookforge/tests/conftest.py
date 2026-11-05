import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from bookforge.layers.runner import StepContext, StepResult  # noqa: E402
from bookforge.project import Project  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """No host config, no global git config: tests see only built-in defaults."""
    host = tmp_path / "_host_config.yaml"
    host.write_text("", encoding="utf-8")
    monkeypatch.setenv("BOOKFORGE_CONFIG", str(host))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    monkeypatch.setenv("HOME", str(tmp_path))


@pytest.fixture
def project(tmp_path) -> Project:
    project = Project.create(tmp_path / "series", "A clerk finds a ledger that predicts deaths.\n")
    project.config.research.model_pick = False  # tests that exercise the model's pick turn it on
    return project


def file_handler(rel_path: str, text: str = "content\n"):
    """A handler that writes one file, like a layer producing its output."""

    def handler(ctx: StepContext) -> StepResult:
        path = ctx.project.resolve(rel_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return StepResult(files=[rel_path], note=f"wrote {rel_path}")

    return handler


def all_handlers() -> dict:
    return {
        "series_north_star": file_handler("north-star.md"),
        "book_north_star": file_handler("books/b1/north-star.md"),
        "synopsis": file_handler("books/b1/synopsis.md"),
        "acts": file_handler("books/b1/acts.yaml"),
        "chapters": file_handler("books/b1/chapters.yaml"),
        "scenes": file_handler("books/b1/scenes.yaml"),
        "prose": file_handler("books/b1/scenes/ch01.md"),
    }


class RuleLLM:
    """A fake model that answers by what it is asked, for steps whose call order is awkward to script.

    `rules` is a list of (marker, reply) pairs; the first rule whose marker appears in the last user
    message wins. A reply may be a string or a function of the messages. Records every call.
    """

    def __init__(self, rules):
        self.rules = list(rules)
        self.calls = []

    def complete(self, role, messages, **options):
        self.calls.append({"role": role, "messages": [dict(m) for m in messages], "options": options})
        # Match on the first user message, so a correction round (which has no marker of its own) gets the same rule.
        first = next((m["content"] for m in messages if m["role"] == "user"), "")
        last = messages[-1]["content"]
        for marker, reply in self.rules:
            if marker in first:
                return reply(messages) if callable(reply) else reply
        raise AssertionError(f"no rule matches this prompt: {first[:120]!r}")

    def calls_matching(self, marker):
        return [c for c in self.calls if marker in c["messages"][-1]["content"]]
