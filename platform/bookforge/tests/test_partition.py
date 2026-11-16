"""The model names where each chapter starts; the tool cuts the act's events there. What used to need checks and repairs cannot be written any more."""

import copy
import structure_fakes as sf

from conftest import RuleLLM
from ledger_structure_fakes import chapters, dump, rules
from test_ledger_structure import HANDLERS, project_ready, run  # noqa: F401
from bookforge.bible import partition, store
from bookforge.bible.models import StoryEvent

ORDER = ["e1", "e2", "e3", "e4", "e5", "e6"]


def ch(*start, cont=None):
    c = {"title": "t"}
    if start:
        c["starts_with"] = start[0]
    if cont:
        c["events_continued"] = cont
    return c


def test_each_chapter_tells_the_stretch_from_its_starting_event_to_the_next_chapters_and_the_last_runs_to_the_end():
    raw = [ch("e1"), ch("e3"), ch("e4")]
    assert partition.assign(raw, ORDER) == []
    assert [c["events_covered"] for c in raw] == [["e1", "e2"], ["e3"], ["e4", "e5", "e6"]] and all("starts_with" not in c for c in raw)
    every = [x for c in raw for x in c["events_covered"]]
    assert every == ORDER  # every event once, in ledger order, whatever the model wrote


def test_the_first_chapter_takes_the_events_before_its_start_and_a_chapter_that_only_continues_tells_nothing_new():
    raw = [ch("e2"), ch(cont=["e2"]), ch("e4")]
    assert partition.assign(raw, ORDER) == []
    assert [c["events_covered"] for c in raw] == [["e1", "e2", "e3"], [], ["e4", "e5", "e6"]]
    spanning = [ch("e1"), ch("e2", cont=["e1"]), ch("e3")]
    partition.assign(spanning, ORDER)
    assert [c["events_covered"] for c in spanning] == [["e1"], ["e2"], ["e3", "e4", "e5", "e6"]]


def test_a_start_that_is_not_an_event_of_the_act_or_goes_backwards_is_handed_back_to_the_model():
    foreign = partition.assign([ch("e1"), ch("e9")], ORDER)
    assert len(foreign) == 1 and "'e9'" in foreign[0] and "not an event of this act" in foreign[0] and "e1, e2" in foreign[0]
    backwards = partition.assign([ch("e3"), ch("e2")], ORDER)
    assert len(backwards) == 1 and "later and later events" in backwards[0]
    twice = partition.assign([ch("e3"), ch("e3")], ORDER)
    assert len(twice) == 1
    bare = partition.assign([ch("e1"), ch()], ORDER)
    assert len(bare) == 1 and "neither `starts_with`" in bare[0]


def test_a_reply_that_still_lists_events_covered_is_taken_as_it_is():
    raw = [dict(title="t", events_covered=["e1"]), dict(title="t", events_covered=["e2"])]
    before = copy.deepcopy(raw)
    assert partition.assign(raw, ORDER) == [] and raw == before


def test_derived_complications_sit_right_after_their_parent_so_they_belong_to_the_chapter_that_tells_it():
    events = [StoryEvent(id=i, text="x", once_only=True, kind="event", weight=2, source="synopsis") for i in ("e1", "e2", "e3")]
    order = partition.act_order(events, ["e1", "e2", "e3"], [dict(id="e1.1", parent="e1"), dict(id="e1.2", parent="e1"), dict(id="e9.1", parent="e9")])
    assert order == ["e1", "e1.1", "e1.2", "e2", "e3"]  # a complication of an event outside the act is ignored
    raw = [ch("e1"), ch("e2")]
    partition.assign(raw, order)
    assert raw[0]["events_covered"] == ["e1", "e1.1", "e1.2"]


def starts_reply(first, starts):
    """The small book's chapters of one act, written the new way: only where each chapter starts."""
    out = copy.deepcopy(chapters(first))
    for c, s in zip(out["chapters"], starts):
        c.pop("events_covered")
        c["starts_with"] = s
    return out


