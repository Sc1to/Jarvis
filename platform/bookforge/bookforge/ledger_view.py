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


def status_text(ledger: Ledger, mine: set[str], chapters_done: list[Chapter], mine_label: str = "ASSIGNED HERE: plan these", continuing: set[str] | None = None) -> str:
    """done / assigned here / reserved for later, with an explicit instruction about what must not be used yet."""
    covered = covered_map(chapters_done)
    done, here, later, cont = [], [], [], []
    for e in ledger.events:
        if continuing and e.id in continuing:  # begun in the chapter before and carried on here: not done, not new
            cont.append(event_line(e, f"  [begun in {covered.get(e.id, 'the chapter before')}]"))
        elif e.id in covered:
            done.append(event_line(e, f"  [told in {covered[e.id]}]"))
        elif e.id in mine:
            here.append(event_line(e))
        elif e.carried_in:
            done.append(event_line(e, "  [already true when the book begins]"))
        else:
            later.append(event_line(e))
    return ("DONE (already told; never tell again, refer to them only as the past):\n" + ("\n".join(done) or "none yet")
            + ("\n\nCONTINUING FROM THE CHAPTER BEFORE (this chapter carries it on; do not start it again, do not repeat what was already shown):\n" + "\n".join(cont) if cont else "")
            + f"\n\n{mine_label}:\n" + ("\n".join(here) or "none")
            + "\n\nRESERVED FOR LATER (do NOT use, hint at, stage or resolve any of these yet):\n" + ("\n".join(later) or "none"))


def carried_text(project, max_chars: int = 1800) -> str:
    """What the series ledger says is already true when this book begins (state inherited from the books before it).

    '' for a first book, where the series ledger is still empty."""
    import yaml
    try:
        data = yaml.safe_load((project.root / "ledger.yaml").read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return ""
    if not isinstance(data, dict) or not any(data.values()):
        return ""
    text = yaml.safe_dump({k: v for k, v in data.items() if v}, sort_keys=False, allow_unicode=True).strip()
    return text if len(text) <= max_chars else text[: max_chars - 3].rstrip() + "..."


def carried_for_prompt(project) -> str:
    return carried_text(project) or "nothing: this is the first book"
