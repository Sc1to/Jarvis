"""Ledger checks: the story events themselves, and how acts, chapters and scenes use them."""

import math
import re
from collections import defaultdict

from .findings import Finding, hard, soft
from .text import WORD, content_stems, dice

MAX_DERIVED_PER_PARENT = 3
MAX_DERIVED_SHARE = 0.4
MAX_DERIVED_ACT_SHARE = 0.34  # derived complications in one act, as a share of its events


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


def resolve_references(raw_events: list) -> int:
    """A model sometimes writes an event's text where an id belongs (pays_off, after, parent). Replace such a value with the id of the
    event whose text or excerpt it matches exactly (ignoring case and punctuation), when exactly one does. Returns how many were fixed.
    The raw events are changed in place; anything that still does not resolve is left for the validator to report."""
    ids = {str(e.get("id")) for e in raw_events if isinstance(e, dict) and e.get("id")}
    by_text: dict[str, set] = defaultdict(set)
    for e in raw_events:
        if isinstance(e, dict) and e.get("id"):
            for key in ("text", "excerpt"):
                if e.get(key):
                    by_text[_norm(str(e[key]))].add(str(e["id"]))

    def fix(value):
        if not isinstance(value, str) or not value or value in ids:
            return value
        hit = by_text.get(_norm(value), set())
        return next(iter(hit)) if len(hit) == 1 else value

    fixed = 0
    for e in raw_events:
        if not isinstance(e, dict):
            continue
        for field in ("pays_off", "parent"):
            new = fix(e.get(field))
            if new != e.get(field):
                e[field], fixed = new, fixed + 1
        if isinstance(e.get("after"), list):
            new_after = [fix(a) for a in e["after"]]
            fixed += sum(a != b for a, b in zip(new_after, e["after"]))
            e["after"] = new_after
    return fixed


def repair_setups(raw_events: list) -> list[str]:
    """Fix the setup/payoff confusions a model makes, in place, and say what was done.

    - `pays_off` names an event that comes LATER: the direction is reversed. When the later event names nothing yet, swap them: the
      earlier event becomes the setup and the later one its payoff.
    - `pays_off` names an earlier event that is not marked a setup: it is a setup; mark it.
    Anything else is left for the validator to report.
    """
    events = [e for e in raw_events if isinstance(e, dict) and e.get("id")]
    pos = {str(e["id"]): i for i, e in enumerate(events)}
    notes: list[str] = []
    for e in events:
        t = str(e.get("pays_off") or "")
        if not t or t not in pos or t == e["id"]:
            continue
        target = events[pos[t]]
        if pos[t] > pos[str(e["id"])]:
            if not target.get("pays_off"):
                e["pays_off"], target["pays_off"] = "", e["id"]
                e["kind"] = "setup"
                if target.get("kind") not in ("payoff", "reveal"):
                    target["kind"] = "payoff"
                notes.append(f"{e['id']} named the later event {t} as the thing it pays off; reversed: {e['id']} is the setup, {t} its payoff")
        elif target.get("kind") != "setup":
            target["kind"] = "setup"
            notes.append(f"{t} is paid off by {e['id']}, so it was marked as a setup")
    return notes


