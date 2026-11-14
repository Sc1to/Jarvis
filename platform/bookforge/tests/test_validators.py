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
    assert "setup_without_payoff" in codes(L.check_ledger(ev, SYN), SOFT)  # the author is asked, the run does not fail
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


def test_reversed_and_unmarked_setup_payoff_pairs_are_repaired():
    raw = [dict(id="e5", kind="event", pays_off="e6"), dict(id="e6", kind="event", pays_off="")]  # pays off a LATER event: reversed
    notes = L.repair_setups(raw)
    assert raw[0]["kind"] == "setup" and raw[0]["pays_off"] == "" and raw[1]["pays_off"] == "e5" and raw[1]["kind"] == "payoff" and "reversed" in notes[0]
    raw2 = [dict(id="e1", kind="event"), dict(id="e2", kind="event", pays_off="e1")]  # earlier target not marked a setup
    assert L.repair_setups(raw2) and raw2[0]["kind"] == "setup"
    raw3 = [dict(id="e1", kind="setup"), dict(id="e2", kind="payoff", pays_off="e1")]
    assert L.repair_setups(raw3) == []


def test_chapter_counts_are_checked_against_the_ledgers_real_weights():
    ev = [dict(id=f"e{i}", text=f"event {i}", weight=3, once_only=True, kind="event") for i in range(1, 7)]  # weight 18
    act = lambda n, reason="weight 15": dict(id="t.act1", events=[e["id"] for e in ev], chapter_count=n, sizing_reason=reason, turning_point_event="e6", turning_point="event 6")
    crammed = [f for f in L.sizing_plausibility([act(4)], ev) if f.code == "implausible_chapter_count"]
    assert crammed and crammed[0].severity == HARD and "weigh 18" in crammed[0].message and "between 6 and 15" in crammed[0].message
    assert L.sizing_plausibility([act(9)], ev) == []
    assert any(f.code == "implausible_chapter_count" and "padded" in f.message for f in L.sizing_plausibility([act(20)], ev))
    assert "weight 18 over 6 events" in L.sizing_note(act(9), ev)


def test_a_turning_point_text_that_describes_another_event_is_flagged():
    ev = [dict(id="e10", text="Eli decides to broadcast the data instead of fighting"), dict(id="e13", text="Eli accepts he cannot save Mara and she dies")]
    ok = dict(id="t.act1", turning_point_event="e13", turning_point="Eli accepts he cannot save Mara")
    bad = dict(id="t.act1", turning_point_event="e13", turning_point="Eli accepts he cannot save Mara and chooses to broadcast the data instead of fighting")
    assert L.turning_point_texts([ok], ev) == []
    assert [f.code for f in L.turning_point_texts([bad], ev)] == ["turning_point_text_differs"]


# ── do the texts describe the events they list? ─────────────────────────────

TEXT_EVENTS = [dict(id="e1", text="The harbor master seizes the smuggled cargo at dawn", once_only=True, weight=2),
               dict(id="e2", text="Teresa bribes the night watchman to open the customs warehouse", once_only=True, weight=2),
               dict(id="e3", text="A fire destroys the customs warehouse ledgers overnight", once_only=True, weight=3)]


def test_a_chapter_that_retells_another_chapters_event_is_a_hard_finding():
    chapters = [dict(id="t.ch01", title="Dawn", purpose="p", summary="The harbor master seizes the smuggled cargo at dawn.", events_covered=["e1"]),
                dict(id="t.ch02", title="Warehouse", purpose="p", summary="Again the harbor master seizes the smuggled cargo at dawn, before Teresa bribes the night watchman.", events_covered=["e2"])]
    f = L.check_chapter_texts(chapters, TEXT_EVENTS)
    assert any(x.code == "chapter_retells_event" and x.severity == HARD and "e1" in x.items for x in f)
    ok = [chapters[0], dict(chapters[1], summary="Teresa bribes the night watchman to open the customs warehouse.")]
    assert [x for x in L.check_chapter_texts(ok, TEXT_EVENTS) if x.severity == HARD] == []


