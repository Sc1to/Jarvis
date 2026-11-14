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


PAYOFF_MIN_SHARED = 3  # content words a later event must share with the setup to be taken for its payoff
PAYOFF_MIN_DICE = 0.25


def payoff_candidates(setup: dict, events: list[dict]) -> list[dict]:
    """Later events that resolve the setup by meaning: they share its content words (names left out), best first. An event that already pays
    off another setup, or is itself a setup, is not a candidate."""
    need = _stems_wo_names(setup.get("excerpt") or setup.get("text", "")) | _stems_wo_names(setup.get("text", ""))
    index = {e["id"]: n for n, e in enumerate(events)}
    scored = []
    for e in events[index[setup["id"]] + 1:]:
        if e.get("pays_off") or e.get("kind") == "setup":
            continue
        have = _stems_wo_names(e.get("text", "")) | _stems_wo_names(e.get("excerpt", ""))
        shared = need & have
        d = dice(need, have)
        if len(shared) >= PAYOFF_MIN_SHARED and d >= PAYOFF_MIN_DICE:
            scored.append((d, e))
    scored.sort(key=lambda x: -x[0])
    return [e for _, e in scored]


def link_payoffs_by_meaning(events: list[dict]) -> tuple[list[str], dict[str, list[dict]]]:
    """Setups nothing names as paid off, but a later event clearly resolves: link them instead of asking the author (events changed in place).
    Returns (notes on what was linked, the setups still unresolved with their candidates). One clearly best candidate links; several close
    ones are left for the author, who is shown them."""
    paid = {e.get("pays_off") for e in events if e.get("pays_off")}
    notes, open_ = [], {}
    for e in events:
        if e.get("kind") != "setup" or e["id"] in paid:
            continue
        cands = payoff_candidates(e, events)
        if cands and (len(cands) == 1 or _score(e, cands[0]) >= 1.5 * _score(e, cands[1])):
            target = cands[0]
            target["pays_off"] = e["id"]
            if target.get("kind", "event") == "event":
                target["kind"] = "payoff"
            paid.add(e["id"])
            notes.append(f"{target['id']} resolves the setup {e['id']} by meaning, so it was linked as its payoff ({target['text'][:70]})")
        else:
            open_[e["id"]] = cands[:3]
    return notes, open_


def _score(setup: dict, event: dict) -> float:
    need = _stems_wo_names(setup.get("excerpt") or setup.get("text", "")) | _stems_wo_names(setup.get("text", ""))
    return dice(need, _stems_wo_names(event.get("text", "")) | _stems_wo_names(event.get("excerpt", ""))) or 1e-9


def unpaid_setup_question(event: dict, candidates: list[dict] | None = None) -> dict:
    """A question about a setup nothing resolves: it quotes the setup's words, and offers a candidate when there is one. Only asked after the
    meaning search found no clear payoff."""
    quote = (event.get("excerpt") or event.get("text", ""))[:200]
    options = [f"{c['id']} resolves it ('{c['text'][:80]}'): link it as the payoff" for c in candidates or []]
    options += [f"Add an event that resolves what '{quote[:80]}' planted", f"It is only atmosphere: change {event['id']} to a plain event"]
    return dict(question=f"Setup {event['id']} is planted but nothing resolves it: \"{quote}\"",
                why="Something planted for later should be resolved before the book ends; no later event shares its meaning.",
                options=options[:4], type="unpaid_setup", quotes=[quote])


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

    # the resolution: exactly one event, and at most one central decision
    endings = [e["id"] for e in events if e.get("ending")]
    if not endings:
        out.append(hard(stage, "no_resolution", "no event is marked ending: true. The synopsis's resolution must be a ledger event"))
    else:
        first_end = min(index[x] for x in endings)
        if len(endings) > 1:
            out.append(hard(stage, "several_endings", f"{', '.join(endings)} are all marked ending: true, but a book has one resolution. Keep ending: true on the event that resolves the story "
                            "(the last of them if it unfolds over several) and mark the others as ordinary events", endings))
        if first_end < 0.6 * len(events):
            out.append(soft(stage, "early_resolution", "the first ending event comes in the first 60% of the events; check the order", [ids[first_end]]))
    decisions = [e["id"] for e in events if e.get("decision")]
    if len(decisions) > 1:
        out.append(hard(stage, "several_decisions", f"{', '.join(decisions)} are all marked decision: true; the book's central decision is one event (the choice the story turns on)", decisions))
    elif not decisions and len(events) >= 6:
        out.append(soft(stage, "no_central_decision", "no event is marked decision: true: name the choice the story turns on (it is what the last act's turning point should be)"))
    out += weights_flat(events, stage)

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

    for e in events:  # the event text is a paraphrase of its excerpt, not an addition to it
        if e.get("source", "synopsis") != "synopsis" or not (e.get("excerpt") or "").strip():
            continue
        need, have = _stems_wo_names(e.get("text", "")), _stems_wo_names(e["excerpt"])
        if len(need) >= 4 and len(need & have) / len(need) < EXCERPT_RECALL:  # short events paraphrase too freely to judge
            out.append(soft(stage, "event_text_not_in_excerpt", f"{e['id']}: its text says more than its excerpt does ('{e['text'][:80]}'): keep the event to what the quoted words say",
                            [e["id"]], [e["excerpt"][:120]]))

    out += causal_order(events, stage)
    # the words of the synopsis
    if synopsis.strip():
        out += _synopsis_coverage(events, synopsis, stage)
    return out