def unpaid_setup_question(event: dict) -> dict:
    return dict(question=f"Setup {event['id']} is planted but never paid off: {event['text'][:140]}",
                why="Something planted for later should be resolved before the book ends, but nothing in the synopsis resolves it.",
                options=[f"Add a payoff: describe the event that resolves {event['id']}", f"It is only atmosphere: change {event['id']} to a plain event"])


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
                out.append(hard(stage, "unknown_event", f"{e['id']}.pays_off names '{target[:60]}', which is not an event id. pays_off takes the ID of the setup event it resolves (for example e5), never its text. "
                                f"Known ids: {', '.join(ids[:40])}", [e["id"]]))
                continue
            if by_id[target].get("kind") != "setup":
                out.append(hard(stage, "payoff_target_not_setup", f"{e['id']} pays off {target}, which is not a setup", [e["id"], target]))
            if index[target] >= index[e["id"]]:
                out.append(hard(stage, "reveal_before_setup", f"{e['id']} comes before the setup {target} it pays off: a reveal cannot precede its setup",
                                [target, e["id"]]))
            payoffs[target].append(e["id"])
            if by_id[target].get("kind") == "setup" and not (set(content_stems(e.get("text", ""))) & set(content_stems(by_id[target].get("text", "")))):
                out.append(soft(stage, "payoff_unrelated_to_setup", f"{e['id']} pays off {target}, but the two share nothing: check that it resolves what {target} planted",
                                [e["id"], target], [by_id[target]["text"][:100], e["text"][:100]]))
    for e in events:
        if e.get("kind") == "setup" and not payoffs.get(e["id"]):
            out.append(soft(stage, "setup_without_payoff", f"setup {e['id']} is never paid off: the author is asked (add the payoff event, or change it to a plain event)", [e["id"]], [e["text"][:120]]))

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

def check_acts(acts: list[dict], events: list[dict], stage: str = "acts", weight_per_chapter: float = 2.0) -> list[Finding]:
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
    out += sizing_plausibility(acts, events, stage, weight_per_chapter)
    out += turning_point_texts(acts, events, stage)
    out += turning_point_positions(acts, events, stage) + check_act_texts(acts, events, stage) + lopsided_acts(acts, stage)
    return out


def act_weight(act: dict, events: list[dict]) -> tuple[int, int]:
    """(total weight, number of events) of an act's events, computed from the ledger (never taken from what the model says)."""
    by_id = {e["id"]: e for e in events}
    evs = [by_id[x] for x in act.get("events", []) or [] if x in by_id]
    return sum(int(e.get("weight", 1)) for e in evs), len(evs)


def sizing_note(act: dict, events: list[dict], weight_per_chapter: float = 2.0) -> str:
    weight, n = act_weight(act, events)
    return f"[computed: weight {weight} over {n} events, about {weight / weight_per_chapter:.1f} chapters at {weight_per_chapter:g} weight per chapter]"


def sizing_plausibility(acts: list[dict], events: list[dict], stage: str = "acts", weight_per_chapter: float = 2.0) -> list[Finding]:
    """The chapter count of an act must fit the weight of its events: about `weight_per_chapter` each, within 0.6x to 1.75x of it.
    Outside that the act is padded (too many chapters for the material) or crammed (too few). The weights are computed here from
    the ledger, so a model that miscounts them in its reasoning is corrected with the real numbers."""
    out: list[Finding] = []
    w = weight_per_chapter
    for a in acts:
        weight, n_events = act_weight(a, events)
        n = a.get("chapter_count")
        if not n or not n_events:
            continue
        per = weight / n
        if per < 0.6 * w or per > 1.75 * w:
            lo, hi = max(1, math.ceil(weight / (1.75 * w))), max(1, math.floor(weight / (0.6 * w)))
            kind = "padded: too many chapters for this material" if per < 0.6 * w else "crammed: too few chapters for this material"
            out.append(hard(stage, "implausible_chapter_count",
                            f"{a['id']}: its events weigh {weight} in total ({n_events} events; the ledger's weights, not your estimate) and you gave {n} chapters, "
                            f"{per:.1f} weight each: {kind}. At about {w:g} weight per chapter that is about {weight / w:.1f} chapters; give between {lo} and {hi}", [a["id"]]))
        if not a.get("sizing_reason"):
            out.append(soft(stage, "no_sizing_reason", f"{a['id']} gives no sizing_reason for its chapter count", [a["id"]]))
    return out


