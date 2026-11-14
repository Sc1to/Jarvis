"""The validators against the known-bad fixtures (test data, tests/fixtures/known_bad): each failure pattern must be caught,
and the good ledger must pass. Patterns, not story content: the same checks run on any book."""

import copy
from pathlib import Path

import pytest
import yaml

from bookforge.validators import HARD, SOFT
from bookforge.validators import ledger as L, prose as P, repeats as R, research_leak as RL, state as S, tension as T

FIX = Path(__file__).parent / "fixtures" / "known_bad"


def load(name):
    return yaml.safe_load((FIX / name).read_text(encoding="utf-8"))


def codes(findings, severity=None):
    return {f.code for f in findings if severity is None or f.severity == severity}


SYN = (FIX / "synopsis.md").read_text(encoding="utf-8")
EVENTS = load("ledger.yaml")["events"]
ACTS = load("acts.yaml")["acts"]
CHAPTERS = load("chapters.yaml")["chapters"]
SCENES = load("scenes.yaml")["scenes"]


# ── ledger ──────────────────────────────────────────────────────────────────

def test_good_ledger_passes():
    assert [f.line() for f in L.check_ledger(EVENTS, SYN)] == []


def test_missing_resolution_is_caught():
    ev = [e for e in copy.deepcopy(EVENTS) if not e["ending"]]
    c = codes(L.check_ledger(ev, SYN), HARD)
    assert "no_resolution" in c and "synopsis_not_covered" in c  # the final paragraph has no event


def test_setup_without_payoff_and_reveal_before_setup():
    ev = copy.deepcopy(EVENTS)
    next(e for e in ev if e["id"] == "e9")["pays_off"] = ""
    ev9 = next(e for e in ev if e["id"] == "e9")
    ev9["kind"] = "event"
    assert "setup_without_payoff" in codes(L.check_ledger(ev, SYN), HARD)
    ev = copy.deepcopy(EVENTS)
    a, b = [i for i, e in enumerate(ev) if e["id"] in ("e7", "e9")]
    ev[a], ev[b] = ev[b], ev[a]
    assert "reveal_before_setup" in codes(L.check_ledger(ev, SYN), HARD)


def test_cycles_unknown_ids_duplicates():
    ev = copy.deepcopy(EVENTS)
    ev[0]["after"] = ["e3"]
    ev[2]["after"] = ["e1"]
    assert "event_cycle" in codes(L.check_ledger(ev, SYN))
    ev = copy.deepcopy(EVENTS)
    ev[1]["after"] = ["e99"]
    assert "unknown_event" in codes(L.check_ledger(ev, SYN))
    ev = copy.deepcopy(EVENTS) + [copy.deepcopy(EVENTS[0])]
    assert "duplicate_event_id" in codes(L.check_ledger(ev, SYN))


def test_excerpt_must_quote_the_synopsis():
    ev = copy.deepcopy(EVENTS)
    ev[3]["excerpt"] = "something the synopsis never says"
    assert "excerpt_not_in_synopsis" in codes(L.check_ledger(ev, SYN), HARD)


def test_derived_events_are_minor_children():
    ev = copy.deepcopy(EVENTS)
    child = dict(id="e3.1", text="a guard nearly spots her", once_only=True, after=["e3"], kind="event", weight=1, source="derived", parent="e3", ending=False, pays_off="")
    ev.insert(3, child)
    assert [f for f in L.check_ledger(ev, SYN) if f.severity == HARD] == []
    major = {**child, "weight": 3}
    assert "derived_not_minor" in codes(L.check_ledger([*ev[:3], major, *ev[4:]], SYN), HARD)
    orphan = {**child, "parent": "e99"}
    assert "derived_without_parent" in codes(L.check_ledger([*ev[:3], orphan, *ev[4:]], SYN), HARD)
    first = {**child, "id": "e3.1"}
    before = [first, *ev[:3], *ev[4:]]
    assert "event_order" in codes(L.check_ledger(before, SYN), HARD)


# ── acts ────────────────────────────────────────────────────────────────────

def test_acts_missing_resolution_turning_point_and_oversized_act():
    c = codes(L.check_acts(ACTS, EVENTS))
    assert "event_in_no_act" in c  # e10 belongs to no act
    assert "resolution_not_in_last_act" in c
    assert "turning_point_without_event" in c
    assert "implausible_chapter_count" in c  # act 1: 8 chapters for 5 weight
    assert "event_in_two_acts" not in c


def test_event_in_two_acts():
    acts = copy.deepcopy(ACTS)
    acts[1]["events"].append("e3")
    assert "event_in_two_acts" in codes(L.check_acts(acts, EVENTS), HARD)


# ── chapters ────────────────────────────────────────────────────────────────