WEIGHT_MAX_SHARE = 0.7  # no weight may be given to more than this share of the events: the weights must tell events apart


def weights_flat(events: list[dict], stage: str = "ledger") -> list[Finding]:
    """The weights size the book, so they have to discriminate: one value on nearly every event carries no information."""
    mine = [e for e in events if e.get("source", "synopsis") != "derived" and not e.get("carried_in")]
    if len(mine) < 6:
        return []
    counts: dict[int, int] = defaultdict(int)
    for e in mine:
        counts[int(e.get("weight", 1))] += 1
    weight, n = max(counts.items(), key=lambda kv: kv[1])
    if n / len(mine) > WEIGHT_MAX_SHARE:
        return [hard(stage, "weights_flat", f"{n} of {len(mine)} events have weight {weight}: weights that hardly vary say nothing about how much story each event carries. "
                     "Use the scale: 1 a beat inside a scene, 2 an event that changes a situation and fills a scene, 3 a chapter-sized event (a reveal, a reversal, a decision, a confrontation); "
                     "reserve 3 for the few events the story turns on, and give small events 1", [])]
    return []


_CONDITIONAL = ("only if", "only on the condition", "on the condition that", "on the condition", "in exchange for", "in return for", "provided that", "unless", "but only", "only when", "only once", "only after")
_CAUSE = ("because", "as a result of", "so that")


def _plain_stems(text: str) -> set:
    """Stems of the content words with every capitalised word (names) left out."""
    return set(content_stems(text, drop={w.lower() for w in WORD.findall(text) if w[0].isupper()}))


def _split_marker(excerpt: str):
    """(main clause, marker, clause after the marker) for the first causal marker in the excerpt, else None."""
    from .audit import CAUSAL
    m = CAUSAL.search(excerpt)
    if not m:
        return None
    return excerpt[:m.start()], m.group(1).lower(), excerpt[m.end():]


def causal_order(events: list[dict], stage: str = "ledger") -> list[Finding]:
    """A condition comes before what it conditions, a cause before its effect. The marker in an event's own excerpt says which way:
    "A, but only on the condition that B": this event grants A on condition B, so the event that IS A comes after it, never before;
    "A because B": the event that is B comes before this one. Falls silent when no other event clearly matches the clause."""
    out: list[Finding] = []
    index = {e["id"]: n for n, e in enumerate(events)}
    for e in events:
        if e.get("source", "synopsis") != "synopsis" or not e.get("excerpt"):
            continue
        parts = _split_marker(e["excerpt"])
        if not parts:
            continue
        main, marker, rest = parts
        for other in events:
            if other["id"] == e["id"] or other.get("kind") == "flashback" or e.get("kind") == "flashback":
                continue
            if marker in _CONDITIONAL:
                clause, wrong = main, index[other["id"]] < index[e["id"]]  # the thing it conditions already happened
                what = f"{e['id']} sets a condition on {other['id']} ('{marker}') but is listed after it, when {other['id']} has already happened and the condition has nothing left to hold over"
            elif marker in _CAUSE:
                clause, wrong = rest, index[other["id"]] > index[e["id"]]
                what = f"{e['id']} happens because of {other['id']} ('{marker}') but is listed before it"
            else:
                continue
            if not wrong:
                continue
            a, b = _plain_stems(clause), _plain_stems(other.get("text", ""))
            shared = a & b
            if not shared or len(shared) / min(len(a), len(b)) < 0.5:
                continue
            make = hard if len(shared) >= 2 else soft  # one shared word is a hint, two a match
            out.append(make(stage, "causal_order", f"{what}: the cause or condition must come first (put it before, and list it in 'after')", [e["id"], other["id"]],
                            [e["excerpt"][:140], other.get("text", "")[:120]]))
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
    out += _sentence_coverage(events, paras, stage)
    for i, ok in enumerate(covered):
        if not ok:
            last = " (the final paragraph: the resolution)" if i == len(paras) - 1 else ""
            out.append(hard(stage, "synopsis_not_covered", f"paragraph {i + 1} of the synopsis{last} has no event: {paras[i][:110]}...", [f"paragraph {i + 1}"]))
    if paras and not any(e.get("ending") and _norm(e.get("excerpt", "")) in norm_paras[-1] for e in events if e.get("excerpt")):
        out.append(hard(stage, "resolution_not_final_paragraph", "no ending event comes from the synopsis's final paragraph"))
    return out


