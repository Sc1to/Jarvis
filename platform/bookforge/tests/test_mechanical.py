import pytest

from bookforge.config import QC
from bookforge.qc.mechanical import (
    CheckContext, check_scene, load_banned, narration, repeated_spans, sentences, suggest_phrases, words,
)
from prose_fakes import prose

BASE = prose(0, 24)


def ctx(**kw) -> CheckContext:
    kw.setdefault("scene_words", (100, 600))
    return CheckContext(**kw)


def codes(report, severity=None):
    return [i.code for i in report.issues if severity is None or i.severity == severity]


# ── helpers ─────────────────────────────────────────────────────────────────

def test_the_baseline_prose_passes_every_check_cleanly():
    r = check_scene(BASE, ctx())
    assert r.issues == [], [(i.code, i.message) for i in r.issues]
    assert 200 < r.stats["words"] < 600 and r.stats["dialogue_ratio"] > 0.05 and r.score == 0


def test_text_helpers():
    assert words("Don't stop-me now, it’s 12") == ["Don't", "stop-me", "now", "it’s", "12"]
    assert narration('He said "stop right there" and left.').split() == ["He", "said", "and", "left."]
    assert narration("She said “no” and «non» and „nein“.").split() == ["She", "said", "and", "and", "."]
    assert len(sentences("One two. Three four! Five six? Seven.")) == 4
    assert load_banned("# comment\n\n  a phrase  \nre:x+\n") == ["a phrase", "re:x+"]


# ── banned phrases and formatting ───────────────────────────────────────────

def test_banned_phrases_block_and_point_at_the_text():
    text = BASE + "\n\nShe felt a shiver  down\nher spine as it ended."
    r = check_scene(text, ctx(banned=["shiver down her spine"]))
    [issue] = [i for i in r.issues if i.code == "banned_phrase"]
    assert issue.severity == "block" and text[issue.start:issue.end].lower().split() == ["shiver", "down", "her", "spine"]
    assert "shiver" in issue.excerpt and r.score >= 100


def test_banned_entries_respect_word_boundaries_and_regexes():
    assert "banned_phrase" not in codes(check_scene(BASE + " The orbital station hummed.", ctx(banned=["orb"])))
    assert "banned_phrase" in codes(check_scene(BASE + " Her orb glowed.", ctx(banned=["orb"])))
    assert "banned_phrase" in codes(check_scene(BASE + " Suddenly, she realized it.", ctx(banned=[r"re:\bsuddenly,? (she|he) realized"])))


def test_an_unusable_regex_is_skipped_not_fatal():
    r = check_scene(BASE, ctx(banned=["re:(unclosed", "fine phrase"]))
    assert r.issues == [] and any("not usable" in s for s in r.skipped)


@pytest.mark.parametrize("text", [
    "Sure! Here is the scene:\n\n" + BASE,
    BASE + "\n\nI hope this works for you. Let me know if you want changes.",
    "# Scene 3\n\n" + BASE,
    BASE + "\n\n- a bullet\n- another",
    "```\n" + BASE + "\n```",
])
def test_chatter_and_formatting_block(text):
    assert {"chatter", "formatting"} & set(codes(check_scene(text, ctx()), "block"))


# ── length and endings ──────────────────────────────────────────────────────