def test_chapters_repeat_once_only_and_leave_events_uncovered():
    f = L.check_chapters(CHAPTERS, EVENTS, ACTS)
    c = codes(f, HARD)
    assert {"once_only_repeated", "event_not_covered", "chapter_nothing_new"} <= c
    repeated = {x for ff in f if ff.code == "once_only_repeated" for x in ff.items if x.startswith("e")}
    assert {"e3", "e5", "e4", "e8"} <= repeated or {"e3", "e8"} <= repeated
    uncovered = {x for ff in f if ff.code == "event_not_covered" for x in ff.items}
    assert "e7" in uncovered  # the turning point of the last act has no chapter


def test_repeated_events_by_meaning_in_plain_text():
    f = R.repeated_events(CHAPTERS, SCENES, names={"mara", "corso"})
    c = codes(f)
    assert "event_repeated" in c
    pairs = {tuple(x.items) for x in f if x.code == "chapter_replans_chapter"}
    assert any({"t.ch05", "t.ch07"} <= set(p) for p in pairs)  # ch07 replans ch05
    texts = " ".join(" ".join(x.items) for x in f if x.code == "event_repeated")
    assert "t.ch04" in texts and "t.ch08" in texts  # the drive found twice
    assert "t.ch06" in texts and "t.ch11" in texts  # the launch twice
    assert "t.ch02" in texts and "t.ch03" in texts  # the entry twice


def test_distinct_chapters_do_not_trigger_repeats():
    ch = [dict(id=f"x.ch{i:02d}", summary=s) for i, s in enumerate([
        "A baker opens a shop on the corner and argues with the landlord about rent.",
        "The landlord's nephew arrives from the coast carrying a mysterious letter.",
        "The baker reads the letter aloud and learns of an inheritance in another city.",
        "A storm floods the cellar and ruins the flour stores.",
        "The baker travels north by coach and meets a retired surveyor.",
        "The surveyor shows a map that explains the inheritance clause."], 1)]
    assert R.repeated_events(ch, []) == []


def test_action_pattern_repeated_across_chapters():
    scenes = []
    for i in range(1, 11):
        scenes.append(dict(id=f"z.ch{i:02d}.s1", chapter=f"z.ch{i:02d}", beats=[
            "Nia forces the rusted lock on the gate." if i in (1, 2, 3, 4, 5, 6, 7) else f"Nia argues with a stranger number {i} about wages.", f"A different thing {chr(96 + i) * 4} happens."]))
    chapters = [dict(id=f"z.ch{i:02d}") for i in range(1, 11)]
    f = R.action_patterns(scenes, chapters)
    assert f and f[0].code == "action_pattern_repeated" and f[0].severity == HARD
    assert R.action_patterns(scenes[:5], chapters[:5]) == []


def test_action_patterns_in_fixture():
    f = R.action_patterns(SCENES, CHAPTERS, names={"mara"})
    assert "action_pattern_repeated" in codes(f)


# ── research ────────────────────────────────────────────────────────────────

def test_research_terms_in_beats():
    notes = [n["claim"] for n in load("research_notes.yaml")["notes"]]
    story = [SYN, " ".join(e["text"] for e in EVENTS)]
    f = RL.research_in_beats(SCENES, notes, story)
    assert "research_in_beats" in codes(f, HARD)  # one term in 3+ scenes
    terms = " ".join(x.message for x in f)
    assert "kurtosis" in terms or "61508" in terms


def test_research_terms_known_to_the_story_are_not_leaks():
    notes = ["Spectral kurtosis helps detect faults."]
    assert RL.research_in_beats(SCENES, notes, [SYN, "spectral kurtosis is the heroine's trade"]) == []


# ── state ───────────────────────────────────────────────────────────────────

def test_state_flip_back_two_places_and_days():
    tracks = load("tracks.yaml")["tracks"]
    assert "state_regression" in codes(S.track_regressions(tracks), HARD)
    fixed = copy.deepcopy(tracks)
    fixed[0]["plan"][2]["cause"] = "the deal is torn up"
    assert S.track_regressions(fixed) == []
    assert "two_places_at_once" in codes(S.location_conflicts([], [], tracks), HARD)
    scenes = [dict(id="t.ch01.s1", setting="a", characters=["x"]), dict(id="t.ch01.s2", setting="b", characters=["x"])]
    tl = [dict(id="t.ch01.s1", day=3, time="noon"), dict(id="t.ch01.s2", day=3, time="noon")]
    assert "two_places_at_once" in codes(S.location_conflicts(scenes, tl))
    assert "story_day_backwards" in codes(S.day_regressions(
        [dict(id="t.ch02.s1"), dict(id="t.ch03.s1")], load("timeline.yaml")["scenes"][1:]))


# ── tension ─────────────────────────────────────────────────────────────────