SENTENCE_RECALL = 0.5  # share of a sentence's content words the events quoting it must carry
MIN_SENTENCE_WORDS = 6  # shorter sentences are a heading, a transition or an aside


def _sentence_coverage(events: list[dict], paras: list[str], stage: str) -> list[Finding]:
    """Every sentence that carries plot is quoted by an event. A paragraph with one event would hide a dropped sentence; this does not.
    Pure description is accepted per finding (validation/accepted.json) rather than guessed at."""
    from .text import sentences
    quotes = [(_norm(e["excerpt"]), set(content_stems(e["excerpt"]))) for e in events if e.get("source", "synopsis") == "synopsis" and (e.get("excerpt") or "").strip()]
    out = []
    for para in paras:
        pn = _norm(para)
        for sent in sentences(para):
            if len(WORD.findall(sent)) < MIN_SENTENCE_WORDS:
                continue
            sn, stems = _norm(sent), set(content_stems(sent))
            if not stems:
                continue
            got: set = set()
            for en, es in quotes:
                if en in sn or sn in en or (en in pn and len(es & stems) >= 3):
                    got |= es & stems
            if len(got) / len(stems) < SENTENCE_RECALL:
                out.append(hard(stage, "sentence_not_covered", f"this sentence of the synopsis is quoted by no event: \"{sent[:140]}\". Add an event that quotes it, or widen the excerpt of the event that tells it", [sent[:60]], [sent[:140]]))
    return out


# ── acts, chapters and scenes against the ledger ─────────────────────────────

def check_acts(acts: list[dict], events: list[dict], stage: str = "acts", weight_per_chapter: float = 2.0, capacity_estimate: float | None = None,
               tolerance: float = 0.2) -> list[Finding]:
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
        decisions = [e["id"] for e in events if e.get("decision")]
        tp_final = final.get("turning_point_event") or ""
        if decisions and tp_final and tp_final not in decisions + endings:
            out.append(hard(stage, "final_turning_point_is_transition", f"the last act's turning point is {tp_final}, but the book turns on {', '.join(decisions)}: the final turning point is the central decision "
                            f"or the resolution, not a transition such as a departure or an arrival. Use {decisions[0]} (or the ending {', '.join(endings)})", [final["id"], tp_final]))
        missing = [x for x in endings if x not in (final.get("events") or [])]
        if endings and missing:
            out.append(hard(stage, "resolution_not_in_last_act", f"the last act ({final['id']}) must contain the resolution; missing: {', '.join(missing)}", [final["id"]] + missing))
    out += sizing_plausibility(acts, events, stage, weight_per_chapter)
    out += sizing_consistency(acts, events, stage) + acts_vs_capacity(acts, capacity_estimate, tolerance, stage)
    out += turning_point_texts(acts, events, stage)
    out += turning_point_positions(acts, events, stage) + check_act_texts(acts, events, stage) + lopsided_acts(acts, stage)
    out += resolution_in_summary(acts, events, stage)
    return out


def act_weight(act: dict, events: list[dict]) -> tuple[int, int]:
    """(total weight, number of events) of an act's events, computed from the ledger (never taken from what the model says)."""
    by_id = {e["id"]: e for e in events}
    evs = [by_id[x] for x in act.get("events", []) or [] if x in by_id]
    return sum(int(e.get("weight", 1)) for e in evs), len(evs)


