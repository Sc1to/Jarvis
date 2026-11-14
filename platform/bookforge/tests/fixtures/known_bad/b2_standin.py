"""A synthetic stand-in for the second test book (TEST DATA, not b2's text). It reproduces, in invented words, each problem b2 showed: contradictions
in the synopsis, a cast that disagrees with it, a dropped sentence, a condition after its consequence, three endings, a launch as the final turning point,
flat weights, sizing text that contradicts its numbers, a chapter that claims what a later one does, a POV that is not the chapter's, and chapters
that are one synopsis sentence each."""

SYNOPSIS = """# Synopsis (TEST DATA)

Eli Voss learns that the corporation hid the cause of the mine collapse, and Foreman Halloway orders the sector sealed.

Eli broadcasts the data to the local network while Mara Reil, dying of radiation sickness, begs him to stop. The corporation buries the data and Eli signs a non-disclosure agreement about it.

Eli launches the Kestrel and escapes as Halloway seals the sector. They allow Eli to escape, but only on the condition that he signs the agreement.

Eli presents the evidence drive to the tribunal. The drive is lost in the void when the Kestrel is struck, and a copy is hidden within the ship's logs.
"""

Q_BROADCAST = "Eli broadcasts the data to the local network"
Q_BURIED = "The corporation buries the data and Eli signs a non-disclosure agreement about it"
Q_ESCAPE = "Eli launches the Kestrel and escapes as Halloway seals the sector"
Q_CONDITION = "They allow Eli to escape, but only on the condition that he signs the agreement"
Q_DRIVE = "Eli presents the evidence drive to the tribunal"
Q_LOST = "The drive is lost in the void when the Kestrel is struck"
Q_HIDDEN = "a copy is hidden within the ship's logs"
Q_HALLOWAY = "Foreman Halloway orders the sector sealed"

AUDIT_REPLY = {"findings": [
    {"type": "contradiction", "quotes": [Q_BROADCAST, Q_BURIED], "why": "the data cannot be both broadcast to the local network and buried", "fixes": ["The broadcast reaches only a few before it is cut off", "The corporation buries it after a failed broadcast"]},
    {"type": "condition_order", "quotes": [Q_ESCAPE, Q_CONDITION], "why": "the condition for escaping comes after the escape", "fixes": ["Move the condition before the launch", "They let him go only because he already signed"]},
    {"type": "unestablished_object", "quotes": [Q_DRIVE], "why": "Eli never acquires an evidence drive before presenting it", "fixes": ["Have Eli copy the data to a drive in the first act", "Present the broadcast log instead"]},
    {"type": "contradiction", "quotes": [Q_LOST, Q_HIDDEN], "why": "the drive is lost, yet a copy is hidden in the logs in the same sentence", "fixes": ["The drive is lost; the copy in the logs is a different record", "Drop the loss"]},
    {"type": "cast_conflict", "quotes": [Q_HALLOWAY], "why": "the cast has silas-thorne in the foreman's role", "fixes": ["Use the cast's name", "Replace the cast entry with Halloway"]},
]}


def ev(i, text, excerpt=None, **kw):
    base = dict(id=i, text=text, excerpt=excerpt or text, once_only=True, after=[], kind="event", weight=2, pov="", ending=False, decision=False, pays_off="", source="synopsis", carried_in=False)
    return {**base, **kw}


LEDGER = [
    ev("e1", "Eli learns the corporation hid the cause of the mine collapse", "Eli Voss learns that the corporation hid the cause of the mine collapse"),
    ev("e2", "Halloway orders the sector sealed", "Foreman Halloway orders the sector sealed"),
    ev("e3", "Eli keeps a hidden copy of the evidence in the ship's logs", "Eli Voss learns that the corporation hid the cause", kind="setup"),
    ev("e10", "Eli decides to broadcast the data to the local network", Q_BROADCAST),
    ev("e11", "Mara begs him to stop", "Mara Reil, dying of radiation sickness, begs him to stop"),
    ev("e12", "Eli uploads the data, triggering a lockdown", "Eli broadcasts the data to the local network"),
    ev("e13", "The corporation buries the data and Eli signs a non-disclosure agreement", Q_BURIED),
    ev("e14", "Eli launches the Kestrel and escapes the sector", Q_ESCAPE, ending=True),
    ev("e15", "They allow Eli to escape on condition that he signs the agreement", Q_CONDITION, ending=True),
    ev("e16", "Eli presents the evidence to the tribunal", Q_DRIVE, ending=True),
]
for e in LEDGER:
    e["weight"] = 2  # every weight the same: the weights say nothing

CAST = [("eli", "Eli Voss"), ("mara", "Mara Reil"), ("silas-thorne", "Silas Thorne")]

ACTS = [
    dict(id="b2.act1", events=["e1", "e2", "e3", "e10"], chapter_count=6, turning_point_event="e10", turning_point="x",
         sizing_reason="weight 9 over 4 events, so about 8 chapters [computed: weight 8 over 4 events, about 4 chapters at 2 weight per chapter]"),
    dict(id="b2.act2", events=["e11", "e12", "e13", "e14", "e15", "e16"], chapter_count=6, turning_point_event="e14", turning_point="x",
         sizing_reason="weight 12 over 6 events, about 9 chapters [computed: weight 12 over 6 events, about 6 chapters at 2 weight per chapter]"),
]


def ch(i, events, summary, end_state, pov="eli", **kw):
    return dict(id=f"b2.ch{i:02d}", act="b2.act1" if i <= 6 else "b2.act2", pov=pov, events_covered=events, events_continued=[], summary=summary, purpose="", end_state=end_state, **kw)


CHAPTERS = [
    ch(1, ["e1"], "Eli learns what the corporation hid.", "Eli knows the cause."),
    ch(2, ["e2"], "Eli watches Halloway seal the sector.", "The sector is sealed."),
    ch(3, ["e3"], "Eli hides a copy in the ship's logs.", "A copy is hidden."),
    ch(6, ["e11"], "Mara argues with Eli while Mara pleads and Eli refuses; Mara weeps.", "Mara has pleaded.", pov="silas-thorne"),
    ch(10, ["e10"], "Eli decides to share what he found.", "Eli has chosen. The data is now public on the local network."),
    ch(12, ["e12"], "Eli uploads the data and a lockdown begins.", "The lockdown has begun."),
    ch(13, ["e13"], "The corporation buries it and Eli signs.", "Eli has signed."),
    ch(14, ["e14"], "Eli launches the Kestrel and escapes.", "Eli is away."),
    ch(15, ["e15"], "They allow Eli to escape on condition that he signs.", "The terms are set."),
    ch(16, ["e16"], "Eli presents his evidence.", "The tribunal has the evidence."),
]
