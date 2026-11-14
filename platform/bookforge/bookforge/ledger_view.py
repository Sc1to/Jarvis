"""Text views of the ledger for planning prompts: what has happened, what this stage may use, what is reserved for later."""

from .bible.models import Chapter, Ledger, StoryEvent


def event_line(e: StoryEvent, extra: str = "") -> str:
    flags = [("once" if e.once_only else "repeatable"), e.kind, f"weight {e.weight}"]
    if e.ending:
        flags.append("ENDING")
    if e.pays_off:
        flags.append(f"pays off {e.pays_off}")
    if e.after:
        flags.append("after " + ",".join(e.after))
    return f"- {e.id} ({', '.join(flags)}): {e.text}{extra}"


def events_text(events: list[StoryEvent]) -> str:
    return "\n".join(event_line(e) for e in events) or "none"


def covered_map(chapters: list[Chapter]) -> dict[str, str]:
    """event id -> the first chapter that tells it."""
    out: dict[str, str] = {}
    for c in chapters:
        for ev in c.events_covered:
            out.setdefault(ev, c.id)
    return out


def act_events(ledger: Ledger, ids: list[str]) -> list[StoryEvent]:
    want = set(ids)
    return [e for e in ledger.events if e.id in want or (e.parent and e.parent in want and e.id in want)]


def status_text(ledger: Ledger, mine: set[str], chapters_done: list[Chapter], mine_label: str = "ASSIGNED HERE: plan these") -> str:
    """done / assigned here / reserved for later, with an explicit instruction about what must not be used yet."""
    covered = covered_map(chapters_done)
    done, here, later = [], [], []
    for e in ledger.events:
        if e.id in covered:
            done.append(event_line(e, f"  [told in {covered[e.id]}]"))
        elif e.id in mine:
            here.append(event_line(e))
        elif e.carried_in:
            done.append(event_line(e, "  [already true when the book begins]"))
        else:
            later.append(event_line(e))
    return ("DONE (already told; never tell again, refer to them only as the past):\n" + ("\n".join(done) or "none yet")
            + f"\n\n{mine_label}:\n" + ("\n".join(here) or "none")
            + "\n\nRESERVED FOR LATER (do NOT use, hint at, stage or resolve any of these yet):\n" + ("\n".join(later) or "none"))