def sizing_note(act: dict, events: list[dict], weight_per_chapter: float = 2.0) -> str:
    weight, n = act_weight(act, events)
    return f"[computed: weight {weight} over {n} events, about {weight / weight_per_chapter:.1f} chapters at {weight_per_chapter:g} weight per chapter]"


def act_capacity(act: dict, events: list[dict]) -> tuple[int, int, int, int]:
    """(most chapters the act's events can supply, events, major events that may take a second chapter, minor complications that may be derived).

    Every chapter needs an event of its own: one chapter per event, a second for each weight 3 event, and up to a third of the events again as
    derived complications. An act asking for more chapters than that cannot be planned, however often the model tries."""
    by_id = {e["id"]: e for e in events}
    mine = [by_id[x] for x in act.get("events") or [] if x in by_id]
    majors = sum(1 for e in mine if int(e.get("weight", 1)) >= 3)
    derived = max(1, round(MAX_DERIVED_ACT_SHARE * len(mine))) if mine else 0
    return len(mine) + majors + derived, len(mine), majors, derived


def sizing_plausibility(acts: list[dict], events: list[dict], stage: str = "acts", weight_per_chapter: float = 2.0) -> list[Finding]:
    """The chapter count of an act is an estimate (the chapters stage sizes the act from its events), so a count that does not fit is only a soft warning. It should fit the weight of its events: about `weight_per_chapter` each, within 0.6x to 1.75x of it.
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
            out.append(soft(stage, "implausible_chapter_count",
                            f"{a['id']}: its events weigh {weight} in total ({n_events} events; the ledger's weights, not your estimate) and you gave {n} chapters, "
                            f"{per:.1f} weight each: {kind}. At about {w:g} weight per chapter that is about {weight / w:.1f} chapters; give between {lo} and {hi}", [a["id"]]))
        cap, n_ev, majors, derived = act_capacity(a, events)
        if n > cap:
            out.append(soft(stage, "chapter_count_exceeds_capacity",
                            f"{a['id']} plans {n} chapters, but its {n_ev} events can supply at most {cap}: every chapter needs a new event of its own, a weight 3 event may take a second chapter "
                            f"({majors} here) and up to {derived} minor complication(s) may be derived. The chapters stage will plan no more than {cap}", [a["id"]]))
        if not a.get("sizing_reason"):
            out.append(soft(stage, "no_sizing_reason", f"{a['id']} gives no sizing_reason for its chapter count", [a["id"]]))
    return out


_CHAPTERS_SAID = re.compile(r"(\d+(?:\.\d+)?)\s*(?:-\s*\d+(?:\.\d+)?\s*)?chapters?", re.I)
_WEIGHT_SAID = re.compile(r"weigh(?:s|ts|t)?\s*(?:of|is|at|about|:)?\s*(\d+)(?!\s*(?:each|per|apiece|a piece|or|/))", re.I)  # "weight 2 each" is one event's, not the act's
OVERRIDE = "override:"


def sizing_consistency(acts: list[dict], events: list[dict], stage: str = "acts") -> list[Finding]:
    """What an act says about its own size must agree with its numbers: the weight it quotes is the ledger's weight, the chapters it names are its
    chapter_count (one chapter of slack). The computed note the system appends is not the model's reasoning and is left out. An act that means to
    differ from the estimate says so: a sizing_reason starting `override:`."""
    out: list[Finding] = []
    for a in acts:
        reason = str(a.get("sizing_reason") or "").split("[computed:")[0].strip()
        if not reason or reason.lower().startswith(OVERRIDE):
            continue
        weight, _ = act_weight(a, events)
        said_w = _WEIGHT_SAID.search(reason)
        if said_w and weight and int(said_w.group(1)) != weight:
            out.append(hard(stage, "sizing_reason_mismatch", f"{a['id']}: its sizing_reason says weight {said_w.group(1)} but the ledger's weights for its events add up to {weight}. "
                            f"Quote the real weight, or start the reason with '{OVERRIDE}' if you mean to depart from it", [a["id"]], [reason[:140]]))
        said_c = _CHAPTERS_SAID.search(reason)
        n = a.get("chapter_count")
        if said_c and n and abs(float(said_c.group(1)) - int(n)) > 1:
            out.append(hard(stage, "sizing_reason_mismatch", f"{a['id']}: its sizing_reason talks of {said_c.group(1)} chapters but chapter_count is {n}. "
                            f"Make them agree, or start the reason with '{OVERRIDE}' and say why the count differs", [a["id"]], [reason[:140]]))
    return out


def acts_vs_capacity(acts: list[dict], estimate: float | None, tolerance: float = 0.2, stage: str = "acts") -> list[Finding]:
    """The acts' chapters add up to about what the ledger said the story carries. A difference beyond the tolerance needs a stated reason."""
    if not estimate or not acts:
        return []
    total = sum(int(a.get("chapter_count") or 0) for a in acts)
    if abs(total - estimate) / estimate <= tolerance:
        return []
    if any(str(a.get("sizing_reason") or "").strip().lower().startswith(OVERRIDE) for a in acts):
        return []
    return [hard(stage, "acts_differ_from_capacity", f"the acts plan {total} chapters in total but the ledger's own estimate is {estimate:g} (its weights over the weight-per-chapter figure). "
                 f"Bring them within {tolerance:.0%}, or start the sizing_reason of the act that departs with '{OVERRIDE}' and say why", [a["id"] for a in acts])]


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
    span: dict[str, int] = {}  # chapters an event has taken so far
    previous_active: set[str] = set()
    last_idx = -1
    for c in chapters:
        covered = c.get("events_covered") or []
        continued = c.get("events_continued") or []
        new = [x for x in covered if x not in seen]
        if not covered and not continued:
            out.append(hard(stage, "chapter_without_events", f"{c['id']} lists no events_covered", [c["id"]]))
        for ev in continued:  # a major event that began in the chapter before and carries on here
            if ev not in by_id:
                out.append(hard(stage, "unknown_event", f"{c['id']} continues {ev}, which is not an event", [c["id"], ev]))
            elif ev not in previous_active:
                out.append(hard(stage, "continued_event_not_begun", f"{c['id']} continues {ev}, but the chapter before does not tell or continue it: an event is continued only in the chapter right after it begins", [c["id"], ev]))
            elif int(by_id[ev].get("weight", 1)) < 3:
                out.append(hard(stage, "only_major_events_continue", f"{c['id']} continues {ev}, which weighs {by_id[ev].get('weight', 1)}: only a weight 3 event (a climax, a confrontation, a turning point) may take a second chapter", [c["id"], ev]))
            elif span.get(ev, 1) >= 2:
                out.append(hard(stage, "event_spans_too_many_chapters", f"{c['id']} continues {ev} for a third chapter: no event takes more than two", [c["id"], ev]))
            else:
                span[ev] = span.get(ev, 1) + 1
            if acts and act_of.get(ev) and c.get("act") and act_of[ev] != c["act"]:
                out.append(hard(stage, "event_from_other_act", f"{c['id']} ({c['act']}) continues {ev}, which belongs to {act_of[ev]}: leave it for that act", [c["id"], ev]))
        for ev in covered:
            if ev not in by_id:
                out.append(hard(stage, "unknown_event", f"{c['id']} covers {ev}, which is not an event", [c["id"], ev]))
                continue
            if acts and act_of.get(ev) and c.get("act") and act_of[ev] != c["act"]:
                out.append(hard(stage, "event_from_other_act", f"{c['id']} ({c['act']}) covers {ev}, which belongs to {act_of[ev]}: leave it for that act", [c["id"], ev]))
            span.setdefault(ev, 1)
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
        if covered and not new and not continued:
            out.append(hard(stage, "chapter_nothing_new", f"{c['id']} brings no event that has not already happened: every chapter must move the story forward (add a new event, continue a weight 3 event from the chapter before, or add a minor complication derived from an event). If the act has no more events, end it here with fewer chapters", [c["id"]]))
        seen.update(covered)
        previous_active = set(covered) | set(continued)
    for e in events:
        if e["id"] not in seen and not e.get("carried_in") and (scope is None or e["id"] in scope):
            out.append(hard(stage, "event_not_covered", f"{e['id']} is covered by no chapter: {e['text'][:90]}", [e["id"]]))
    return out


