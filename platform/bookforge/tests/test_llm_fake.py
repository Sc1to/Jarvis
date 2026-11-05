import pytest

from bookforge.llm import FakeLLMClient, FakeLLMExhausted

MSG = [{"role": "user", "content": "hi"}]


def test_replies_are_consumed_in_order_per_role():
    llm = FakeLLMClient({"critic": ["c1", "c2"], "writer": ["w1"]})
    assert llm.complete("critic", MSG) == "c1"
    assert llm.complete("writer", MSG) == "w1"
    assert llm.complete("critic", MSG) == "c2"


def test_exhausted_script_fails_loudly():
    llm = FakeLLMClient({"critic": ["only"]})
    llm.complete("critic", MSG)
    with pytest.raises(FakeLLMExhausted):
        llm.complete("critic", MSG)
    with pytest.raises(FakeLLMExhausted):
        llm.complete("writer", MSG)


def test_wildcard_and_callable_replies():
    llm = FakeLLMClient({"*": [lambda m: m[0]["content"].upper()]})
    assert llm.complete("writer", MSG) == "HI"


def test_calls_are_recorded_with_options():
    llm = FakeLLMClient({"critic": ["x"]})
    llm.complete("critic", MSG, temperature=0.2)
    assert llm.calls == [{"role": "critic", "messages": MSG, "options": {"temperature": 0.2}}]


def test_instances_do_not_share_state():
    a, b = FakeLLMClient(), FakeLLMClient()
    a.calls.append({})
    assert b.calls == []