def turning_point_texts(acts: list[dict], events: list[dict], stage: str = "acts") -> list[Finding]:
    """The act's turning_point text must describe its turning_point_event, not another event (soft)."""
    by_id = {e["id"]: e for e in events}
    out = []
    for a in acts:
        ev = by_id.get(a.get("turning_point_event") or "")
        text = str(a.get("turning_point") or "")
        if not ev or not text:
            continue
        stems = set(content_stems(text))
        ev_stems = set(content_stems(ev.get("text", "")))
        extra = stems - ev_stems
        if ev_stems and len(stems & ev_stems) / len(ev_stems) < 0.4 or (stems and len(extra) / len(stems) > 0.35):
            out.append(soft(stage, "turning_point_text_differs", f"{a['id']}: the turning_point text does not match its event {ev['id']} ('{ev.get('text', '')[:80]}'); "
                            "describe that event only", [a["id"], ev["id"]], [text[:120]]))
    return out


def check_chapters(chapters: list[dict], events: list[dict], acts: list[dict] | None = None, stage: str = "chapters",
                   scope: set[str] | None = None) -> list[Finding]:
    """Chapters list events_covered. Each event once (if once_only), in order, each chapter with something new; no event from another act."""
    out: list[Finding] = []
    by_id = {e["id"]: e for e in events}
    index = {e["id"]: n for n, e in enumerate(events)}
    act_of = {ev: a["id"] for a in (acts or []) for ev in a.get("events", []) or []}
    for e in events:  # a derived complication belongs to its parent's act
        if e.get("parent") in act_of:
            act_of.setdefault(e["id"], act_of[e["parent"]])
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
        if e["id"] not in seen and not e.get("carried_in") and (scope is None or e["id"] in scope):
            out.append(hard(stage, "event_not_covered", f"{e['id']} is covered by no chapter: {e['text'][:90]}", [e["id"]]))
    return out


def check_scenes_vs_chapters(scenes: list[dict], chapters: list[dict], events: list[dict], stage: str = "scenes") -> list[Finding]:
    """Scenes carry end_state and the chapter's events: each event of a chapter is shown in a scene, a once_only one in exactly one."""
    out: list[Finding] = []
    once = {e["id"]: e.get("once_only", True) for e in events}
    allowed = {c["id"]: list(c.get("events_covered") or []) for c in chapters}
    by_chapter: dict[str, list[dict]] = defaultdict(list)
    for s in scenes:
        by_chapter[s.get("chapter") or s["id"].rsplit(".s", 1)[0]].append(s)
    for s in scenes:
        ch = s.get("chapter") or s["id"].rsplit(".s", 1)[0]
        if not (s.get("end_state") or "").strip():
            out.append(hard(stage, "scene_without_end_state", f"{s['id']} has no end_state: say where things stand when the scene ends", [s["id"]]))
        for ev in s.get("events") or []:
            if ev not in allowed.get(ch, []):
                out.append(hard(stage, "scene_event_not_in_chapter", f"{s['id']} uses {ev}, which is not an event of {ch}: it is told elsewhere or reserved for later", [s["id"], ev]))
    for cid, evs in allowed.items():
        if cid not in by_chapter:
            continue
        used: dict[str, list[str]] = defaultdict(list)
        for s in by_chapter[cid]:
            for ev in s.get("events") or []:
                used[ev].append(s["id"])
        for ev in evs:
            if not used.get(ev):
                out.append(hard(stage, "chapter_event_not_in_scenes", f"{cid} covers {ev}, but no scene lists it in `events`: show it in the scene where it happens", [cid, ev]))
            elif len(used[ev]) > 1 and once.get(ev, True):
                out.append(hard(stage, "once_only_repeated", f"{ev} is once_only but is shown in {len(used[ev])} scenes of {cid} ({', '.join(used[ev])}): once", [ev] + used[ev]))
    return out


