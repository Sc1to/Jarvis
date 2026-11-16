"""Every finding code the pipeline can raise, with its class.

The class says what kind of problem it is, and so who deals with it:

- STRUCTURAL: bookkeeping with exactly one right answer (an id, which events a chapter tells, order). The model never writes these and the tool never
  asks about them: they are derived by construction (bible/partition.py, bible/normalize.py). One that still shows up is a bug of the tool and is saved
  as a diagnostics bundle (diagnostics.py), not shown as an item to answer.
- WORDING: a text field says something wrong. A narrow rewrite fixes it (qc/overreach_fix.py, prose_repair.py).
- RATING: a number or a label (tension, a count, a weight).
- DECISION: needs a story choice (a contradiction, a name that is not in the cast, whose point of view).
- INFO: housekeeping the tool reports about itself.

`planned` names the row of the plan that makes a structural code impossible (A1 #n in the plan), or "done" when it already is. A test
(tests/test_registry.py) fails when the source raises a code this table does not know, so a new finding cannot appear without a class.
"""

from dataclasses import dataclass

STRUCTURAL, WORDING, RATING, DECISION, INFO = "structural", "wording", "rating", "decision", "info"


@dataclass(frozen=True)
class FindingSpec:
    code: str
    klass: str
    stage: str  # where it is raised first: ledger | acts | chapters | scenes | prose | state
    planned: str = ""  # structural: how it becomes impossible ("done", or the plan row "A1#3")
    note: str = ""
    also_done: tuple = ()  # further stages where it is already impossible (planned "done" holds for `stage` and these)