def test_length_warns_then_blocks():
    n = len(words(BASE))
    assert "length" not in codes(check_scene(BASE, ctx(scene_words=(100, 600))))
    warn = check_scene(BASE, ctx(scene_words=(n + 20, n + 400)))
    assert [(i.code, i.severity) for i in warn.issues if i.code == "length"] == [("length", "warn")]
    block = check_scene(BASE, ctx(scene_words=(n * 3, n * 6)))
    assert [(i.code, i.severity) for i in block.issues if i.code == "length"] == [("length", "block")]
    too_long = check_scene(BASE, ctx(scene_words=(10, n // 3)))
    assert ("length", "block") in [(i.code, i.severity) for i in too_long.issues]


def test_a_text_that_stops_mid_sentence_is_flagged_as_cut_off():
    cut = BASE[: BASE.rindex(".")] + " and then she"
    assert "cut_off" in codes(check_scene(cut, ctx()), "block")
    assert "cut_off" not in codes(check_scene(BASE + ' "Yes."', ctx()))


# ── repetition ──────────────────────────────────────────────────────────────

def test_phrases_repeated_from_earlier_scenes_are_reported_once_merged():
    earlier = [prose(0, 24), prose(0, 24), "Unrelated words about an entirely different afternoon at sea."]
    r = check_scene(BASE, ctx(earlier_texts=earlier))
    reps = [i for i in r.issues if i.code == "repeated_phrase"]
    assert reps and all(i.severity == "warn" for i in reps) and "already appears in 2 earlier scenes" in reps[0].message
    assert len(reps) <= 5


def test_one_earlier_scene_is_not_enough_by_default():
    assert "repeated_phrase" not in codes(check_scene(BASE, ctx(earlier_texts=[prose(0, 24)])))
    qc = QC(repeat_ngram_scenes=1)
    assert "repeated_phrase" in codes(check_scene(BASE, ctx(earlier_texts=[prose(0, 24)], qc=qc)))


def test_stopword_only_phrases_do_not_count_as_repetition():
    filler = "it was in the and of the to a"
    assert repeated_spans(filler, [filler, filler], 5, 2) == []


def test_a_phrase_repeated_inside_the_scene_is_reported():
    text = BASE + " " + " ".join(["She counted the names on the page again."] * 3)
    assert any("appears" in i.message and "times in this scene" in i.message for i in check_scene(text, ctx()).issues)


def test_suggested_phrases_need_to_appear_in_many_scenes():
    texts = [prose(i, 10) + " A cold wind from the sea." for i in range(5)] + ["Nothing in common here at all."]
    suggestions = dict(suggest_phrases(texts, size=4, min_scenes=4))
    assert "a cold wind from" in suggestions and suggestions["a cold wind from"] == 5
    assert suggest_phrases(texts, size=4, min_scenes=7) == []


# ── words, rhythm, dialogue ─────────────────────────────────────────────────

def test_an_overused_word_is_flagged_but_names_are_not():
    text = BASE + " " + " ".join(["The lantern swung."] * 10)
    assert any(i.code == "overused_word" and "lantern" in i.message for i in check_scene(text, ctx()).issues)
    verbs = ["nodded", "frowned", "paused", "blinked", "sighed", "stood", "turned", "smiled", "coughed", "waited", "stared", "slept"]
    named = BASE + " " + " ".join(f"Voss {v}." for v in verbs)
    assert "overused_word" not in codes(check_scene(named, ctx(names={"anna": "Anna Voss"})))
    assert "overused_word" in codes(check_scene(named, ctx(names={})))


def test_monotone_sentence_length_is_flagged():
    text = " ".join(["The boat moved slowly through the harbour."] * 12)
    assert "monotone_rhythm" in codes(check_scene(text, ctx(scene_words=(10, 600))))


def test_very_long_sentences_and_repeated_openings():
    long = "She walked " + " and then ".join(["along the quay"] * 30) + "."
    assert "long_sentence" in codes(check_scene(BASE + " " + long, ctx()))
    opening = BASE + " " + " ".join(f"She {v} the door." for v in ("opened", "closed", "locked", "tried"))
    assert "repeated_openings" in codes(check_scene(opening, ctx()))


def test_dialogue_ratio_outside_the_range_warns_only_for_real_scenes():
    narrated = " ".join(["Anna walked along the quay while the fog thickened and the lamps burned."] * 3 + ["Then the bell rang once and she stopped to listen."] * 3)
    assert "dialogue_ratio" in codes(check_scene(" ".join([narrated] * 4), ctx(scene_words=(10, 1200))))
    all_talk = " ".join(f'"Line number {i} of the long argument that never ended."' for i in range(30))
    assert "dialogue_ratio" in codes(check_scene(all_talk, ctx(scene_words=(10, 900))))
    short = "A short line without any dialogue at all."
    assert "dialogue_ratio" not in codes(check_scene(short, ctx(scene_words=(1, 900))))


# ── recap, tense, point of view ─────────────────────────────────────────────

def test_an_opening_that_repeats_the_previous_scene_is_flagged():
    tail = " ".join(BASE.split()[-120:])
    text = " ".join(tail.split()[-60:]) + " " + prose(14, 16)
    assert "recap" in codes(check_scene(text, ctx(previous_tail=tail)))
    assert "recap" not in codes(check_scene(BASE, ctx(previous_tail="A completely different last scene ended here, quietly.")))


def test_tense_slips_are_reported_for_english_only():
    present = " ".join(["Anna is walking and she has the ledger and the town does not know it, so she can hide it."] * 3
                       + ["The fog is thick and it will not lift."] * 3)
    assert "tense_slip" in codes(check_scene(present, ctx(tense="past", scene_words=(10, 900))))
    assert "tense_slip" not in codes(check_scene(present, ctx(tense="present", scene_words=(10, 900))))
    german = check_scene(present, ctx(tense="past", language="German", scene_words=(10, 900)))
    assert "tense_slip" not in codes(german) and any("English-only" in s for s in german.skipped)


def test_pov_slips():
    first = BASE + " I thought my life was over, and we all knew it was our fault, and I wept."
    assert "pov_slip" in codes(check_scene(first, ctx(pov="third-limited")))
    assert "pov_slip" not in codes(check_scene(first, ctx(pov="first")))
    assert "pov_slip" in codes(check_scene(BASE + " The fog covered every roof in the lower town for miles around the bay.", ctx(pov="first", scene_words=(10, 900))))
    assert "pov_slip" not in codes(check_scene(BASE, ctx(pov="third-limited")))


def test_head_hopping_is_flagged_for_other_characters_thoughts_only():
    names = {"anna": "Anna Voss", "jonas": "Jonas Reil"}
    hop = BASE + " Jonas wondered whether she would ever forgive him."
    r = check_scene(hop, ctx(names=names, pov_id="anna"))
    assert "head_hop" in codes(r) and "Jonas" in [i for i in r.issues if i.code == "head_hop"][0].message
    own = BASE + " Anna wondered whether he would ever forgive her."
    assert "head_hop" not in codes(check_scene(own, ctx(names=names, pov_id="anna")))
    assert "head_hop" not in codes(check_scene(hop, ctx(names=names, pov_id="anna", pov="third-omniscient")))


# ── report ──────────────────────────────────────────────────────────────────

def test_score_orders_drafts_and_the_report_serialises():
    clean = check_scene(BASE, ctx())
    warned = check_scene(BASE + " " + " ".join(["The lantern swung."] * 10), ctx())
    blocked = check_scene(BASE, ctx(banned=["harbour bell"]))
    assert clean.score < warned.score < blocked.score
    d = blocked.to_dict()
    assert d["score"] == blocked.score and d["issues"][0]["code"] == "banned_phrase" and "words" in d["stats"]