def test_a_whole_act_planned_with_starting_events_is_saved_with_the_events_the_tool_cut(project):
    p = project_ready(project)
    act1 = starts_reply(1, ["e1", "e2"])
    summary = run(p, RuleLLM([("Plan the chapters this act's events need, b1.ch01 onward", dump(act1))] + rules()), HANDLERS, until="chapters")
    assert summary.ran == ["acts", "chapters"], summary.detail
    saved = {c.id: c.events_covered for c in store.load_chapters(p)}
    assert saved["b1.ch01"] == ["e1"] and saved["b1.ch02"] == ["e2"]


def test_a_start_the_act_does_not_own_is_corrected_by_the_model_not_left_to_you(project):
    p = project_ready(project)
    bad = starts_reply(1, ["e1", "e3"])  # e3 belongs to act 2
    llm = RuleLLM([("Plan the chapters this act's events need, b1.ch01 onward", dump(bad))] + rules()[:2])
    summary = run(p, llm, HANDLERS, until="chapters")
    assert summary.stopped == "failed"
    assert any("starts_with is 'e3', which is not an event of this act" in c["messages"][-1]["content"] for c in llm.calls)


def test_a_reply_with_both_starts_with_and_events_covered_is_read_by_starts_with_alone():
    raw = [dict(title="t", starts_with="e1", events_covered=["e1", "e2", "e3"]), dict(title="t", starts_with="e4", events_covered=["e9"])]
    assert partition.assign(raw, ORDER) == []
    assert [c["events_covered"] for c in raw] == [["e1", "e2", "e3"], ["e4", "e5", "e6"]]  # the second chapter's own list (e9) is ignored


def test_a_bad_start_hands_back_only_that_problem_not_a_wall_of_follow_on_errors(project):
    p = project_ready(project)
    bad = starts_reply(1, ["e3", "e4"])  # both belong to act 2
    llm = RuleLLM([("Plan the chapters this act's events need, b1.ch01 onward", dump(bad))] + rules()[:2])
    run(p, llm, HANDLERS, until="chapters")
    feedback = " ".join(c["messages"][-1]["content"] for c in llm.calls if "Your previous document has these problems" in c["messages"][-1]["content"])
    assert "starts_with is 'e3', which is not an event of this act" in feedback
    for noise in ("events_covered is empty", "chapter_without_events", "event_not_covered"):
        assert noise not in feedback


def test_the_chapters_prompt_names_the_acts_events_as_the_only_valid_starts_and_sums_up_the_long_done_list(project):
    from bookforge.ledger_view import status_text
    from bookforge.bible.models import Chapter, Ledger
    events = [StoryEvent(id=f"e{i}", text=f"event {i}", once_only=True, kind="event", weight=2, source="synopsis") for i in range(1, 9)]
    done_chapters = [Chapter(id=f"b2.ch{i:02d}", act="b2.act1", title="t", purpose="p", summary="s", pov="a", setting="b", tension=3, events_covered=[f"e{i}"]) for i in range(1, 6)]
    text = status_text(Ledger(events=events), {"e6", "e7"}, done_chapters, done_limit=2)
    assert "3 earlier events are told in the chapters before" in text and "- e4 " in text and "- e5 " in text and "- e1 " not in text and "- e3 " not in text
    assert "- e6 " in text and "- e8 " in text  # assigned here and reserved are untouched
    assert "- e1 " in status_text(Ledger(events=events), {"e6", "e7"}, done_chapters)  # the scenes prompt still lists them all


def test_the_chapters_prompt_carries_the_valid_starts_of_the_act(project):
    p = project_ready(project)
    llm = RuleLLM([("Plan the chapters this act's events need, b1.ch01 onward", dump(starts_reply(1, ["e1", "e2"])))] + rules())
    run(p, llm, HANDLERS, until="chapters")
    first = next(c["messages"][-1]["content"] for c in llm.calls if "Plan the CHAPTERS of one act" in c["messages"][-1]["content"])
    assert "Use ONLY these ids, in this order (they are the events of this act): e1, e2" in first


def test_a_possessive_is_the_same_name_in_the_unknown_name_check():
    from bookforge.bible.models import Constants, Entity
    from bookforge.validators import names as name_checks
    cast = Constants(entities=[Entity(id="eli-vance", kind="character", name="Eli Vance", facts=["a miner"]), Entity(id="halloway", kind="character", name="Foreman Halloway", facts=["a foreman"])])
    units = [dict(id="b2.ch12", purpose="Halloway's men reach the bay.", summary="Eli's plan fails and the Kestrel's engines wake.", end_state="The empty chair is Mara's.")]
    names = [n for f in name_checks.unknown_names(units, cast, "chapters") for n in f.message.split(" names ", 1)[1].split(", which")[0].split(", ")]
    assert "halloway's" not in names and "eli's" not in names and sorted(names) == ["kestrel", "mara"]  # the cast is the cast; real unknown names are still found


