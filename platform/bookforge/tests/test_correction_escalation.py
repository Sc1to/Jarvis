"""The second correction round is firmer: it marks the problems that survived the first, quotes where they are in the model's own reply."""

import pytest
from conftest import RuleLLM  # noqa: F401
from bookforge.ask import ask_until_valid, where_in_reply, _problem_key
from bookforge.layers.runner import StepContext
from bookforge.llm import FakeLLMClient


def validate(text):
    return [] if "GOOD" in text else ["chapter_retells_event [b2.ch03, e7]: b2.ch03 describes e7 again: do not tell it", "flat_tension [b2.ch01]: tension is flat"] if "BAD2" in text else ["chapter_retells_event [b2.ch03, e7]: b2.ch03 describes e7 again: do not tell it"]


def run(project, replies):
    llm = FakeLLMClient({"critic": replies})
    ctx = StepContext(project=project, layer="chapters", llm=llm)
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "write it"}]
    out = ask_until_valid(ctx, "t", "critic", msgs, validate, {}, strip_preamble=False)
    return out, llm


def test_the_first_correction_is_plain_and_the_second_marks_what_is_still_wrong(project):
    reply = "- id: b2.ch03\n  summary: Eli and Mara locate the buried Kestrel. BAD\n- id: b2.ch04\n  summary: fine"
    out, llm = run(project, [reply, reply.replace("BAD", "BAD2"), "GOOD"])
    assert out == "GOOD"
    first, second = (c["messages"][-1]["content"] for c in llm.calls[1:3])
    assert "Your previous document has these problems" in first and "STILL PRESENT" not in first
    assert "correction round 2 of 2" in second and "did NOT fix" in second
    assert "- STILL PRESENT: chapter_retells_event [b2.ch03, e7]" in second and "- flat_tension [b2.ch01]" in second  # a new problem is listed unmarked
    assert "Where they are in your last reply" in second and "summary: Eli and Mara locate the buried Kestrel" in second
    assert "summary: fine" not in second  # only the lines that concern the problems


def test_where_in_reply_quotes_only_item_ids_and_caps_the_lines():
    text = "\n".join(f"line {i} about b2.ch03" for i in range(20)) + "\nunrelated e7 line"
    where = where_in_reply(text, ["x [b2.ch03, e7]: y"])
    assert where.count("\n- ") <= 6 and "unrelated e7" not in where  # plain event ids (no dot) are not looked up: they match too much
    assert where_in_reply("nothing here", ["x [b2.ch09]: y"]) == ""
    assert _problem_key("a  b") == _problem_key("a b")