def acts_text_coverage(acts: list[dict], synopsis: str, stage: str = "acts", min_recall: float = 0.4) -> list[Finding]:
    """Without a ledger: every paragraph of the synopsis must be taken up by some act (its summary, purpose or turning point).

    Recall = the share of the paragraph's content words found in the acts' own text. A paragraph that no act reflects, above all
    the last one (the resolution), was dropped when the synopsis was cut into acts.
    """
    paras = paragraphs(synopsis)
    if not paras or not acts:
        return []
    act_stems = set()
    for a in acts:
        act_stems |= set(content_stems(" ".join(str(a.get(k, "")) for k in ("title", "summary", "purpose", "turning_point"))))
    out = []
    for i, p in enumerate(paras):
        stems = set(content_stems(p))
        if not stems:
            continue
        recall = len(stems & act_stems) / len(stems)
        if recall < min_recall:
            last = " (the final paragraph: the resolution)" if i == len(paras) - 1 else ""
            out.append(hard(stage, "synopsis_not_in_acts", f"paragraph {i + 1} of the synopsis{last} is taken up by no act ({recall:.0%} of its words appear in the acts): {p[:100]}...", [f"paragraph {i + 1}"]))
    return out


# ── do the chapters' and scenes' own words describe the events they list? ────

DESCRIBES_MIN = 0.25  # share of an event's content words that must appear in the text that claims it
RETELLS_SOFT, RETELLS_HARD = 0.5, 0.7  # share of ANOTHER once_only event's words found in the text: a retelling
SCENE_WEIGHT = 3.0  # story weight one scene carries; scenes per chapter follow from the chapter's weight


def _stems_wo_names(text: str) -> set:
    from .text import proper_nouns
    return set(content_stems(text, drop=proper_nouns(text)))


def _event_text_checks(unit_id: str, unit_text: str, listed: list[str], by_id: dict, others: list[dict], stage: str, what: str) -> list[Finding]:  # noqa: C901
    out: list[Finding] = []
    unit = _stems_wo_names(unit_text)
    for ev_id in listed:
        ev = by_id.get(ev_id)
        if not ev:
            continue
        need = _stems_wo_names(ev.get("text", ""))
        if len(need) < 2:
            continue  # too little to compare
        recall = len(need & unit) / len(need)
        if recall == 0 and len(need) >= 3:
            out.append(soft(stage, f"{what}_text_misses_event", f"{unit_id} lists {ev_id} but its own text shares no words with it ('{ev['text'][:90]}'): check that it really tells that event", [unit_id, ev_id]))
        elif recall < DESCRIBES_MIN:
            out.append(soft(stage, f"{what}_text_thin_on_event", f"{unit_id} lists {ev_id} but its text barely describes it ({recall:.0%} of the event's words)", [unit_id, ev_id]))
    for ev in others:
        if not ev.get("once_only", True):
            continue
        need = _stems_wo_names(ev.get("text", ""))
        if len(need) < 4:
            continue
        shared = need & unit
        recall = len(shared) / len(need)
        if len(shared) >= 4 and recall >= RETELLS_SOFT:
            make = hard if recall >= RETELLS_HARD else soft
            out.append(make(stage, f"{what}_retells_event", f"{unit_id} describes {ev['id']} again ('{ev['text'][:90]}'), which belongs to another chapter: do not retell it", [unit_id, ev["id"]],
                            [unit_text[:120]]))
    return out


def check_chapter_texts(chapters: list[dict], events: list[dict], stage: str = "chapters") -> list[Finding]:
    """Each chapter's summary must describe the events it lists, and must not retell events that belong to other chapters."""
    by_id = {e["id"]: e for e in events}
    out: list[Finding] = []
    for c in chapters:
        text = " ".join(str(c.get(k, "")) for k in ("purpose", "summary"))  # not the title: its capitalised words would read as names
        mine = set(c.get("events_covered") or [])
        others = [e for e in events if e["id"] not in mine and not e.get("carried_in")]
        out += _event_text_checks(c["id"], text, list(mine), by_id, others, stage, "chapter")
    return out


def check_scene_texts(scenes: list[dict], chapters: list[dict], events: list[dict], stage: str = "scenes") -> list[Finding]:
    """Each scene's purpose and beats must describe the events it lists; they must not retell an event of another chapter."""
    by_id = {e["id"]: e for e in events}
    ch_events = {c["id"]: set(c.get("events_covered") or []) for c in chapters}
    out: list[Finding] = []
    for s in scenes:
        ch = s.get("chapter") or s["id"].rsplit(".s", 1)[0]
        text = " ".join([str(s.get("purpose", ""))] + [str(b) for b in s.get("beats") or []])
        others = [e for e in events if e["id"] not in ch_events.get(ch, set()) and not e.get("carried_in")]
        out += _event_text_checks(s["id"], text, list(s.get("events") or []), by_id, others, stage, "scene")
    return out


