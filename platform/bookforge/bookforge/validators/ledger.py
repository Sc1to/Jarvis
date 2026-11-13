"""Ledger checks: the story events themselves, and how acts, chapters and scenes use them."""

import math
import re
from collections import defaultdict

from .findings import Finding, hard, soft
from .text import WORD, content_stems, dice

MAX_DERIVED_PER_PARENT = 3
MAX_DERIVED_SHARE = 0.4


def _norm(text: str) -> str:
    return " ".join(w.lower() for w in WORD.findall(text))


def paragraphs(synopsis: str) -> list[str]:
    """The prose paragraphs of a synopsis (headings and rules left out)."""
    out = []
    for block in re.split(r"\n\s*\n", synopsis.strip()):
        lines = [l for l in block.splitlines() if l.strip() and not l.lstrip().startswith("#") and not set(l.strip()) <= set("-*_ ")]
        text = " ".join(l.strip() for l in lines)
        if len(WORD.findall(text)) >= 4:
            out.append(text)
    return out


def check_ledger(events: list[dict], synopsis: str = "", stage: str = "ledger") -> list[Finding]:
    """Structure of the ledger. `events` are plain dicts (as in ledger.yaml), in narrative order."""
    out: list[Finding] = []
    ids = [e["id"] for e in events]
    index = {i: n for n, i in enumerate(ids)}
    if len(index) != len(ids):
        dup = sorted({i for i in ids if ids.count(i) > 1})
        out.append(hard(stage, "duplicate_event_id", f"event ids must be unique; repeated: {', '.join(dup)}", dup))
    by_id = {e["id"]: e for e in events}
    if not events:
        return [hard(stage, "no_events", "the ledger has no events")]

    for e in events:
        for a in e.get("after", []) or []:
            if a not in by_id:
                out.append(hard(stage, "unknown_event", f"{e['id']}: 'after' names {a}, which is not an event", [e["id"], a]))
            elif a == e["id"]:
                out.append(hard(stage, "event_cycle", f"{e['id']} comes after itself", [e["id"]]))
            elif index[a] > index[e["id"]] and e.get("kind") != "flashback" and by_id[a].get("kind") != "flashback":
                out.append(hard(stage, "event_order", f"{e['id']} is listed before {a}, which it needs to follow: put the events in the order they happen",
                                [e["id"], a]))
    out += _cycles(by_id, stage)

    # setups and payoffs
    payoffs: dict[str, list[str]] = defaultdict(list)
    for e in events:
        target = e.get("pays_off") or ""
        if e.get("kind") in ("payoff", "reveal") and not target:
            out.append(hard(stage, "payoff_without_setup", f"{e['id']} is a {e['kind']} but names no setup (pays_off)", [e["id"]]))
        if target:
            if target not in by_id:
                out.append(hard(stage, "unknown_event", f"{e['id']}.pays_off names {target}, which is not an event", [e["id"], target]))
                continue
            if by_id[target].get("kind") != "setup":
                out.append(hard(stage, "payoff_target_not_setup", f"{e['id']} pays off {target}, which is not a setup", [e["id"], target]))
            if index[target] >= index[e["id"]]:
                out.append(hard(stage, "reveal_before_setup", f"{e['id']} comes before the setup {target} it pays off: a reveal cannot precede its setup",
                                [target, e["id"]]))
            payoffs[target].append(e["id"])
    for e in events:
        if e.get("kind") == "setup" and not payoffs.get(e["id"]):
            out.append(hard(stage, "setup_without_payoff", f"setup {e['id']} is never paid off: add the payoff event or drop the setup", [e["id"]], [e["text"][:120]]))

    # the resolution
    if not any(e.get("ending") for e in events):
        out.append(hard(stage, "no_resolution", "no event is marked ending: true. The synopsis's resolution must be a ledger event"))
    else:
        first_end = min(index[e["id"]] for e in events if e.get("ending"))
        if first_end < 0.6 * len(events):
            out.append(soft(stage, "early_resolution", "the first ending event comes in the first 60% of the events; check the order", [ids[first_end]]))

    # derived events: minor complications only
    derived = [e for e in events if e.get("source") == "derived"]
    per_parent: dict[str, int] = defaultdict(int)
    for e in derived:
        p = e.get("parent") or ""
        if p not in by_id or by_id[p].get("source") == "derived":
            out.append(hard(stage, "derived_without_parent", f"{e['id']} is derived but its parent '{p}' is not a top-level event", [e["id"]]))
            continue
        per_parent[p] += 1
        if int(e.get("weight", 1)) != 1 or e.get("kind", "event") != "event" or e.get("ending"):
            out.append(hard(stage, "derived_not_minor", f"{e['id']}: a derived event is a minor complication (weight 1, kind event, not ending), never major plot", [e["id"]]))
        if index[e["id"]] <= index[p]:
            out.append(hard(stage, "event_order", f"{e['id']} must come after its parent {p}", [e["id"], p]))
        if p not in (e.get("after") or []):
            out.append(hard(stage, "derived_not_after_parent", f"{e['id']} must list its parent {p} in 'after'", [e["id"], p]))
    for p, n in per_parent.items():
        if n > MAX_DERIVED_PER_PARENT:
            out.append(hard(stage, "too_many_derived", f"{p} has {n} derived complications (at most {MAX_DERIVED_PER_PARENT})", [p]))
    if derived and len(derived) > MAX_DERIVED_SHARE * len(events):
        out.append(soft(stage, "mostly_derived", f"{len(derived)} of {len(events)} events are derived by the planner: the synopsis may be too thin; consider asking the author"))

    # the words of the synopsis
    if synopsis.strip():
        out += _synopsis_coverage(events, synopsis, stage)
    return out