def check_scenes_vs_chapters(scenes: list[dict], chapters: list[dict], events: list[dict], stage: str = "scenes") -> list[Finding]:
    """Scenes carry end_state and the chapter's events: each event of a chapter is shown in a scene, a once_only one in exactly one."""
    out: list[Finding] = []
    once = {e["id"]: e.get("once_only", True) for e in events}
    allowed = {c["id"]: list(c.get("events_covered") or []) + list(c.get("events_continued") or []) for c in chapters}
    begun = {c["id"]: list(c.get("events_covered") or []) for c in chapters}  # only these must be shown in a scene of the chapter
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
    for cid, evs in begun.items():
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

EXCERPT_RECALL = 0.3  # share of an event's words that must come from the excerpt it quotes
DESCRIBES_MIN = 0.25  # share of an event's content words that must appear in the text that claims it
RETELLS_SOFT, RETELLS_HARD = 0.5, 0.7  # share of ANOTHER once_only event's words found in the text: a retelling
SCENE_WEIGHT = 3.0  # story weight one scene carries; scenes per chapter follow from the chapter's weight


def _stems_wo_names(text: str) -> set:
    from .text import proper_nouns
    return set(content_stems(text, drop=proper_nouns(text)))


def _event_text_checks(unit_id: str, unit_text: str, listed: list[str], by_id: dict, others: list[dict], stage: str, what: str,
                       where: dict | None = None, soften: set | None = None) -> list[Finding]:  # noqa: C901
    """`where` says why an event is not this unit's ('was already told in b2.ch01', 'is reserved for a later act'); `soften` lists events whose
    retelling is only soft (the next chapters of the same act: a chapter may touch what follows)."""
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
            make = hard if recall >= RETELLS_HARD and ev["id"] not in (soften or set()) else soft
            why = (where or {}).get(ev["id"], "belongs elsewhere")
            out.append(make(stage, f"{what}_retells_event", f"{unit_id} describes {ev['id']} ('{ev['text'][:90]}'), which {why}: do not tell, show or hint at it here", [unit_id, ev["id"]],
                            [f"{what} text: {unit_text[:240]}", f"event {ev['id']}: {ev['text'][:200]}"]))  # both, so the critic can say whether the unit really tells it
    return out