def test_a_listed_event_the_text_never_mentions_is_a_soft_finding():
    ch = [dict(id="t.ch01", title="x", purpose="y", summary="Nothing relevant here at all, only weather and gloom.", events_covered=["e3"])]
    f = L.check_chapter_texts(ch, TEXT_EVENTS)
    assert [x.code for x in f if "misses" in x.code] == ["chapter_text_misses_event"] and f[0].severity == SOFT


def test_scenes_that_retell_an_event_of_another_chapter_are_refused():
    chapters = [dict(id="t.ch01", events_covered=["e1"]), dict(id="t.ch02", events_covered=["e2"])]
    scenes = [dict(id="t.ch02.s1", chapter="t.ch02", purpose="p", events=["e2"],
                   beats=["The harbor master seizes the smuggled cargo at dawn again.", "Teresa bribes the night watchman to open the customs warehouse."])]
    assert any(x.code == "scene_retells_event" and x.severity == HARD for x in L.check_scene_texts(scenes, chapters, TEXT_EVENTS))


def test_scene_counts_follow_the_weight_of_the_chapter():
    heavy = dict(id="t.ch01", events_covered=["e1", "e2", "e3"])  # weight 7
    ev = TEXT_EVENTS
    one = L.scene_count_plausibility(heavy, [dict(id="t.ch01.s1")], ev)
    assert one and one[0].severity == HARD and "crammed" in one[0].message and "between 2 and 4" in one[0].message
    assert L.scene_count_plausibility(heavy, [dict(id="a"), dict(id="b")], ev) == []
    light = dict(id="t.ch02", events_covered=["e1"])  # weight 2
    four = L.scene_count_plausibility(light, [dict(id=str(i)) for i in range(4)], ev)
    assert four and "padded" in four[0].message


def test_times_of_day_are_compared_as_parts_of_the_day():
    assert S.time_part("just after midnight") == "midnight" and S.time_part("Evening") == S.time_part("dusk") and S.time_part("midday") == "noon"
    scenes = [dict(id="t.ch01.s1", setting="a", characters=["x"]), dict(id="t.ch01.s2", setting="b", characters=["x"])]
    tl = [dict(id="t.ch01.s1", day=3, time="evening"), dict(id="t.ch01.s2", day=3, time="at dusk")]
    assert "two_places_at_once" in codes(S.location_conflicts(scenes, tl))


@pytest.mark.real_prose_checks
def test_prose_summaries_that_retell_an_event_in_new_words_are_caught(project):
    from bookforge import scenefiles
    from bookforge.bible import store
    from bookforge.validators.book import prose_findings
    from structure_fakes import ready, rules
    from conftest import RuleLLM
    from bookforge.layers import HANDLERS
    from bookforge.layers.runner import run
    p = ready(project)
    run(p, RuleLLM(rules()), HANDLERS, until="scenes")
    sc = store.load_scenes(p)
    texts = {sc[0].id: "Anna pries open the rusted lock on the cargo hatch and slips inside the ferry.",
             sc[2].id: "Anna forces the rusted lock of the cargo hatch and slips inside the ferry once more.",
             sc[4].id: "Anna pries the rusted lock on the cargo hatch and slips inside the ferry yet again."}
    for sid, t in texts.items():
        scenefiles.scene_dir(p, sid).mkdir(parents=True, exist_ok=True)
        scenefiles.final_path(p, sid).write_text(t + " The rest of the scene follows.")
        scenefiles.summary_path(p, sid).write_text(t)
    found, _ = prose_findings(p)
    assert any(f.code == "event_repeated" and f.stage == "prose" for f in found)


# ── the shape of the acts (the acts a real run produced, with the ledger's events) ──