def _cycles(by_id: dict, stage: str) -> list[Finding]:
    state: dict[str, int] = {}
    found: list[Finding] = []

    def visit(i, path):
        state[i] = 1
        for a in by_id[i].get("after", []) or []:
            if a not in by_id:
                continue
            if state.get(a) == 1:
                found.append(hard(stage, "event_cycle", "events wait on each other in a circle: " + " -> ".join(path + [a]), path + [a]))
            elif a not in state:
                visit(a, path + [a])
        state[i] = 2

    for i in by_id:
        if i not in state:
            visit(i, [i])
    return found


def _synopsis_coverage(events: list[dict], synopsis: str, stage: str) -> list[Finding]:
    out: list[Finding] = []
    paras = paragraphs(synopsis)
    norm_paras = [_norm(p) for p in paras]
    covered = [False] * len(paras)
    for e in events:
        ex = _norm(e.get("excerpt", "") or "")
        if e.get("source", "synopsis") != "synopsis":
            continue
        if not ex:
            out.append(hard(stage, "no_excerpt", f"{e['id']} has no 'excerpt': quote the words of the synopsis it comes from", [e["id"]]))
            continue
        hits = [i for i, p in enumerate(norm_paras) if ex in p]
        if not hits:
            out.append(hard(stage, "excerpt_not_in_synopsis", f"{e['id']}: its excerpt is not a verbatim quotation of the synopsis. Quote exact words", [e["id"]], [e["excerpt"][:100]]))
        for i in hits:
            covered[i] = True
    for i, ok in enumerate(covered):
        if not ok:
            last = " (the final paragraph: the resolution)" if i == len(paras) - 1 else ""
            out.append(hard(stage, "synopsis_not_covered", f"paragraph {i + 1} of the synopsis{last} has no event: {paras[i][:110]}...", [f"paragraph {i + 1}"]))
    if paras and not any(e.get("ending") and _norm(e.get("excerpt", "")) in norm_paras[-1] for e in events if e.get("excerpt")):
        out.append(hard(stage, "resolution_not_final_paragraph", "no ending event comes from the synopsis's final paragraph"))
    return out


# ── acts, chapters and scenes against the ledger ─────────────────────────────

def check_acts(acts: list[dict], events: list[dict], stage: str = "acts") -> list[Finding]:
    out: list[Finding] = []
    by_id = {e["id"]: e for e in events}
    index = {e["id"]: n for n, e in enumerate(events)}
    owner: dict[str, str] = {}
    for a in acts:
        for ev in a.get("events", []) or []:
            if ev not in by_id:
                out.append(hard(stage, "unknown_event", f"{a['id']} lists {ev}, which is not an event", [a["id"], ev]))
            elif ev in owner:
                out.append(hard(stage, "event_in_two_acts", f"{ev} is in both {owner[ev]} and {a['id']}: every event belongs to exactly one act", [ev, owner[ev], a["id"]]))
            else:
                owner[ev] = a["id"]
        tp = a.get("turning_point_event") or ""
        if not tp:
            out.append(hard(stage, "turning_point_without_event", f"{a['id']} names no turning_point_event", [a["id"]]))
        elif tp not in (a.get("events") or []):
            out.append(hard(stage, "turning_point_not_in_act", f"{a['id']}: the turning point {tp} is not one of the act's events", [a["id"], tp]))
    for e in events:
        if e["id"] not in owner and not e.get("carried_in"):
            out.append(hard(stage, "event_in_no_act", f"{e['id']} belongs to no act: {e['text'][:90]}", [e["id"]]))
    # acts follow ledger order
    last = -1
    for a in acts:
        idxs = [index[x] for x in a.get("events", []) or [] if x in index]
        if idxs and min(idxs) < last:
            out.append(hard(stage, "acts_out_of_order", f"{a['id']} holds events that come before the previous act's events", [a["id"]]))
        if idxs:
            last = max(last, max(idxs))
    if acts:
        final = acts[-1]
        endings = [e["id"] for e in events if e.get("ending")]
        missing = [x for x in endings if x not in (final.get("events") or [])]
        if endings and missing:
            out.append(hard(stage, "resolution_not_in_last_act", f"the last act ({final['id']}) must contain the resolution; missing: {', '.join(missing)}", [final["id"]] + missing))
    out += sizing_plausibility(acts, events, stage)
    return out


