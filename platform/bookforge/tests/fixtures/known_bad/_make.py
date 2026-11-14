"""Writes the known-bad fixture files next to this script. TEST DATA, not a real book.

It reproduces, in a small invented story, the failure patterns seen in a real first draft: an act with no resolution, an
act with too many chapters for its material, once-only events planned twice, a missing turning point, scenes that restart
the same action, research terms that became beats, states that flip back, a character in two places, flat tension, chapters
that open with the previous chapter's closing lines, repeated sentences and wrap-up endings. Run: python _make.py
"""

from pathlib import Path

import yaml

HERE = Path(__file__).parent

SYNOPSIS = """\
# Synopsis (test data)

Mara Voss is a salvage pilot who owes a crushing debt to the moneylender Corso, and she finds a derelict ferry rusting in the harbor yard.

She forces her way into the ferry and finds a data drive that names Corso as a smuggler.

Corso learns of the drive and offers Mara a deal: hand it over and the debt is voided.

Mara signs the deal but secretly keeps a copy of the drive, and she launches the ferry to escape the yard.

She gives the copy to the harbor inspector, who arrests Corso, and Mara sails free with her debt cleared.
"""

EVENTS = [
    dict(id="e1", text="Mara owes Corso a crushing debt", excerpt="owes a crushing debt to the moneylender Corso", weight=1),
    dict(id="e2", text="Mara finds a derelict ferry in the harbor yard", excerpt="finds a derelict ferry rusting in the harbor yard", after=["e1"], weight=2),
    dict(id="e3", text="Mara enters the ferry", excerpt="forces her way into the ferry", after=["e2"], weight=2),
    dict(id="e4", text="Mara finds a data drive naming Corso as a smuggler", excerpt="finds a data drive that names Corso as a smuggler", after=["e3"], weight=3),
    dict(id="e5", text="Corso learns of the drive", excerpt="Corso learns of the drive", after=["e4"], weight=2),
    dict(id="e6", text="Corso offers a deal: the drive for the debt", excerpt="offers Mara a deal: hand it over and the debt is voided", after=["e5"], weight=2),
    dict(id="e7", text="Mara signs the deal but secretly keeps a copy", excerpt="Mara signs the deal but secretly keeps a copy of the drive", after=["e6"], weight=3, kind="setup"),
    dict(id="e8", text="Mara launches the ferry to escape the yard", excerpt="she launches the ferry to escape the yard", after=["e7"], weight=3),
    dict(id="e9", text="The inspector arrests Corso with Mara's copy", excerpt="gives the copy to the harbor inspector, who arrests Corso", after=["e8"], weight=3, kind="payoff", pays_off="e7", ending=True),
    dict(id="e10", text="Mara sails free, her debt cleared", excerpt="Mara sails free with her debt cleared", after=["e9"], weight=1, ending=True),
]


def full(e):
    return {"once_only": True, "after": [], "kind": "event", "pov": "", "ending": False, "pays_off": "", "source": "synopsis", "parent": "", **e}


LEDGER = {"events": [full(e) for e in EVENTS], "questions": [], "thin": False}

# ── acts: act 3 lacks the resolution (e10); act 1 has 8 chapters for 4 light events; no turning point event for act 3 ──
ACTS = [
    dict(id="t.act1", title="The yard", summary="Mara, in debt, finds the ferry and enters it.", purpose="setup", turning_point="the ferry is entered",
         chapter_count=8, events=["e1", "e2", "e3"], turning_point_event="e3", sizing_reason="hit the word target"),
    dict(id="t.act2", title="The drive", summary="Mara finds the drive; Corso learns and offers a deal.", purpose="escalation", turning_point="the deal is offered",
         chapter_count=2, events=["e4", "e5", "e6"], turning_point_event="e6", sizing_reason="one chapter per beat"),
    dict(id="t.act3", title="The deal", summary="Mara signs, launches and Corso is arrested.", purpose="crisis", turning_point="the arrest",
         chapter_count=2, events=["e7", "e8", "e9"], turning_point_event="", sizing_reason="the rest"),
]