REAL = {1: "Eli arrives at Erebus-7 and steps onto the asteroid surface", 2: "Eli observes the decaying industrial environment and realizes his debt binds him to the Astra Dominion",
        3: "Eli seeks out Mara Kovic, a technician suffering from radiation-induced cognitive decline", 4: "Mara reveals that Eli's grandfather was executed by the corporation for discovering mining destabilization",
        5: "Eli and Mara form an alliance to navigate the mining tunnels", 6: "Foreman Halloway begins hunting Eli and Mara, viewing them as liabilities",
        7: "Eli and Mara locate the buried Kestrel beneath the processing plant", 8: "Eli realizes activating the ship requires bypassing safety protocols that would expose corporate secrets",
        9: "Halloway intercepts them at the launch bay with drones and a plasma cutter", 10: "Eli decides to broadcast contamination data instead of fighting",
        11: "Mara intervenes to protect the data drive, injuring Halloway in the process", 12: "Eli uploads the data, triggering a lockdown and worsening Mara's condition",
        13: "Eli accepts he cannot save Mara and she succumbs to her condition", 14: "Eli launches the Kestrel and escapes as Halloway seals the sector",
        15: "The corporation allows Eli to escape in exchange for a non-disclosure agreement and debt contract", 16: "Eli lands on an unclaimed moon, realizing survival requires compromise and the system remains intact"}
REAL_EVENTS = [dict(id=f"e{i}", text=t, weight=3 if i >= 7 or i == 4 else 2, once_only=True, kind="event", ending=i >= 14) for i, t in REAL.items()]


def real_acts():
    return [dict(id="b2.act1", title="Arrival and Alliance", chapter_count=4, events=["e1", "e2", "e3", "e4"], turning_point_event="e4", sizing_reason="x",
                 summary="Eli arrives at Erebus-7 and steps onto the asteroid surface, observing the decaying industrial environment and realizing his debt binds him. He seeks out Mara Kovic, "
                         "a technician suffering from radiation-induced cognitive decline, who warns him that Eli's grandfather was executed by the corporation. This forces Eli and Mara to form a fragile alliance to navigate the dangerous mining tunnels together.",
                 purpose="To establish the hostile setting.", turning_point="Mara warns that Eli's grandfather was executed by the corporation for discovering mining destabilization."),
            dict(id="b2.act2", title="The Hunt", chapter_count=7, events=["e5", "e6", "e7", "e8", "e9"], turning_point_event="e9", sizing_reason="x",
                 summary="Eli and Mara form an alliance to navigate the mining tunnels, where Foreman Halloway begins hunting them. They locate the buried Kestrel beneath the processing plant but realize that activating the ship requires bypassing safety protocols. "
                         "Halloway intercepts them at the launch bay with drones and a plasma cutter, forcing Eli to decide between fighting or broadcasting contamination data.",
                 purpose="To escalate.", turning_point="Halloway intercepts them at the launch bay."),
            dict(id="b2.act3", title="Escape", chapter_count=11, events=["e10", "e11", "e12", "e13", "e14", "e15", "e16"], turning_point_event="e10", sizing_reason="x",
                 summary="Eli decides to broadcast contamination data instead of fighting, and Mara intervenes to protect the data drive. Eli uploads the data. He accepts he cannot save her. Eli launches the Kestrel and escapes, but the corporation allows it only for a non-disclosure agreement and debt contract. He lands on an unclaimed moon.",
                 purpose="To resolve.", turning_point="Eli decides to broadcast contamination data instead of fighting.")]


def test_a_turning_point_in_the_first_half_of_its_act_is_refused_and_one_at_the_end_is_not():
    f = L.turning_point_positions(real_acts(), REAL_EVENTS)
    assert [(x.code, x.severity, x.items[0]) for x in f] == [("turning_point_not_at_end", HARD, "b2.act3")] and "e15, e16" in f[0].message
    fixed = real_acts()
    fixed[2]["turning_point_event"] = "e13"
    assert L.turning_point_positions(fixed, REAL_EVENTS) == []


