from types import SimpleNamespace

import pytest

from bookforge.ask import ask_until_valid
from bookforge.errors import LayerError


class Scripted:
    def __init__(self, replies):
        self.replies = list(replies)

    def complete(self, role, messages, **options):
        return self.replies.pop(0)


def ctx(tmp_path, replies, rounds=2):
    project = SimpleNamespace(root=tmp_path, config=SimpleNamespace(qc=SimpleNamespace(max_revision_rounds=rounds)))
    return SimpleNamespace(project=project, llm=Scripted(replies))


def hard(text):
    return [] if text.startswith("chapters:") else ["'chapters' must be a list"]


def review(text):
    return ["the summary contradicts a track"]


def test_a_correction_that_breaks_a_valid_reply_keeps_the_valid_one(tmp_path):
    c = ctx(tmp_path, ["chapters: first", "chapters: second", '{"ok": false}'])
    sink = []
    out = ask_until_valid(c, "chapters/act4", "writer", [{"role": "user", "content": "x"}], hard, {}, False,
                          soft_validate=review, soft_sink=sink)
    assert out == "chapters: second"
    assert sink == [("chapters/act4", ["the summary contradicts a track"])]


def test_a_reply_that_was_never_valid_still_fails(tmp_path):
    c = ctx(tmp_path, ["nope", "still nope", "no"])
    with pytest.raises(LayerError, match="still has problems"):
        ask_until_valid(c, "chapters/act4", "writer", [{"role": "user", "content": "x"}], hard, {}, False)