def sizing_plausibility(acts: list[dict], events: list[dict], stage: str = "acts") -> list[Finding]:
    """Warn when the chapter count of an act does not fit the weight of its events (soft: sizing is the model's call)."""
    out: list[Finding] = []
    by_id = {e["id"]: e for e in events}
    for a in acts:
        evs = [by_id[x] for x in a.get("events", []) or [] if x in by_id]
        weight = sum(int(e.get("weight", 1)) for e in evs)
        n = a.get("chapter_count")
        if not n or not evs:
            continue
        per = weight / n
        if per < 0.8 or per > 4.5:
            out.append(soft(stage, "implausible_chapter_count",
                            f"{a['id']}: {n} chapters for {len(evs)} events of total weight {weight} ({per:.1f} weight per chapter; "
                            "plausible is about 1 to 4): too many chapters pads the story, too few crams it", [a["id"]]))
        if not a.get("sizing_reason"):
            out.append(soft(stage, "no_sizing_reason", f"{a['id']} gives no sizing_reason for its chapter count", [a["id"]]))
    return out


def check_chapters(chapters: list[dict], events: list[dict], acts: list[dict] | None = None, stage: str = "chapters") -> list[Finding]:
    """Chapters list events_covered. Each event once (if once_only), in order, each chapter with something new; no event from another act."""
    out: list[Finding] = []
    by_id = {e["id"]: e for e in events}
    index = {e["id"]: n for n, e in enumerate(events)}
    act_of = {ev: a["id"] for a in (acts or []) for ev in a.get("events", []) or []}
    told: dict[str, str] = {}
    seen: set[str] = set()
    last_idx = -1
    for c in chapters:
        covered = c.get("events_covered") or []
        new = [x for x in covered if x not in seen]
        if not covered:
            out.append(hard(stage, "chapter_without_events", f"{c['id']} lists no events_covered", [c["id"]]))
        for ev in covered:
            if ev not in by_id:
                out.append(hard(stage, "unknown_event", f"{c['id']} covers {ev}, which is not an event", [c["id"], ev]))
                continue
            if acts and act_of.get(ev) and c.get("act") and act_of[ev] != c["act"]:
                out.append(hard(stage, "event_from_other_act", f"{c['id']} ({c['act']}) covers {ev}, which belongs to {act_of[ev]}: leave it for that act", [c["id"], ev]))
            if ev in told and by_id[ev].get("once_only", True):
                out.append(hard(stage, "once_only_repeated", f"{ev} is once_only but is told in both {told[ev]} and {c['id']}", [ev, told[ev], c["id"]], [by_id[ev]["text"][:120]]))
            else:
                told.setdefault(ev, c["id"])
            for a in by_id[ev].get("after", []) or []:
                if a in by_id and a not in seen and a not in covered and not by_id[a].get("carried_in") and by_id[ev].get("kind") != "flashback":
                    out.append(hard(stage, "event_before_cause", f"{c['id']} covers {ev} before {a}, which it follows", [c["id"], ev, a]))
        idxs = [index[x] for x in covered if x in index and by_id[x].get("kind") != "flashback"]
        if idxs and min(idxs) < last_idx - 0:
            if any(i < last_idx for i in idxs):
                out.append(hard(stage, "chapters_out_of_order", f"{c['id']} covers events that belong earlier in the story than the previous chapter", [c["id"]]))
        if idxs:
            last_idx = max(last_idx, max(idxs))
        if covered and not new:
            out.append(hard(stage, "chapter_nothing_new", f"{c['id']} brings no event that has not already happened: every chapter must move the story forward (add a new event, or a minor complication derived from one)", [c["id"]]))
        seen.update(covered)
    for e in events:
        if e["id"] not in seen and not e.get("carried_in"):
            out.append(hard(stage, "event_not_covered", f"{e['id']} is covered by no chapter: {e['text'][:90]}", [e["id"]]))
    return out


def check_scenes_vs_chapters(scenes: list[dict], chapters: list[dict], events: list[dict], stage: str = "scenes") -> list[Finding]:
    """Scenes carry end_state; scene events stay inside their chapter's events; ledger status: no event reserved for later."""
    out: list[Finding] = []
    allowed = {c["id"]: set(c.get("events_covered") or []) for c in chapters}
    seen_chapter: dict[str, str] = {}
    for c in chapters:
        for ev in c.get("events_covered") or []:
            seen_chapter.setdefault(ev, c["id"])
    for s in scenes:
        ch = s.get("chapter") or s["id"].rsplit(".s", 1)[0]
        if not (s.get("end_state") or "").strip():
            out.append(hard(stage, "scene_without_end_state", f"{s['id']} has no end_state", [s["id"]]))
        for ev in s.get("events") or []:
            if ev not in allowed.get(ch, set()):
                out.append(hard(stage, "scene_event_not_in_chapter", f"{s['id']} uses {ev}, which is not an event of {ch}", [s["id"], ev]))
    return out