def _specs() -> dict[str, FindingSpec]:
    rows = [
        # ledger
        ("duplicate_event_id", STRUCTURAL, "ledger", "A1#8"), ("no_events", STRUCTURAL, "ledger", "", "extraction produced nothing: a tool or model failure"),
        ("unknown_event", STRUCTURAL, "ledger", "A1#2"), ("event_cycle", DECISION, "ledger"), ("event_order", STRUCTURAL, "ledger", "done"),
        ("payoff_without_setup", STRUCTURAL, "ledger", "A1#9"), ("payoff_target_not_setup", STRUCTURAL, "ledger", "A1#9"),
        ("reveal_before_setup", STRUCTURAL, "ledger", "A1#9"), ("payoff_unrelated_to_setup", WORDING, "ledger"), ("setup_without_payoff", DECISION, "ledger"),
        ("no_resolution", STRUCTURAL, "ledger", "A1#9"), ("several_endings", STRUCTURAL, "ledger", "A1#9"), ("several_decisions", STRUCTURAL, "ledger", "A1#9"),
        ("no_central_decision", DECISION, "ledger"), ("early_resolution", DECISION, "ledger"), ("mostly_derived", DECISION, "ledger"),
        ("causal_order", DECISION, "ledger"), ("weights_flat", RATING, "ledger"),
        ("no_excerpt", WORDING, "ledger"), ("excerpt_not_in_synopsis", WORDING, "ledger"), ("event_text_not_in_excerpt", WORDING, "ledger"),
        ("synopsis_not_covered", DECISION, "ledger"), ("sentence_not_covered", DECISION, "ledger", "", "housekeeping outcomes (widen, attach, waive) are applied by the tool"),
        ("resolution_not_final_paragraph", DECISION, "ledger"), ("synopsis_not_in_acts", INFO, "ledger", "", "only used by the suite"),
        ("auto_repaired", INFO, "ledger"), ("synopsis_audit", INFO, "ledger"),
        ("derived_without_parent", STRUCTURAL, "chapters", "A1#6"), ("derived_not_minor", STRUCTURAL, "chapters", "A1#6"),
        ("derived_not_after_parent", STRUCTURAL, "chapters", "A1#6"), ("too_many_derived", STRUCTURAL, "chapters", "A1#6"),
        # acts
        ("event_in_two_acts", STRUCTURAL, "acts", "A1#2"), ("event_in_no_act", STRUCTURAL, "acts", "A1#2"), ("acts_out_of_order", STRUCTURAL, "acts", "A1#2"),
        ("turning_point_without_event", STRUCTURAL, "acts", "A1#3"), ("turning_point_not_in_act", STRUCTURAL, "acts", "A1#3"),
        ("turning_point_not_at_end", STRUCTURAL, "acts", "A1#3"), ("resolution_not_in_last_act", STRUCTURAL, "acts", "A1#2"),
        ("final_turning_point_is_transition", STRUCTURAL, "acts", "A1#3"), ("acts_differ_from_capacity", STRUCTURAL, "acts", "A1#3"),
        ("sizing_reason_mismatch", STRUCTURAL, "acts", "A1#3"), ("no_sizing_reason", STRUCTURAL, "acts", "A1#3"),
        ("implausible_chapter_count", STRUCTURAL, "acts", "A1#3"), ("chapter_count_exceeds_capacity", STRUCTURAL, "acts", "A1#3"),
        ("lopsided_acts", RATING, "acts"), ("turning_point_text_differs", WORDING, "acts"), ("act_summary_omits_resolution", WORDING, "acts"),
        ("act_retells_event", WORDING, "acts"),
        # chapters
        ("chapter_without_events", STRUCTURAL, "chapters", "done"), ("continued_event_not_begun", STRUCTURAL, "chapters", "A1#5"),
        ("only_major_events_continue", STRUCTURAL, "chapters", "A1#5"), ("event_spans_too_many_chapters", STRUCTURAL, "chapters", "A1#5"),
        ("event_from_other_act", STRUCTURAL, "chapters", "done"), ("once_only_repeated", STRUCTURAL, "chapters", "done", "chapters by starts_with, scenes by starts_with", ("scenes",)),
        ("event_before_cause", STRUCTURAL, "chapters", "done"), ("chapters_out_of_order", STRUCTURAL, "chapters", "done"),
        ("chapter_nothing_new", STRUCTURAL, "chapters", "done"), ("event_not_covered", STRUCTURAL, "chapters", "done"),
        ("chapter_retells_event", WORDING, "chapters"), ("chapter_text_misses_event", WORDING, "chapters"), ("chapter_text_thin_on_event", WORDING, "chapters"),
        ("end_state_overreach", WORDING, "chapters"), ("state_change_repeated", WORDING, "chapters"), ("event_repeated", WORDING, "chapters"),
        ("chapter_replans_chapter", WORDING, "chapters"), ("chapters_one_sentence_each", RATING, "chapters"), ("heavy_chapter", RATING, "chapters"),
        ("flat_tension", RATING, "chapters"), ("pov_not_in_text", DECISION, "chapters"), ("pov_not_main", DECISION, "chapters"),
        ("unknown_name", DECISION, "chapters"),
        # scenes
        ("scene_event_not_in_chapter", STRUCTURAL, "scenes", "done"), ("chapter_event_not_in_scenes", STRUCTURAL, "scenes", "done"),
        ("scene_without_end_state", WORDING, "scenes"), ("scene_retells_event", WORDING, "scenes"), ("scene_text_misses_event", WORDING, "scenes"),
        ("scene_text_thin_on_event", WORDING, "scenes"), ("scene_repeats_scene", WORDING, "scenes"), ("action_pattern_repeated", WORDING, "scenes"),
        ("research_in_beats", WORDING, "scenes"), ("implausible_scene_count", RATING, "scenes"), ("chapter_overloaded", RATING, "scenes"),
        ("story_day_backwards", STRUCTURAL, "scenes", "A1#7"), ("state_regression", DECISION, "scenes"), ("two_places_at_once", DECISION, "scenes"),
        # prose
        ("sentences_repeated", WORDING, "prose"), ("chapter_opens_with_previous_ending", WORDING, "prose"), ("wrap_up_ending", WORDING, "prose"),
        ("tic_word", WORDING, "prose"), ("prose_misses_event", WORDING, "prose"),
    ]
    return {r[0]: FindingSpec(*r) for r in rows}


SPECS: dict[str, FindingSpec] = _specs()

# audit question types (layers/audit.py): they are DECISIONS (a world fact is decided by policy, see resolve.py)
QUESTION_TYPES = ("contradiction", "cast_conflict", "unknown_name", "condition_order", "unestablished_object", "motive_gap", "thin", "unpaid_setup")


def spec(code: str) -> FindingSpec | None:
    return SPECS.get(code)


def klass(code: str) -> str | None:
    s = SPECS.get(code)
    return s.klass if s else None


def structural(code: str) -> bool:
    return klass(code) == STRUCTURAL


def guaranteed(code: str, stage: str) -> bool:
    """A structural code the tool already makes impossible at this stage (planned "done"): if one is raised, it is a bug of the tool."""
    s = SPECS.get(code)
    return bool(s and s.klass == STRUCTURAL and s.planned == "done" and (s.stage == stage or stage in s.also_done))
