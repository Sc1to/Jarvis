"""Valid replies for the ledger-driven acts, chapters and scenes of the small test book (4 events, 2 acts, 4 chapters, 2 scenes each)."""

import copy

import yaml

import structure_fakes as sf
from bookforge.bible import store
from bookforge.bible.models import Ledger, StoryEvent


def events():
    base = dict(once_only=True, kind="event", weight=2, source="synopsis")
    return [
        StoryEvent(id="e1", text="Anna finds the ledger", **base),
        StoryEvent(id="e2", text="Anna crosses a name out", after=["e1"], **base),
        StoryEvent(id="e3", text="Jonas learns the truth", after=["e2"], **base),
        StoryEvent(id="e4", text="Anna burns the ledger", after=["e3"], ending=True, **base),
    ]


def install_ledger(project):
    """An accepted ledger for the small book (written as if the ledger layer had run)."""
    store.save_ledger(project, Ledger(events=events(), capacity={"estimated_chapters": 4.0, "thin": False}))
    project.state.set_layer_status("ledger", "accepted", note="4 events")
    project.state.checkpoints["ledger"].status = "approved"
    project.save_state()


def acts():
    a = copy.deepcopy(sf.acts())
    for act, evs, tp in zip(a["acts"], (["e1", "e2"], ["e3", "e4"]), ("e2", "e4")):
        act.update(events=evs, turning_point_event=tp, sizing_reason="two events of weight 2 each fill two chapters")
    return a


END = {1: "Anna holds the ledger in the harbor.", 2: "A name is crossed out and Anna is wounded.", 3: "Jonas knows; the vestry is locked.", 4: "The ledger is ash."}
COVER = {1: ["e1"], 2: ["e2"], 3: ["e3"], 4: ["e4"]}
SUMMARY = {1: "Anna finds a black ledger in the harbor.", 2: "She crosses out a name and pays for it.", 3: "Jonas confronts her in the vestry.", 4: "Anna burns the ledger on the quay."}


def chapters(first, tension=(3, 6, 4, 8)):
    base = sf.chapters_act1() if first == 1 else sf.chapters_act2()
    out = copy.deepcopy(base)
    for c in out["chapters"]:
        n = int(c["id"][-2:])
        c.update(events_covered=COVER[n], end_state=END[n], summary=SUMMARY[n], tension=tension[n - 1])
    return out


BEATS = [
    ("Anna walks the foggy quay and notices a black ledger half buried in netting.", "She hides it inside her coat before the watchman turns."),
    ("A fishwife sells Anna a candle and mentions the harbor master's temper.", "Anna lights the candle in her attic room and opens the book."),
    ("Anna reads a stranger's name aloud and the ink on the page bleeds.", "A cut opens across her shoulder and she bandages it with a torn sleeve."),
    ("Jonas visits the clinic to ask which patients have vanished lately.", "The nurse refuses to answer and bolts the cabinet."),
    ("Jonas follows a trail of candle wax to the vestry door.", "He finds the door locked from within and calls through it."),
    ("Anna admits what the ledger does and offers him the key.", "Jonas pockets the key and swears to keep the secret."),
    ("Anna drags a barrel of tar onto the empty quay at midnight.", "She lights it and feeds the pages into the flames."),
    ("The scar on her shoulder stops aching as the cover curls.", "Dawn comes grey over the water and the watchman walks past without a glance."),
]


def scenes(ch):
    out = sf.scenes_reply(ch)
    for i, s in enumerate(out["scenes"]):
        s["events"] = COVER[ch] if i == 0 else []
        s["end_state"] = f"Scene {ch}.{i + 1} ends with things changed."
        a, b = BEATS[(ch - 1) * 2 + i]
        s["beats"] = [a, b]
    return out


def dump(d):
    return yaml.safe_dump(d, sort_keys=False, allow_unicode=True)


def rules():
    r = [("Divide the book into ACTS by assigning", dump(acts())), ("List the CAST AND WORLD", dump(sf.cast())),
         ("Plan exactly 2 chapters, b1.ch01 to b1.ch02", dump(chapters(1))), ("Plan exactly 2 chapters, b1.ch03 to b1.ch04", dump(chapters(3)))]
    for ch in range(1, 5):
        r.append((f"Scene ids are consecutive: b1.ch{ch:02d}.s1", dump(scenes(ch))))
    return r