def _where(chapters: list[dict]) -> tuple[dict, dict]:
    """event id -> the first chapter (index) that tells it, and that chapter's act."""
    first: dict[str, int] = {}
    for i, c in enumerate(chapters):
        for ev in c.get("events_covered") or []:
            first.setdefault(ev, i)
    return first, {i: c.get("act") for i, c in enumerate(chapters)}


def _classify(first: dict, acts: dict, chapters: list[dict], here_idx: int, here_act, ev_id: str) -> tuple[str, bool]:
    """(why this unit may not use the event, whether it is only the next chapter(s) of the same act)."""
    at = first.get(ev_id)
    if at is None:
        return "is reserved for a later act (no chapter tells it yet); a chapter with nothing new of its own continues a weight 3 event or adds a derived minor complication, it never borrows from another act", False
    if at < here_idx:
        return f"was already told in {chapters[at]['id']}", False
    if at > here_idx and here_act is not None and acts.get(at) == here_act:
        return f"is told in the later chapter {chapters[at]['id']}", True
    return f"is told in {chapters[at]['id']}" if at != here_idx else "is told here", False


def check_chapter_texts(chapters: list[dict], events: list[dict], stage: str = "chapters") -> list[Finding]:
    """Each chapter's summary must describe the events it lists. It must not retell an event already told, nor touch one reserved for a
    later act (hard). Touching an event of a following chapter in the same act is only soft: a chapter may lead into the next."""
    by_id = {e["id"]: e for e in events}
    first, acts = _where(chapters)
    out: list[Finding] = []
    for i, c in enumerate(chapters):
        text = " ".join(str(c.get(k, "")) for k in ("purpose", "summary"))  # not the title: its capitalised words would read as names
        mine = set(c.get("events_covered") or []) | set(c.get("events_continued") or [])
        others = [e for e in events if e["id"] not in mine and not e.get("carried_in")]
        where, soften = {}, set()
        for e in others:
            why, near = _classify(first, acts, chapters, i, c.get("act"), e["id"])
            where[e["id"]] = why
            if near:
                soften.add(e["id"])
        out += _event_text_checks(c["id"], text, list(c.get("events_covered") or []), by_id, others, stage, "chapter", where, soften)
    return out