def test_an_act_summary_that_retells_another_acts_event_is_refused():
    f = L.check_act_texts(real_acts(), REAL_EVENTS)
    assert {(x.code, x.items[0], x.items[1]) for x in f if x.severity == HARD} >= {("act_retells_event", "b2.act1", "e5"), ("act_retells_event", "b2.act2", "e10")}
    assert not any(x.items[0] == "b2.act3" and x.severity == HARD for x in f)
    clean = real_acts()
    clean[0]["summary"] = "Eli arrives at Erebus-7 and steps onto the asteroid surface and observes the decaying industrial environment. He seeks out Mara Kovic, a technician suffering from radiation-induced cognitive decline, who reveals his grandfather was executed."
    clean[1]["summary"] = "Eli and Mara form an alliance to navigate the mining tunnels while Foreman Halloway hunts them. They locate the buried Kestrel but activating it requires bypassing safety protocols. Halloway intercepts them at the launch bay."
    assert [x for x in L.check_act_texts(clean, REAL_EVENTS) if x.severity == HARD] == []


def test_an_act_holding_half_the_chapters_is_flagged_softly():
    f = L.lopsided_acts(real_acts())
    assert [(x.code, x.severity, x.items[0]) for x in f] == [("lopsided_acts", SOFT, "b2.act3")] and "50%" in f[0].message
    assert L.lopsided_acts([dict(id="a", chapter_count=3), dict(id="b", chapter_count=3)]) == []  # two acts: not judged


def test_the_last_acts_summary_must_describe_the_resolution_softly():
    acts = real_acts()
    acts[2]["summary"] = ("Eli decides to broadcast contamination data, and Mara intervenes to protect the data drive. Eli uploads the data and accepts he cannot save her. "
                          "Eli launches the Kestrel and escapes as Halloway seals the sector. The corporation allows it only for a non-disclosure agreement and debt contract.")
    f = [x for x in L.resolution_in_summary(acts, REAL_EVENTS)]
    assert [(x.code, x.severity, x.items[1]) for x in f] == [("act_summary_omits_resolution", SOFT, "e16")]  # e14 and e15 are described, the landing is not
    acts[2]["summary"] += " He lands on an unclaimed moon, realizing survival requires compromise and the system remains intact."
    assert L.resolution_in_summary(acts, REAL_EVENTS) == []
    assert L.resolution_in_summary([], REAL_EVENTS) == []


def test_a_chapter_may_lead_into_the_next_event_of_its_act_but_not_use_a_later_acts_events():
    ch = lambda n, ev, text: dict(id=f"b2.ch{n:02d}", act="b2.act1", purpose="p", summary=text, events_covered=ev)
    chapters = [ch(1, ["e1"], "Eli arrives at Erebus-7 and steps onto the asteroid surface, then observes the decaying industrial environment and realizes his debt binds him to the Astra Dominion."),
                ch(2, ["e2"], "Eli observes the decaying industrial environment and realizes his debt binds him. Mara reveals that Eli's grandfather was executed by the corporation for discovering mining destabilization."),
                ch(3, ["e3"], "Eli seeks out Mara Kovic, a technician suffering from radiation-induced cognitive decline. Eli and Mara locate the buried Kestrel beneath the processing plant."),
                ch(4, ["e4"], "Mara reveals that Eli's grandfather was executed by the corporation for discovering mining destabilization. Halloway intercepts them at the launch bay with drones and a plasma cutter.")]
    f = L.check_chapter_texts(chapters, REAL_EVENTS)
    hard_ = {(x.items[0], x.items[1]) for x in f if x.severity == HARD}
    assert ("b2.ch03", "e7") in hard_ and ("b2.ch04", "e9") in hard_  # events of act 2: reserved
    assert not any(x.items[:2] == ["b2.ch01", "e2"] and x.severity == HARD for x in f)  # the next event of the same act: soft
    assert not any(x.items[:2] == ["b2.ch02", "e4"] and x.severity == HARD for x in f)
    assert ("b2.ch02", "e2") not in hard_
    msg = next(x.message for x in f if x.items[:2] == ["b2.ch03", "e7"])
    assert "reserved for a later act" in msg
    again = next(x.message for x in f if x.items[:2] == ["b2.ch04", "e4"] ) if any(x.items[:2] == ["b2.ch04", "e4"] for x in f) else ""
    assert again == "" or "already told" in again or "its own" in again