# ── scenes ─────────────────────────────────────────────────────────────────

def sc(*start, **kw):
    d = {"purpose": "p"}
    if start:
        d["starts_with"] = start[0]
    d.update(kw)
    return d


def test_each_scene_tells_the_stretch_from_its_starting_event_and_a_scene_with_no_start_goes_on_with_the_one_before():
    raw = [sc("e1"), sc(), sc("e3"), sc("e4")]
    assert partition.assign_scenes(raw, ["e1", "e2", "e3", "e4"], []) == []
    assert [s["events"] for s in raw] == [["e1", "e2"], [], ["e3"], ["e4"]] and all("starts_with" not in s for s in raw)


def test_the_first_scene_starts_with_the_chapters_first_event_and_takes_an_event_the_chapter_only_continues():
    raw = [sc("e2"), sc("e3")]
    assert partition.assign_scenes(raw, ["e1", "e2", "e3"], ["e0"]) == []
    assert [s["events"] for s in raw] == [["e0", "e1", "e2"], ["e3"]]
    bare = [sc(), sc()]  # no starts_with at all: the old shape, left as it is
    assert partition.assign_scenes(bare, ["e1"], []) == [] and "events" not in bare[0]
    carry_only = [sc(starts_with=None) | {"starts_with": None}]
    assert partition.assign_scenes(carry_only, [], ["e0"]) == [] and carry_only[0]["events"] == ["e0"]


def test_a_scene_start_the_chapter_does_not_own_or_that_goes_backwards_goes_back_to_the_model_alone():
    foreign = partition.assign_scenes([sc("e1"), sc("e9")], ["e1", "e2"], [])
    assert len(foreign) == 1 and "'e9'" in foreign[0] and "not an event of this chapter" in foreign[0] and "e1, e2" in foreign[0]
    back = partition.assign_scenes([sc("e2"), sc("e1")], ["e1", "e2"], [])
    assert len(back) == 1 and "later and later events" in back[0]
    both = [sc("e1", events=["e2"]), sc("e2", events=["e1"])]  # both fields: starts_with alone is read
    assert partition.assign_scenes(both, ["e1", "e2"], []) == [] and [s["events"] for s in both] == [["e1"], ["e2"]]


def test_story_days_are_added_up_from_days_later_and_cannot_run_backwards():
    from bookforge.bible import normalize
    raw = [dict(days_later=0), dict(days_later=2), dict(days_later=-3), dict(), dict(flashback=True, day=1), dict(days_later="soon"), dict(days_later=1)]
    normalize.derive_days(raw, None)
    assert [s["day"] for s in raw] == [1, 3, 3, 3, 1, 3, 4]  # a negative or unreadable number is today; a flashback has its own day and the story goes on from where it was
    assert "days_later" not in raw[1]
    old = [dict(day=5), dict(day=2)]
    normalize.derive_days(old, 4)
    assert [s["day"] for s in old] == [5, 2]  # absolute days are left as they were (and checked as before)
    follow = [dict(days_later=0), dict()]
    normalize.derive_days(follow, 7)
    assert [s["day"] for s in follow] == [7, 7]


def scenes_with_starts(ch, starts):
    out = copy.deepcopy(sf.scenes_reply(ch))
    for s, st in zip(out["scenes"], starts):
        s.pop("events", None)
        s.pop("id", None)
        if st:
            s["starts_with"] = st
    return out