def test_flat_tension():
    f = T.flat_stretches(CHAPTERS)
    assert f and f[0].code == "flat_tension"
    varied = [dict(id=f"c{i}", tension=t) for i, t in enumerate([2, 5, 3, 7, 4, 9, 3, 6, 2, 8, 5, 10], 1)]
    assert T.flat_stretches(varied) == []


# ── prose ───────────────────────────────────────────────────────────────────

def _prose():
    return [(p.stem, p.read_text(encoding="utf-8")) for p in sorted((FIX / "prose").glob("*.md"))]


def test_prose_copies_and_wrap_ups():
    pr = _prose()
    assert "sentences_repeated" in codes(P.repeated_sentences(pr), HARD)
    assert "chapter_opens_with_previous_ending" in codes(P.chapter_openings_copy(pr), HARD)
    w = P.wrap_up_endings(pr)
    assert codes(w) == {"wrap_up_ending"} and all(x.severity == SOFT for x in w)  # soft only


def test_clean_prose_passes():
    pr = [("a", "The kettle boiled over and hissed on the stove. Ines wiped the counter twice, then opened the window."),
          ("b", "Rain came sideways across the car park. A courier ran for the shelter, holding a box over his head.")]
    assert P.repeated_sentences(pr) == [] and P.chapter_openings_copy(pr) == [] and P.wrap_up_endings(pr) == []


def test_tic_report_flags_habits():
    scenes = [(f"s{i}", f"Anna felt a heavy silence. The silence was heavy and the room hummed with a low hum number {i}. " * 5 + f"Unique thing {chr(97 + i) * 5}.") for i in range(8)]
    f, report = P.tic_report(scenes)
    assert f and any("silence" in x.message for x in f) and report["top"]


def test_a_payoff_that_resolves_something_else_is_flagged_softly():
    ev = copy.deepcopy(EVENTS)
    next(e for e in ev if e["id"] == "e9")["text"] = "A storm passes over the harbor"
    f = [x for x in L.check_ledger(ev, SYN) if x.code == "payoff_unrelated_to_setup"]
    assert f and f[0].severity == SOFT


@pytest.mark.real_prose_checks
def test_book_level_prose_checks_are_saved_and_a_clean_book_passes(project):
    from bookforge import scenefiles
    from bookforge.bible import store
    from bookforge.validators.book import prose_findings
    from structure_fakes import ready, rules, small
    from conftest import RuleLLM
    from bookforge.layers import HANDLERS
    from bookforge.layers.runner import run
    p = ready(project)
    run(p, RuleLLM(rules()), HANDLERS, until="scenes")
    sc = store.load_scenes(p)
    same = "The harbor was quiet and Anna walked along the wet planks toward the vestry door. "
    for s in sc[:3]:
        scenefiles.scene_dir(p, s.id).mkdir(parents=True, exist_ok=True)
        scenefiles.final_path(p, s.id).write_text(same * 5 + f"Then something unique {s.id} happened at last.")
    found, _ = prose_findings(p)
    assert "sentences_repeated" in {f.code for f in found}


def test_a_payoff_chapter_may_echo_its_setup_chapter():
    chapters = [dict(id="m.ch01", summary="Hale notices the clock stopped at ten past nine in the library.", events_covered=["e1"]),
                dict(id="m.ch02", summary="Hale discovers that the clock was stopped on purpose at ten past nine in the library.", events_covered=["e2"])]
    events = [dict(id="e1", kind="setup", once_only=True), dict(id="e2", kind="reveal", pays_off="e1", once_only=True)]
    assert R.repeated_events(chapters, [], ledger_events=events) == []
    assert R.repeated_events(chapters, [], ledger_events=[dict(id="e1", once_only=True), dict(id="e2", once_only=True)])  # unlinked: reported


def test_an_event_text_written_where_an_id_belongs_is_mapped_back_and_unknown_ones_are_explained():
    raw = [dict(id="e1", text="Mara hides the key", excerpt="Mara hides the key", kind="setup", after=[]),
           dict(id="e2", text="The key opens the vault", after=["Mara hides the key"], pays_off="Mara hides the key"),
           dict(id="e3", text="Something else", pays_off="A sentence that matches no event")]
    assert L.resolve_references(raw) == 2
    assert raw[1]["pays_off"] == "e1" and raw[1]["after"] == ["e1"] and raw[2]["pays_off"].startswith("A sentence")
    found = [f for f in L.check_ledger([{**e, "once_only": True, "kind": e.get("kind", "event"), "weight": 1} for e in raw]) if f.code == "unknown_event"]
    assert found and "ID of the setup" in found[0].message and "Known ids: e1, e2, e3" in found[0].message
    ambiguous = [dict(id="e1", text="Same words"), dict(id="e2", text="Same words"), dict(id="e3", text="x", pays_off="Same words")]
    assert L.resolve_references(ambiguous) == 0  # two events match: not guessed
