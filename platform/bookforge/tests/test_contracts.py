"""Prompt edits must not quietly break the stage contracts (platform/bookforge/CONTRACTS.md), and the validators stay general."""

import re
from pathlib import Path

import pytest

from bookforge.prompts import PROMPT_DIR

LOAD_BEARING = {
    "ledger": ["{synopsis}", "excerpt", "once_only", "ending", "Do not add plot, do not pad", "questions"],
    "ledger_revise": ["{answers}", "source: author", "exactly as it is"],
    "acts_ledger": ["what the events can supply", "{carried}", "{ledger_events}", "EVERY event of the ledger belongs to exactly one act", "turning_point_event", "sizing_reason"],
    "chapters_ledger": ["events_continued", "{carried}", "{ledger_status}", "{story_so_far}", "{research_notes}", "events_covered", "end_state", "RESERVED FOR LATER", "derived_events", "never retell"],
    "scenes_ledger": ["{carried}", "{ledger_status}", "{story_so_far}", "{research_notes}", "`events`", "`end_state`", "from 1 to 4", "never turn one into a beat"],
    "prose_system": ["Never end on a summary", "Never restate", "never become events"],
    "prose": ["do not restate or summarize it"],
}


@pytest.mark.parametrize("name", sorted(LOAD_BEARING))
def test_shipped_prompts_keep_their_contract_text(name):
    text = (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")
    for needle in LOAD_BEARING[name]:
        assert needle.lower() in text.lower() or needle in text, f"{name}.md lost: {needle}"


def test_research_is_framed_as_reference_only():
    from bookforge.research.select import REFERENCE_ONLY
    assert "never become a beat" in REFERENCE_ONLY and "plot device" in REFERENCE_ONLY


def test_validators_hold_no_story_specific_words():
    """The validators detect failure patterns of any book. A word list of one story's events or setting would not belong here."""
    folder = Path(__file__).resolve().parent.parent / "bookforge" / "validators"
    banned = re.compile(r"\b(ship|launch\w*|hatch|kestrel|thorne|erebus|dominion|drive|lock|salvage|mara|corso)\b", re.I)
    for f in folder.glob("*.py"):
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            assert not banned.search(code), f"{f.name}:{n} mentions a story-specific word: {line.strip()}"