def test_a_chapters_scenes_planned_with_starts_and_days_later_are_saved_with_the_events_and_days_the_tool_cut(project):
    import ledger_structure_fakes as lf
    p = project_ready(project)
    run(p, RuleLLM(rules()), HANDLERS, until="chapters")
    replies = []
    for ch in range(1, 5):
        r = lf.scenes(ch)
        for i, s in enumerate(r["scenes"]):
            s.pop("events", None)
            s.pop("id", None)
            s.pop("day", None)
            s["days_later"] = 0 if (ch == 1 and i == 0) else 1  # each scene a day after the one before: no two places at one moment
            if i == 0:
                s["starts_with"] = lf.COVER[ch][0]
        replies.append((f"Scene ids are consecutive: b1.ch{ch:02d}.s1", dump(r)))
    summary = run(p, RuleLLM(replies + rules()[:4]), HANDLERS, until="scenes")
    assert summary.ran == ["scenes"], summary.detail
    scenes = store.load_scenes(p)
    assert [s.id for s in scenes][:2] == ["b1.ch01.s1", "b1.ch01.s2"] and scenes[0].events == ["e1"] and scenes[1].events == []
    days = [t.day for t in store.load_timeline(p)]
    assert days == list(range(1, len(days) + 1))  # 0 then 1 day later each time: 1, 2, 3 ...


# ── acts ───────────────────────────────────────────────────────────────────

EV = ["e1", "e2", "e3", "e4", "e5", "e6", "e7", "e8"]


def act(*start, **kw):
    d = {"title": "t", "summary": "s", "purpose": "p", "turning_point": "x"}
    if start:
        d["starts_with"] = start[0]
    d.update(kw)
    return d


def test_each_act_takes_the_stretch_from_its_starting_event_and_gets_its_id_by_position():
    raw = [act("e1", id="wrong", events=["e5"], chapter_count=9), act("e4"), act("e7")]
    problems, notes = partition.assign_acts(raw, EV, ["e8"], "b2")
    assert problems == [] and notes == []
    assert [a["events"] for a in raw] == [["e1", "e2", "e3"], ["e4", "e5", "e6"], ["e7", "e8"]]
    assert [a["id"] for a in raw] == ["b2.act1", "b2.act2", "b2.act3"] and all("starts_with" not in a and "chapter_count" not in a for a in raw)


def test_the_first_act_starts_with_the_first_event_and_the_resolution_is_always_in_the_last_act():
    raw = [act("e2"), act("e5")]
    problems, notes = partition.assign_acts(raw, EV, ["e4"], "b2")  # the ending is event 4, but the last act was told to start at 5
    assert problems == [] and [a["events"] for a in raw] == [["e1", "e2", "e3"], ["e4", "e5", "e6", "e7", "e8"]]
    assert any("first act starts with e1" in n for n in notes) and any("holds the resolution" in n for n in notes)
    merged = [act("e1"), act("e3"), act("e6")]
    problems, notes = partition.assign_acts(merged, EV, ["e2"], "b2")  # the ending is event 2: the acts after it have nothing of their own
    assert problems == [] and [a["events"] for a in merged] == [["e1"], EV[1:]]  # the third act starts after the ending: merged away; the second is pulled back to hold it
    assert any("merged into the act before" in n for n in notes) and any("holds the resolution" in n for n in notes)


def test_an_act_start_that_is_not_an_event_or_goes_backwards_or_is_missing_goes_back_to_the_model_alone():
    p1, _ = partition.assign_acts([act("e1"), act("e99")], EV, [], "b2")
    assert len(p1) == 1 and "'e99'" in p1[0] and "e1, e2, e3" in p1[0]
    p2, _ = partition.assign_acts([act("e4"), act("e2")], EV, [], "b2")
    assert len(p2) == 1 and "later and later events" in p2[0]
    p3, _ = partition.assign_acts([act("e1"), act()], EV, [], "b2")
    assert len(p3) == 1 and "needs `starts_with`" in p3[0]
    old = [dict(id="b2.act1", events=["e1", "e2"]), dict(id="b2.act2", events=["e3"])]  # no starts_with at all: left as it is
    assert partition.assign_acts(old, EV, [], "b2") == ([], []) and old[0]["events"] == ["e1", "e2"]


def numbered(*events_per_act, weights, decision=None, ending=None):
    from bookforge.bible import normalize
    evs = [StoryEvent(id=f"e{i}", text=f"event {i}", once_only=True, kind="event", weight=weights[i - 1], source="synopsis", decision=(decision == f"e{i}"),
                      ending=(ending == f"e{i}")) for i in range(1, len(weights) + 1)]
    from bookforge.bible.models import Ledger
    ledger = Ledger(events=evs)
    raw = [dict(title="t", summary="s", purpose="p", turning_point="x", events=list(e)) for e in events_per_act]
    normalize.derive_act_numbers(raw, ledger, 2.0)
    return raw