def check_scene_texts(scenes: list[dict], chapters: list[dict], events: list[dict], stage: str = "scenes") -> list[Finding]:
    """Each scene's purpose and beats must describe the events it lists, and must not retell an event of an earlier chapter or one reserved
    for a later act (hard). Touching what the next chapters of the same act tell is only soft."""
    by_id = {e["id"]: e for e in events}
    first, acts = _where(chapters)
    index = {c["id"]: i for i, c in enumerate(chapters)}
    out: list[Finding] = []
    for s in scenes:
        ch = s.get("chapter") or s["id"].rsplit(".s", 1)[0]
        here = index.get(ch, -1)
        mine = (set(chapters[here].get("events_covered") or []) | set(chapters[here].get("events_continued") or [])) if here >= 0 else set()
        text = " ".join([str(s.get("purpose", ""))] + [str(b) for b in s.get("beats") or []])
        others = [e for e in events if e["id"] not in mine and not e.get("carried_in")]
        where, soften = {}, set()
        for e in others:
            why, near = _classify(first, acts, chapters, here, chapters[here].get("act") if here >= 0 else None, e["id"])
            where[e["id"]] = why
            if near:
                soften.add(e["id"])
        out += _event_text_checks(s["id"], text, list(s.get("events") or []), by_id, others, stage, "scene", where, soften)
    return out


def scene_count_plausibility(chapter: dict, scenes: list[dict], events: list[dict], stage: str = "scenes", max_scenes: int = 4) -> list[Finding]:
    """The number of scenes in a chapter must fit the weight of its events: about SCENE_WEIGHT each, within 0.2x..1.75x (padded or crammed)."""
    by_id = {e["id"]: e for e in events}
    weight = sum(int(by_id[x].get("weight", 1)) for x in list(chapter.get("events_covered") or []) + list(chapter.get("events_continued") or []) if x in by_id)
    n = len(scenes)
    if not weight or not n:
        return []
    per = weight / n
    lo = max(1, math.ceil(weight / (1.75 * SCENE_WEIGHT)))
    hi = min(max_scenes, max(lo, math.floor(weight / (0.2 * SCENE_WEIGHT))))
    if lo > max_scenes:
        return [hard(stage, "chapter_overloaded", f"{chapter['id']}: its events weigh {weight} in total, more than {max_scenes} scenes can carry (about {1.75 * SCENE_WEIGHT:.0f} each at most). "
                     "The chapter holds too much: move some of its events to a neighbouring chapter of the act", [chapter["id"]])]
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


def resolution_in_summary(acts: list[dict], events: list[dict], stage: str = "acts") -> list[Finding]:
    """Soft: the last act's own text (summary, purpose, turning point) should describe the events that make up the resolution.

    The ending is what the whole book builds toward; a summary of the final act that never mentions it reads as an act that stops short.
    """
    if not acts:
        return []
    final = acts[-1]
    by_id = {e["id"]: e for e in events}
    text = " ".join(str(final.get(k, "")) for k in ("summary", "purpose", "turning_point"))
    unit = _stems_wo_names(text)
    out = []
    for ev_id in final.get("events") or []:
        ev = by_id.get(ev_id)
        if not ev or not ev.get("ending"):
            continue
        need = _stems_wo_names(ev.get("text", ""))
        if len(need) < 3:
            continue
        recall = len(need & unit) / len(need)
        if recall < DESCRIBES_MIN:
            out.append(soft(stage, "act_summary_omits_resolution", f"{final['id']} is the last act, but its summary never describes the resolution event {ev_id} "
                            f"('{ev['text'][:90]}'): say how the book ends", [final["id"], ev_id]))
    return out


def heavy_chapters(chapters: list[dict], events: list[dict], weight_per_chapter: float = 2.0, stage: str = "chapters", factor: float = 3.0) -> list[Finding]:
    """Soft: a chapter whose events weigh much more than the usual chapter will not fit its scenes (at most four)."""
    by_id = {e["id"]: e for e in events}
    out = []
    for c in chapters:
        weight = sum(int(by_id[x].get("weight", 1)) for x in list(c.get("events_covered") or []) + list(c.get("events_continued") or []) if x in by_id)
        if weight > factor * weight_per_chapter:
            out.append(soft(stage, "heavy_chapter", f"{c['id']} carries events weighing {weight} (a usual chapter about {weight_per_chapter:g}): consider moving some to the next chapter", [c["id"]]))
    return out
