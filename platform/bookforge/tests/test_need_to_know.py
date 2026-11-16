"""A planner is never shown what comes later: a model shown a fact and told to ignore it uses it (b2.ch15.s2 described e19, which ch18 tells)."""

import re

import ledger_structure_fakes as lf
from conftest import RuleLLM
from test_ledger_structure import HANDLERS, project_ready, run  # noqa: F401
from test_prose_qc import book  # noqa: F401  (a fixture)
from ledger_structure_fakes import dump, rules
from bookforge.bible import store
from bookforge.ledger_view import NOT_YET, status_text
from bookforge.bible.models import Chapter, Ledger, StoryEvent

TOKENS = {"e1": "ZQVONE", "e2": "ZQVTWO", "e3": "ZQVTHREE", "e4": "ZQVFOUR"}


def tokened_ledger():
    base = dict(once_only=True, kind="event", weight=2, source="synopsis")
    texts = {"e1": "Anna finds the ledger", "e2": "Anna crosses a name out", "e3": "Jonas learns the truth", "e4": "Anna burns the ledger"}
    after = {"e1": [], "e2": ["e1"], "e3": ["e2"], "e4": ["e3"]}
    return Ledger(events=[StoryEvent(id=i, text=f"{texts[i]} {TOKENS[i]}", after=after[i], ending=(i == "e4"), **base) for i in texts],
                  capacity={"estimated_chapters": 4.0, "thin": False})


def shows(prompt: str, ev: str) -> bool:
    return TOKENS[ev] in prompt or re.search(rf"\b{ev}\b", prompt) is not None


def users(llm, marker: str) -> list[str]:
    return [next(m["content"] for m in c["messages"] if m["role"] == "user") for c in llm.calls if marker in c["messages"][-1]["content"]]


def planned_with_tokens(project):
    p = project_ready(project)
    store.save_ledger(p, tokened_ledger())  # the same events, with texts only their own prompts may carry
    llm = RuleLLM(rules())
    run(p, llm, HANDLERS, until="scenes")
    return p, llm


def test_the_text_and_id_of_a_later_event_never_reach_a_chapter_or_scene_planner(project):
    p, llm = planned_with_tokens(project)
    act1 = users(llm, "events need, b1.ch01 onward")[0]  # act 1 tells e1, e2
    assert shows(act1, "e1") and shows(act1, "e2") and not shows(act1, "e3") and not shows(act1, "e4") and NOT_YET in act1
    act2 = users(llm, "events need, b1.ch03 onward")[0]  # act 2 tells e3, e4; e1 and e2 are the past
    assert shows(act2, "e3") and shows(act2, "e4") and shows(act2, "e1")
    for ch, tells in ((1, "e1"), (2, "e2"), (3, "e3"), (4, "e4")):
        scene_prompt = users(llm, f"Scene ids are consecutive: b1.ch{ch:02d}.s1")[0]
        later = [e for e in TOKENS if int(e[1:]) > int(tells[1:])]
        assert shows(scene_prompt, tells), f"ch{ch} must see its own event"
        for e in later:
            assert not shows(scene_prompt, e), f"the scene planner of ch{ch} saw {e}, which is told later"


def test_the_status_text_can_hide_the_future_and_still_lists_the_past_and_the_present():
    led = tokened_ledger()
    done = [Chapter(id="b1.ch01", act="b1.act1", title="t", purpose="p", summary="s", pov="a", setting="b", tension=3, events_covered=["e1"])]
    hidden = status_text(led, {"e2"}, done, future="hidden")
    assert shows(hidden, "e1") and shows(hidden, "e2") and not shows(hidden, "e3") and not shows(hidden, "e4") and NOT_YET in hidden and "RESERVED" not in hidden
    shown = status_text(led, {"e2"}, done)  # the acts stage and the plan reviewer still see everything
    assert shows(shown, "e3") and shows(shown, "e4") and "RESERVED FOR LATER" in shown
    nothing_later = status_text(led, {"e1", "e2", "e3", "e4"}, [], future="hidden")
    assert NOT_YET not in nothing_later  # nothing is left to hide


def test_a_scene_briefing_carries_no_event_of_a_later_chapter(project):
    from bookforge import briefing
    p, _ = planned_with_tokens(project)
    seen = {}
    for sid, tells in (("b1.ch01.s1", "e1"), ("b1.ch02.s1", "e2"), ("b1.ch03.s1", "e3")):
        text = briefing.build_briefing(p, sid).text()
        assert "Not yet: story events" not in text and "reserved for later" not in text.lower()
        for e in TOKENS:
            if int(e[1:]) > int(tells[1:]):
                assert not shows(text, e), f"the briefing of {sid} carries {e}, which is told later"
        seen[sid] = text
    assert seen["b1.ch01.s1"]  # the briefing itself is still built


def test_a_scene_written_before_this_change_is_not_made_stale_by_the_reserved_section_going_away():
    from bookforge.deps import Deps, diff, tag
    old = Deps(bible=[tag("ledger:reserved", "- e3: something")])
    assert diff(old, Deps()) == []