TENS = [3, 4, 5, 8, 9, 8, 10, 9, 8, 10, 9, 8]
# ch07 replans ch05, e4 is told in ch04 and again in ch08, e8 in ch06 and ch11, e7 is covered by no chapter, e3 in ch02 and ch03.
CH = [
    ("ch01", "t.act1", "Mara reels from her debt to Corso. She walks the harbor yard and sees the derelict ferry rusting at the pier.", ["e1", "e2"]),
    ("ch02", "t.act1", "Mara forces the rusted lock and enters the ferry through the cargo hatch. She explores the dark corridors.", ["e3"]),
    ("ch03", "t.act1", "Mara enters the ferry again through the cargo hatch after forcing the rusted lock. She explores the dark corridors once more.", ["e3"]),
    ("ch04", "t.act1", "Mara searches the cabin and finds a data drive that names Corso as a smuggler.", ["e4"]),
    ("ch05", "t.act2", "Corso hears about the drive from a dockhand and sends two men to the yard to question Mara about the drive.", ["e5"]),
    ("ch06", "t.act2", "Mara starts the engines and launches the ferry from the yard to escape Corso's men.", ["e8"]),
    ("ch07", "t.act2", "Corso hears about the drive from a dockhand and sends two men to the yard to question Mara about the drive again.", ["e5"]),
    ("ch08", "t.act2", "Mara searches the cabin again and finds the data drive that names Corso as a smuggler.", ["e4"]),
    ("ch09", "t.act2", "Corso meets Mara and offers a deal: the drive for the debt.", ["e6"]),
    ("ch10", "t.act3", "Mara hesitates over the deal and walks the harbor wall at night.", ["e6"]),
    ("ch11", "t.act3", "Mara starts the engines and launches the ferry from the yard once more.", ["e8"]),
    ("ch12", "t.act3", "The inspector arrests Corso on the strength of the drive.", ["e9"]),
]
CHAPTERS = [dict(id=f"t.{c}", act=a, title=f"Chapter {i}", purpose="p", summary=s, pov="mara", setting="yard", tension=TENS[i - 1], events_covered=ev,
                 end_state="") for i, (c, a, s, ev) in enumerate(CH, 1)]

LEAK = "Mara reads the vibration as sensor noise per IEC 61508 and checks the spectral kurtosis."
LOCK = "Mara forces the rusted lock on the hatch and slips inside the ferry."
SCENES = []
for i, c in enumerate(CHAPTERS, 1):
    base = [LOCK, "Mara enters the ferry and walks the dark corridor to the cabin."] if i in (2, 3, 4, 5, 6, 7, 8, 9, 11) else ["Mara talks with her friend at the pier.", "She weighs her debt in the evening."]
    beats = base + ([LEAK] if i % 2 == 0 or i in (5, 7, 9) else [])
    SCENES.append(dict(id=f"{c['id']}.s1", chapter=c["id"], purpose="p", pov="mara", setting="yard", characters=["mara"], beats=beats, research=[], end_state="", events=[]))

NOTES = [dict(id="r1", claim="Vibration can be misread as sensor noise; IEC 61508 sets safety integrity levels for such sensors."),
         dict(id="r2", claim="Spectral kurtosis helps detect impulsive faults in rotating machinery.")]

TRACKS = [
    dict(id="mara-debt", entity="mara", kind="status", plan=[
        dict(**{"from": "t.ch01"}, value="the debt to Corso is active and crushing"),
        dict(**{"from": "t.ch05"}, value="the debt is voided"),
        dict(**{"from": "t.ch10"}, value="the debt to Corso is active and crushing")]),
    dict(id="corso-where", entity="corso", kind="location", plan=[dict(**{"from": "t.ch09.s1"}, value="Corso is in the harbor office")]),
    dict(id="corso-where2", entity="corso", kind="location", plan=[dict(**{"from": "t.ch09.s1"}, value="Corso is on the pier")]),
]
TIMELINE = [dict(id="t.ch01.s1", day=1, time="dawn"), dict(id="t.ch02.s1", day=2, time="noon"), dict(id="t.ch03.s1", day=1, time="noon")]

PROSE = {
    "ch01": ("The yard lay quiet. Mara walked the pier and looked at the ferry for a long time before she moved. "
             "The rust had eaten the rail down to lace. She thought about the debt and Corso and the way he smiled. "
             "She walked back toward the gate and did not look behind her. She knew now that nothing would ever be the same, and for now that was enough. "
             "They were free, for now."),
    "ch02": ("She walked back toward the gate and did not look behind her. She knew now that nothing would ever be the same, and for now that was enough. "
             "The hatch stood open on a black corridor. Mara stepped inside. The air tasted of old oil and the cold of the hull came through her boots. "
             "The air tasted of old oil and the cold of the hull came through her boots. She counted the doors as she passed them and none of them would open."),
}


def dump(name, data):
    (HERE / name).write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=110), encoding="utf-8")


if __name__ == "__main__":
    (HERE / "synopsis.md").write_text(SYNOPSIS, encoding="utf-8")
    dump("ledger.yaml", LEDGER)
    dump("acts.yaml", {"acts": ACTS})
    dump("chapters.yaml", {"chapters": CHAPTERS})
    dump("scenes.yaml", {"scenes": SCENES})
    dump("research_notes.yaml", {"notes": NOTES})
    dump("tracks.yaml", {"tracks": TRACKS})
    dump("timeline.yaml", {"scenes": TIMELINE})
    (HERE / "prose").mkdir(exist_ok=True)
    for k, v in PROSE.items():
        (HERE / "prose" / f"{k}.md").write_text(v + "\n", encoding="utf-8")