def test_chapter_counts_come_from_the_ledgers_weights_and_add_up_to_its_estimate_and_the_text_is_the_computed_note():
    raw = numbered(["e1", "e2", "e3"], ["e4", "e5", "e6"], ["e7", "e8"], weights=[3, 2, 2, 3, 2, 2, 2, 2])  # weights 7, 7, 4: 3.5 + 3.5 + 2 = 9 chapters
    assert [a["chapter_count"] for a in raw] == [4, 3, 2] and sum(a["chapter_count"] for a in raw) == 9
    assert all(a["sizing_reason"].startswith("[computed: weight") for a in raw) and "weight 7 over 3 events" in raw[0]["sizing_reason"]
    thin = numbered(["e1"], ["e2"], weights=[1, 1])  # never fewer than a chapter
    assert [a["chapter_count"] for a in thin] == [1, 1]
    capped = numbered(["e1"], ["e2"], weights=[3, 2])  # one event of weight 3 can supply at most 3 chapters (itself, a second, a complication): 1.5 -> 2 is fine
    assert capped[0]["chapter_count"] <= 3


def test_the_turning_point_is_the_acts_last_event_and_the_books_last_turning_point_is_the_decision_or_the_resolution():
    raw = numbered(["e1", "e2", "e3"], ["e4", "e5", "e6", "e7", "e8"], weights=[2] * 8, decision="e7", ending="e8")
    assert [a["turning_point_event"] for a in raw] == ["e3", "e7"]  # the decision is in the second half of the last act
    early = numbered(["e1", "e2"], ["e3", "e4", "e5", "e6", "e7"], weights=[2] * 7, decision="e3", ending="e7")
    assert early[1]["turning_point_event"] == "e7"  # the decision opens the act: the resolution ends it
    none = numbered(["e1", "e2"], ["e3", "e4"], weights=[2] * 4)
    assert [a["turning_point_event"] for a in none] == ["e2", "e4"]


def test_a_whole_book_planned_with_act_starts_is_saved_with_the_events_numbers_and_turning_points_the_tool_derived(project):
    import ledger_structure_fakes as lf
    p = project_ready(project)
    new = {"acts": [dict(title="Act one", summary="Anna finds the ledger and crosses a name out.", purpose="Set the trap.", turning_point="The name is crossed out.", starts_with="e1"),
                    dict(title="Act two", summary="Jonas learns the truth and Anna burns the ledger.", purpose="Spring the trap.", turning_point="The ledger burns.", starts_with="e3")]}
    rest = [r for r in rules() if not r[0].startswith("Divide the book into ACTS")]
    summary = run(p, RuleLLM([("Divide the book into ACTS by assigning", dump(new))] + rest), HANDLERS, until="chapters")
    assert summary.ran == ["acts", "chapters"], summary.detail
    acts = store.load_acts(p)
    assert [a.id for a in acts] == ["b1.act1", "b1.act2"] and [a.events for a in acts] == [["e1", "e2"], ["e3", "e4"]]
    assert [a.turning_point_event for a in acts] == ["e2", "e4"] and [a.chapter_count for a in acts] == [2, 2]
    assert all(a.sizing_reason.startswith("[computed: weight 4 over 2 events") for a in acts)


def test_a_bad_act_start_is_handed_back_and_nothing_else_is_asked(project):
    p = project_ready(project)
    bad = {"acts": [dict(title="a", summary="s", purpose="p", turning_point="x", starts_with="e1"), dict(title="b", summary="s", purpose="p", turning_point="x", starts_with="e9")]}
    llm = RuleLLM([("Divide the book into ACTS by assigning", dump(bad))])
    run(p, llm, HANDLERS, until="acts")
    feedback = " ".join(c["messages"][-1]["content"] for c in llm.calls if "Your previous document has these problems" in c["messages"][-1]["content"])
    assert "starts_with is 'e9', which is not an event of the book" in feedback
    for noise in ("event_in_no_act", "turning_point_without_event", "chapter_count", "sizing_reason"):
        assert noise not in feedback