def scene_count_plausibility(chapter: dict, scenes: list[dict], events: list[dict], stage: str = "scenes", max_scenes: int = 4) -> list[Finding]:
    """The number of scenes in a chapter must fit the weight of its events: about SCENE_WEIGHT each, within 0.2x..1.75x (padded or crammed)."""
    by_id = {e["id"]: e for e in events}
    weight = sum(int(by_id[x].get("weight", 1)) for x in chapter.get("events_covered") or [] if x in by_id)
    n = len(scenes)
    if not weight or not n:
        return []
    per = weight / n
    lo = max(1, math.ceil(weight / (1.75 * SCENE_WEIGHT)))
    hi = min(max_scenes, max(lo, math.floor(weight / (0.2 * SCENE_WEIGHT))))
    crammed, padded = per > 1.75 * SCENE_WEIGHT, per < 0.2 * SCENE_WEIGHT and n >= 3
    if crammed or padded:
        kind = "crammed: too few scenes for this material" if crammed else "padded: too many scenes for this material"
        return [hard(stage, "implausible_scene_count", f"{chapter['id']}: its events weigh {weight} in total (the ledger's weights) and you gave {n} scene(s), {per:.1f} weight each: {kind}. "
                     f"At about {SCENE_WEIGHT:g} weight per scene give between {lo} and {hi}", [chapter["id"]])]
    return []


# ── the shape of the acts ────────────────────────────────────────────────────

def turning_point_positions(acts: list[dict], events: list[dict], stage: str = "acts") -> list[Finding]:
    """A turning point ends its act. One in the first half of an act's events (with four or more) is out of place."""
    order = {e["id"]: i for i, e in enumerate(events)}
    out = []
    for a in acts:
        mine = sorted([x for x in a.get("events") or [] if x in order], key=order.get)
        tp = a.get("turning_point_event") or ""
        if len(mine) < 4 or tp not in mine:
            continue
        at = mine.index(tp)
        if at < (len(mine) - 1) / 2:
            out.append(hard(stage, "turning_point_not_at_end", f"{a['id']}: the turning point {tp} is event {at + 1} of {len(mine)} in the act. A turning point ends its act: "
                            f"choose a later event, or move the events after {tp} into the next act (the act's last events: {', '.join(mine[-2:])})", [a["id"], tp]))
    return out


def check_act_texts(acts: list[dict], events: list[dict], stage: str = "acts") -> list[Finding]:
    """An act's summary, purpose and turning point must not retell an event that belongs to another act."""
    out = []
    for a in acts:
        text = " ".join(str(a.get(k, "")) for k in ("summary", "purpose", "turning_point"))
        mine = set(a.get("events") or [])
        others = [e for e in events if e["id"] not in mine and not e.get("carried_in")]
        out += [f for f in _event_text_checks(a["id"], text, [], {}, others, stage, "act") if f.code.endswith("retells_event")]
    return out


def lopsided_acts(acts: list[dict], stage: str = "acts", high: float = 0.45, low: float = 0.1) -> list[Finding]:
    """Soft: one act holding almost half the chapters (or nearly none) makes a lopsided book. With three or more acts."""
    total = sum(int(a.get("chapter_count") or 0) for a in acts)
    if len(acts) < 3 or not total:
        return []
    out = []
    for a in acts:
        share = int(a.get("chapter_count") or 0) / total
        if share > high or share < low:
            out.append(soft(stage, "lopsided_acts", f"{a['id']} holds {a.get('chapter_count')} of {total} chapters ({share:.0%}): "
                            + ("consider moving some of its events into a neighbouring act" if share > high else "it is very short next to the others"), [a["id"]]))
    return out
