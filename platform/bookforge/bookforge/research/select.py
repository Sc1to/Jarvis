"""Research for planning prompts: at most a few notes, chosen by relevance, framed as reference only.

Research is for accuracy and texture. Handing a planner every note invites it to turn notes into events, so each chapter or
scene gets only the notes that match its own text, with a plain statement that they must never become a beat or a plot device.
"""

from ..validators.text import content_stems, dice
from .notes import decisions_text, stores_for

MAX_NOTES = 3
REFERENCE_ONLY = ("Reference only. These notes are for accuracy and texture. They must never become a beat, an event, an obstacle or a plot device: "
                  "do not build anything on them; the story comes from the events above.")


def select_notes(project, text: str, k: int = MAX_NOTES) -> list:
    """The facts most relevant to `text`, best first. Only facts that share vocabulary with it are considered."""
    want = set(content_stems(text))
    scored = []
    for store in stores_for(project).values():
        for f in store.facts():
            have = set(content_stems(f.claim))
            shared = want & have
            if shared:
                scored.append((dice(want, have) + 0.01 * len(shared), f))
    scored.sort(key=lambda x: -x[0])
    return [f for _, f in scored[:k]]


def notes_text(project, text: str, k: int = MAX_NOTES) -> str:
    facts = select_notes(project, text, k)
    body = "\n".join(f"- [{f.id}] {f.claim}" for f in facts) or "none relevant"
    decided = decisions_text(project)
    return f"{REFERENCE_ONLY}\n\n{body}" + (f"\n\n{decided}" if decided else "")