# ── a major event may take a second chapter; an act cannot ask for more chapters than its events supply ──

def test_a_weight_three_event_may_continue_into_the_next_chapter_and_nothing_else_may():
    ev = [dict(id="e1", text="a", weight=2, once_only=True, kind="event"), dict(id="e2", text="b", weight=3, once_only=True, kind="event", after=["e1"]),
          dict(id="e3", text="c", weight=3, once_only=True, kind="event", after=["e2"])]
    acts = [dict(id="t.act1", events=["e1", "e2", "e3"])]
    ch = lambda n, cov, cont=(): dict(id=f"t.ch{n:02d}", act="t.act1", events_covered=list(cov), events_continued=list(cont))  # noqa: E731
    ok = [ch(1, ["e1"]), ch(2, ["e2"]), ch(3, [], ["e2"]), ch(4, ["e3"])]
    assert [f for f in L.check_chapters(ok, ev, acts) if f.severity == HARD] == []
    light = [ch(1, ["e1"]), ch(2, [], ["e1"]), ch(3, ["e2"]), ch(4, ["e3"])]
    assert "only_major_events_continue" in codes(L.check_chapters(light, ev, acts), HARD)
    gap = [ch(1, ["e1"]), ch(2, ["e2"]), ch(3, ["e3"]), ch(4, [], ["e2"])]
    assert "continued_event_not_begun" in codes(L.check_chapters(gap, ev, acts), HARD)
    third = [ch(1, ["e1"]), ch(2, ["e2"]), ch(3, [], ["e2"]), ch(4, [], ["e2"]), ch(5, ["e3"])]
    assert "event_spans_too_many_chapters" in codes(L.check_chapters(third, ev, acts), HARD)
    stalled = [ch(1, ["e1"]), ch(2, ["e1"]), ch(3, ["e2"]), ch(4, ["e3"])]  # retelling e1 without continuing it
    assert "once_only_repeated" in codes(L.check_chapters(stalled, ev, acts), HARD)


def test_an_act_cannot_ask_for_more_chapters_than_its_events_supply():
    ev = [dict(id=f"e{i}", text=f"event {i}", weight=w, once_only=True, kind="event") for i, w in enumerate([2, 2, 3, 3, 3, 3], 5)]  # the act 2 that failed on a real run
    act = lambda n: dict(id="b2.act2", events=[e["id"] for e in ev], chapter_count=n, sizing_reason="x", turning_point_event="e10", turning_point="event 10")  # noqa: E731
    assert L.act_capacity(act(8), ev) == (12, 6, 4, 2)  # 6 events + 4 major second chapters + 2 derived
    assert not [f for f in L.sizing_plausibility([act(8)], ev) if f.code == "chapter_count_exceeds_capacity"]
    big = [dict(id=f"e{i}", text=f"event {i}", weight=3, once_only=True, kind="event") for i in range(1, 7)]
    over = [f for f in L.sizing_plausibility([dict(id="a", events=[e["id"] for e in big], chapter_count=15, sizing_reason="x")], big) if f.code == "chapter_count_exceeds_capacity"]
    assert over and over[0].severity == HARD and "at most 14" in over[0].message


def test_a_continued_event_is_the_chapters_own_for_the_text_checks():
    events = [dict(id="e1", text="Halloway intercepts them at the launch bay with drones and a plasma cutter", once_only=True, weight=3),
              dict(id="e2", text="Eli decides to broadcast contamination data instead of fighting", once_only=True, weight=3)]
    ch = [dict(id="b.ch01", act="a", purpose="p", summary="Halloway intercepts them at the launch bay with drones and a plasma cutter.", events_covered=["e1"], events_continued=[]),
          dict(id="b.ch02", act="a", purpose="p", summary="Halloway presses the attack at the launch bay with drones and a plasma cutter while Eli decides to broadcast contamination data instead of fighting.",
               events_covered=["e2"], events_continued=["e1"])]
    assert [f for f in L.check_chapter_texts(ch, events) if f.severity == HARD] == []
