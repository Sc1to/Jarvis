"""A chapter may claim only the changes its own events bring about; the same change told twice in different words is a repeat."""

from bookforge.validators import HARD, state_claims as S


def ev(i, text, **kw):
    return dict(id=i, text=text, once_only=True, **kw)


def ch(i, events, end_state, summary=""):
    return dict(id=f"b2.ch{i:02d}", events_covered=events, end_state=end_state, summary=summary)


EVENTS = [ev("e10", "Eli decides to broadcast the data to the whole network"), ev("e12", "Eli uploads the data, triggering a lockdown and worsening Mara's condition")]


def test_a_chapter_about_deciding_must_not_end_with_it_done():
    chapters = [ch(10, ["e10"], "Eli has chosen. The data is now public on the local network.", "Eli decides to share what he found."),
                ch(11, [], "x"), ch(12, ["e12"], "The lockdown begins.")]
    found = S.end_state_overreach(chapters, EVENTS)
    assert [(f.code, f.severity, f.items[:2]) for f in found] == [("end_state_overreach", HARD, ["b2.ch10", "e12"])] and len(found[0].evidence) == 2


def test_an_end_state_that_stays_within_its_events_passes():
    chapters = [ch(10, ["e10"], "Eli has chosen to share the data but has not yet done it."), ch(12, ["e12"], "The data is public and the lockdown begins.")]
    assert S.end_state_overreach(chapters, EVENTS) == []


def test_the_same_change_in_different_words_is_a_repeat_but_unrelated_events_are_not():
    chapters = [ch(10, ["e10"], "x"), ch(12, ["e12"], "y")]
    found = S.state_change_repeated(chapters, EVENTS)
    assert found and found[0].code == "state_change_repeated" and found[0].items[2:] == ["e10", "e12"]
    other = [ev("e1", "Mara repairs the engine"), ev("e2", "Corso arrests the inspector")]
    assert S.state_change_repeated([ch(1, ["e1"], ""), ch(2, ["e2"], "")], other) == []
