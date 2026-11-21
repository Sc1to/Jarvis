"""Proposals for what stops a stage: what the tool would answer, and why (docs/BOOKFORGE.md, "The tool proposes the answers").

A proposal is stored beside the Inbox item (books/<book>/validation/proposals.json, keyed by the item's id) and shown with a "Use suggestion" button.
In `shadow` mode, which is the default, nothing is applied: the proposal is only a suggestion, and what you did with it is recorded so the tool earns trust.

Sentences of the synopsis that no event quotes (the commonest Inbox item) are resolved in three steps, cheapest and most checkable first:
1. an existing event already tells it by meaning -> widen that event's excerpt (no model);
2. it elaborates the event just before it, naming the same people or things -> attach it to that event (no model);
3. otherwise a model must name the change the sentence makes to the story and quote the words that say so; none -> description, needs no event;
   a change -> a new event is proposed (never applied without you).
"""

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from urllib.parse import urlparse

from . import answers as answers_mod
from .validators.ledger import _norm
from .validators.text import WORD, content_stems, sentences

log = logging.getLogger("platform_bookforge.resolve")

WIDEN_RECALL = 0.6  # share of a sentence's content words an event's text must carry for the event to be taken as telling it
WIDEN_MIN_SHARED = 3
ATTACH_MIN_SHARED = 1


@dataclass
class Proposal:
    outcome: str  # widen | attach | waive | new_event | options
    answer: str  # the text the answer box is filled with by "Use suggestion"
    rationale: str
    label: str  # tool housekeeping | proposal | from source | extrapolated | invented
    target: str = ""  # the event it concerns
    sources: list[dict] = field(default_factory=list)  # [{url, quote}] when it comes from research
    size: str = "n/a"  # minor | major | n/a
    confidence: str = "medium"
    decided_by: str = "tool"
    applied: bool = False
    mode: str = "shadow"
    quote: str = ""  # the synopsis sentence it concerns, in full (a world fact: the fact to establish)
    need: str = ""  # the need recorded when the tool answered a fact about the world itself


def path(project):
    return project.book_dir / "validation" / "proposals.json"


def load(project) -> dict[str, dict]:
    try:
        data = json.loads(path(project).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(project, proposals: dict[str, dict]) -> None:
    p = path(project)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(proposals, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def _flat(synopsis: str) -> list[tuple[int, str]]:
    """(paragraph number, sentence) for every sentence of the synopsis."""
    from .validators.ledger import paragraphs
    return [(n, s) for n, para in enumerate(paragraphs(synopsis)) for s in sentences(para)]


def locate(synopsis: str, fragment: str) -> int | None:
    """Index of the synopsis sentence a (possibly shortened) quotation starts, or None."""
    want = _norm(fragment)[:60]
    for i, (_, s) in enumerate(_flat(synopsis)):
        if _norm(s).startswith(want) or want in _norm(s):
            return i
    return None


def _stems(text: str) -> set[str]:
    return set(content_stems(text))


def _names(text: str) -> set[str]:
    return {w.lower() for w in WORD.findall(text) if w[0].isupper() and len(w) > 2} - {"the", "she", "his", "her", "they", "their", "this", "that", "upon", "when"}


def _events_text(events: list[dict]) -> str:
    return "\n".join(f"- {e['id']}: {e.get('text', '')}" for e in events) or "(none)"


def covered_by_meaning(sentence: str, events: list[dict]) -> dict | None:
    """The event whose text and excerpt already carry most of the sentence's words (best first), or None."""
    need = _stems(sentence)
    if len(need) < WIDEN_MIN_SHARED:
        return None
    best, score = None, 0.0
    for e in events:
        have = _stems(f"{e.get('text', '')} {e.get('excerpt', '')}")
        shared = need & have
        recall = len(shared) / len(need)
        if len(shared) >= WIDEN_MIN_SHARED and recall >= WIDEN_RECALL and recall > score:
            best, score = e, recall
    return best


def elaborates_previous(flat: list[tuple[int, str]], index: int, events: list[dict]) -> dict | None:
    """The event that quotes the sentence just before this one in the same paragraph, when this sentence names the same people or things."""
    if index == 0 or flat[index - 1][0] != flat[index][0]:
        return None
    before = flat[index - 1][1]
    nb = _norm(before)
    owner = next((e for e in events if e.get("excerpt") and (_norm(e["excerpt"]) in nb or nb in _norm(e["excerpt"]))), None)
    if owner is None:
        return None
    here = flat[index][1]
    shared = (_names(here) & _names(before)) | (_stems(here) & _stems(before))
    return owner if len(shared) >= ATTACH_MIN_SHARED else None


def check_model_answer(data: dict, sentence: str) -> tuple[str, str, str] | None:
    """(outcome, change, reason) from the model's reply when it holds up, else None. A change must be named and the words that say so must be in the sentence;
    commentary must name no change."""
    if not isinstance(data, dict) or data.get("outcome") not in ("change", "commentary"):
        return None
    reason = str(data.get("reason", "")).strip()
    change, words = str(data.get("change", "")).strip(), str(data.get("words", "")).strip()
    if data["outcome"] == "change":
        if not change or not words or _norm(words) not in _norm(sentence):
            return None
        return "change", change, reason
    if change or words:
        return None
    return "commentary", "", reason


def _with_quote(p: Proposal | None, sentence: str) -> Proposal | None:
    if p is not None:
        p.quote = sentence
    return p


def propose_coverage(project, synopsis: str, sentence_fragment: str, events: list[dict], ask=None) -> Proposal | None:
    """See `_propose_coverage`; the proposal also carries the full sentence."""
    p = _propose_coverage(project, synopsis, sentence_fragment, events, ask)
    index = locate(synopsis, sentence_fragment)
    return _with_quote(p, _flat(synopsis)[index][1]) if index is not None else p


def _propose_coverage(project, synopsis: str, sentence_fragment: str, events: list[dict], ask=None) -> Proposal | None:
    """The proposal for one uncovered sentence. `ask(prompt_slots) -> dict` is the model step (None when no model is at hand: only the first two steps run)."""
    flat = _flat(synopsis)
    index = locate(synopsis, sentence_fragment)
    if index is None:
        return None
    sentence = flat[index][1]
    hit = covered_by_meaning(sentence, events)
    if hit:
        return Proposal("widen", f"Widen the excerpt of {hit['id']} so it also quotes this sentence: it already tells it ({hit['text'][:80]}).",
                        f"{hit['id']} already says most of this in other words.", "tool housekeeping", target=hit["id"], confidence="high")
    owner = elaborates_previous(flat, index, events)
    if owner:
        return Proposal("attach", f"Attach this sentence to {owner['id']}: widen its excerpt to include it. It elaborates what {owner['id']} tells ({owner['text'][:80]}).",
                        "It follows the sentence that event quotes and names the same people or things.", "tool housekeeping", target=owner["id"], confidence="medium")
    if ask is None:
        return None
    near = [e for e in events if e.get("excerpt") and any(_norm(e["excerpt"]) in _norm(flat[j][1]) or _norm(flat[j][1]) in _norm(e["excerpt"]) for j in range(max(0, index - 3), min(len(flat), index + 4)))]
    data = ask(sentence=sentence, before=flat[index - 1][1] if index else "(nothing)", after=flat[index + 1][1] if index + 1 < len(flat) else "(nothing)", events=_events_text(near or events[:12]))
    answer = check_model_answer(data, sentence)
    if answer is None:
        return None
    outcome, change, reason = answer
    if outcome == "commentary":
        return Proposal("waive", f"No event needed: {reason or 'it only describes or comments'}. List it under `no_event_needed`.", reason or "It changes nothing in the story.",
                        "tool housekeeping", confidence="medium")
    return Proposal("new_event", f"Add an event: {change}", f"It changes the story: {change}" + (f" ({reason})" if reason else ""), "proposal", confidence="medium")


def propose_all(project, llm=None, web=None, research_fn=None) -> dict:
    """Proposals for every open coverage finding of the ledger stage that has none yet. Returns {item id: proposal} (also saved).
    Never raises: a missing synopsis, a failed model call or an odd finding only means no proposal for that item."""
    from . import inbox
    from .layers.ledger import load_attempt_events
    from .bible import store
    from .prompts import render
    from .qc.support import parse_json_object

    try:
        synopsis = project.resolve(f"books/{project.book}/synopsis.md").read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        return {}
    ledger = store.load_ledger(project)
    events = [e.model_dump() for e in ledger.events] if ledger and ledger.events else load_attempt_events(project)
    known = load(project)
    answered = answers_mod.load(project)
    mode = answered["mode"]

    def ask_template(template: str, **slots) -> dict:
        if llm is None:
            return {}
        try:
            text = llm.complete(project.config.layers["ledger"].model, [{"role": "system", "content": render("system", project.root, **inbox_values(project))},
                                                                         {"role": "user", "content": render(template, project.root, **slots)}], max_tokens=600)
        except Exception as e:  # a failed call is no proposal
            log.info("proposal: model call failed (%s)", e)
            return {}
        return parse_json_object(text) or {}

    def ask(**slots) -> dict:
        return ask_template("coverage_resolve", **slots)

    from .realism import realism_setting
    realism = realism_setting(project)
    policy = answers_mod.policy_for(project)
    if research_fn is None and web is not None:
        from .research.step import answer_question as research_fn

    for item in inbox.collect(project, include_done=False):
        if item["id"] in known or item["kind"] == "healed":
            continue
        if item["kind"] == "question":
            made = propose_question(project, item, realism, policy, ask_template if llm is not None else None, web, research_fn, llm)
            if made:
                known[item["id"]] = asdict(made)
            continue
        if item["kind"] != "finding" or item.get("code") != "sentence_not_covered":
            continue
        fragment = (item["quotes"] or [""])[0]
        proposal = propose_coverage(project, synopsis, fragment, events, ask if llm is not None else None)
        if proposal:
            known[item["id"]] = asdict(proposal)
    if mode in ("assist", "auto"):
        off = set(demoted(project))
        apply_housekeeping(project, known, answered, off)
        if mode == "auto":
            apply_world_facts(project, known, answered, off)
    save(project, known)
    return known


HOUSEKEEPING = ("widen", "attach", "waive")  # outcomes the tool may settle itself in assist mode: they change no event and add none


def apply_housekeeping(project, proposals: dict, answered: dict, off: set | None = None) -> int:
    """In assist mode: settle the housekeeping proposals (a sentence attached to the event it elaborates, description waived) and mark them applied.
    A new event, anything else the tool proposes, and every sentence you took back stay yours. Returns how many were applied."""
    n = 0
    for item_id, p in proposals.items():
        if p.get("applied") or p.get("outcome") not in HOUSEKEEPING or not p.get("quote") or answers_mod.is_undone(answered, p["quote"]) or p["outcome"] in (off or ()):
            continue
        if p["outcome"] == "waive":
            answers_mod.waive(project, p["quote"], p.get("rationale", ""))
        p["applied"], p["mode"] = True, "assist"
        _log(project, item_id, p, "applied")
        n += 1
    return n


RULE_LABELS = ("extrapolated", "invented", "invented: no source found")  # a rule of this world the tool may record; a source-backed answer stays a suggestion


def apply_world_facts(project, proposals: dict, answered: dict, off: set | None = None) -> int:
    """In auto mode: a minor fact about the world the tool proposed as a rule is recorded as a decision of the tool's (an approved need, not canon: it only warns)
    and the question is answered with it, marked as the tool's and undoable. A major answer, a story decision, a consistency problem and a source-backed answer are
    never applied here. Returns how many were applied."""
    from .bible import store
    from .research.notes import MAX_RULE_CHARS_STORED, stores_for
    ledger = store.load_ledger(project)
    if ledger is None:
        return 0
    n = 0
    for item_id, p in proposals.items():
        if p.get("applied") or p.get("outcome") != "world_fact" or p.get("size") != "minor" or p.get("label") not in RULE_LABELS or "world_fact" in (off or ()) \
                or answers_mod.is_undone(answered, p.get("quote", "")) or not item_id.startswith("question:"):
            continue
        q = next((x for x in ledger.questions if x.id == item_id.split(":", 1)[1] and x.status == "open"), None)
        if q is None:
            continue
        need = stores_for(project)["book"].add_need(layer="ledger", question=(p.get("quote") or q.question)[:200], stance="extrapolate" if p["label"] == "extrapolated" else "invent",
                                                    reason=f"decided by the tool ({p['label']})", rule=p["answer"][:MAX_RULE_CHARS_STORED], status="approved", decided_by="tool", canon=False, applies_to=[])
        q.status, q.answer, q.decided_by, q.applied = "answered", p["answer"], "tool", False
        p["applied"], p["mode"], p["need"] = True, "auto", need.id
        _log(project, item_id, p, "applied")
        n += 1
    if n:
        store.save_ledger(project, ledger)
    return n


def repair_coverage(raw_events: list, synopsis: str, answered: dict, off: set | None = None) -> list[str]:
    """In assist mode, at the ledger parse: every plot sentence no event quotes that an event already tells by meaning, or that elaborates the event
    before it, is attached to that event (`also`). Waived sentences and sentences you took back are left alone. Events are changed in place; returns what was done."""
    from .validators.ledger import _sentence_coverage, paragraphs
    plain = [e for e in raw_events if isinstance(e, dict) and e.get("id")]
    flat = _flat(synopsis)
    notes = []
    for f in _sentence_coverage(plain, paragraphs(synopsis), "ledger", answered["waived"]):
        index = locate(synopsis, f.evidence[0]) if f.evidence else None
        if index is None:
            continue
        sentence = flat[index][1]
        if answers_mod.is_undone(answered, sentence) or (answered["mode"] == "shadow" and not answers_mod.is_accepted(answered, sentence)):
            continue  # in shadow mode only what you accepted
        owner = None if "widen" in (off or ()) else covered_by_meaning(sentence, plain)
        if owner is None and "attach" not in (off or ()):
            owner = elaborates_previous(flat, index, plain)
        if owner is not None:
            owner.setdefault("also", []).append(sentence)
            notes.append(f"{owner['id']} also tells \"{sentence[:70]}...\" (attached by the tool, mode assist)")
    return notes


def accept(project, item_id: str) -> dict:
    """You accept the tool's housekeeping suggestion for an item (waive the sentence, or attach it to the event): it is done now (a waiver) or at the next
    ledger run (an attachment), in any mode. Counted as a suggestion you accepted. Anything else (a new event, a fact about the world) is answered in your words."""
    from .errors import BookforgeError
    proposals = load(project)
    p = proposals.get(item_id)
    if not p or p.get("outcome") not in HOUSEKEEPING or not p.get("quote"):
        raise BookforgeError("that suggestion cannot be accepted as it is: answer it in your own words")
    if p.get("outcome") == "waive":
        answers_mod.waive(project, p["quote"], p.get("rationale", ""), decided_by="you")
    else:
        answers_mod.accept_sentence(project, p["quote"])
    p["applied"], p["decided_by"], p["mode"] = True, "you", "accepted"
    _log(project, item_id, p, "accepted")
    save(project, proposals)
    return p


def undo(project, item_id: str) -> None:
    """Take back a decision the tool made: the sentence is no longer waived or attached, and the tool leaves it alone from now on."""
    proposals = load(project)
    p = proposals.get(item_id)
    if not p or not p.get("applied"):
        from .errors import BookforgeError
        raise BookforgeError("the tool has not decided that item")
    answers_mod.take_back(project, p.get("quote", ""))
    if p.get("outcome") == "world_fact" and item_id.startswith("question:"):  # the rule is rejected and the question is yours again
        from .bible import store
        from .research.notes import stores_for
        book_store = stores_for(project)["book"]
        for need in book_store.needs():
            if need.id == p.get("need"):
                need.status, need.decided_by = "rejected", "author"
                book_store.save_need(need)
        ledger = store.load_ledger(project)
        q = next((x for x in (ledger.questions if ledger else []) if x.id == item_id.split(":", 1)[1] and x.decided_by == "tool"), None)
        if q is not None:
            q.status, q.answer, q.decided_by = "open", "", ""
            store.save_ledger(project, ledger)
        p["need"] = ""
    p["applied"] = False
    _log(project, item_id, p, "undone")
    save(project, proposals)


# ── questions: story decisions stay yours, facts about the world are answered by the book's policy ──

CONSISTENCY_TYPES = ("contradiction", "condition_order", "cast_conflict", "unknown_name")  # which version is true is the author's call
STORY_TYPES = ("thin", "unpaid_setup")
_MAJOR_MARKERS = re.compile(r"\b(1[0-9]{3}|20[0-9]{2})\b|\b(dies|died|killed|executed|murder\w*|assassinat\w*|betray\w*|turning point|decides to|will decide|a new character|named [A-Z]|called [A-Z]|founded|invaded|war breaks)\b")


def size_of(text: str, changes_what_happens: bool) -> str:
    """minor or major. An invented answer is major when it decides what happens: a death, a date, a betrayal, a new character or a turning point,
    or when the model itself says it changes what happens. Anything uncertain is treated as major."""
    return "major" if changes_what_happens or _MAJOR_MARKERS.search(text) else "minor"


def classify_gap(item: dict, realism: str, ask) -> dict:
    """{"kind": consistency | story_decision | world_fact, "fact": ...}. Known kinds of finding are classified without a model; the rest by a model that
    must state the fact to establish, else it is a story decision."""
    if item["type"] in CONSISTENCY_TYPES:
        return {"kind": "consistency", "fact": ""}
    if item["type"] in STORY_TYPES or ask is None:
        return {"kind": "story_decision", "fact": ""}
    data = ask("gap_classify", question=item["title"], why=item.get("why", ""), type=item["type"], realism=realism or "(none stated)")
    fact = str(data.get("fact", "")).strip() if isinstance(data, dict) else ""
    if isinstance(data, dict) and data.get("kind") == "world_fact" and fact:
        return {"kind": "world_fact", "fact": fact}
    return {"kind": "story_decision", "fact": ""}


def approved_rules(project) -> str:
    """The rules of this world you or the tool already approved (needs with a rule), so a new one never contradicts them."""
    from .research.notes import stores_for
    rules = []
    try:
        for store in stores_for(project).values():
            rules += [f"- {n.rule}" for n in store.needs() if n.status == "approved" and n.rule]
    except Exception:  # no research folder yet
        pass
    return "\n".join(rules) or "(none yet)"


def propose_world_fact(project, fact: str, realism: str, policy: dict, ask, web, research_fn, document: str = "", llm=None) -> Proposal:
    """The proposal for a fact about the world, by the book's policy: research first for `research` (a source quote or nothing), else a minor rule or
    assumption of this world. A major invention is never proposed as an answer: it decides what happens, which is yours."""
    from .layers.runner import StepContext
    attempt_reason = ""
    if policy["world_facts"] == "research" and web is not None and research_fn is not None:
        from .research.step import Question
        try:
            attempt = research_fn(StepContext(project=project, layer="ledger", llm=llm), web, Question(question=fact, query=fact, sensitive=True, context=realism), document, set())
        except Exception as e:  # research never takes the Inbox down
            attempt, attempt_reason = None, f"the search failed ({e})"
        if attempt is not None and attempt.facts:
            sources = [{"url": h.url, "quote": f.get("quote", "")} for h, f in attempt.facts[:3]]
            best = attempt.facts[0][1]
            return Proposal("world_fact", f"From sources: {best.get('claim', '')}", "Found in " + ", ".join(sorted({urlparse(h.url).hostname or h.url for h, _ in attempt.facts[:3]})) + ". Every claim keeps the exact words of its page.",
                            "from source", sources=sources, size="n/a", confidence="high" if len({s['url'] for s in sources}) > 1 else "medium")
        attempt_reason = attempt_reason or (attempt.reason if attempt is not None else "")
    if ask is None:
        return Proposal("options", "", f"No source found ({attempt_reason or 'no research was possible'}) and no model to propose a rule: this is yours to decide.", "no source found", size="n/a", confidence="low")
    data = ask("world_fact_invent", fact=fact, realism=realism or "(none stated)", rules=approved_rules(project),
               policy={"research": "look it up first; this is the fallback because no source was found: invent only a minor detail", "extrapolate": "ground what is real and extend it with an invented but plausible rule",
                       "invent": "invent a consistent rule"}[policy["world_facts"]])
    rule = str(data.get("rule", "")).strip() if isinstance(data, dict) else ""
    if not rule:
        return Proposal("options", "", "No usable answer was found for this fact: it is yours to decide.", "no source found" if policy["world_facts"] == "research" else "proposal", confidence="low")
    size = size_of(rule, bool(data.get("changes_what_happens")))
    if size == "major":
        return Proposal("options", "", f"Answering this decides what happens in the story, so it stays yours. A possible answer: {rule}", "proposal", size="major", confidence="low")
    basis = str(data.get("basis", "")).strip()
    label = "invented: no source found" if policy["world_facts"] == "research" else ("extrapolated" if policy["world_facts"] == "extrapolate" and basis else "invented")
    return Proposal("world_fact", rule, (f"Basis: {basis}. " if basis else "") + str(data.get("reason", "")).strip(), label, size="minor", confidence="medium")


def propose_question(project, item: dict, realism: str, policy: dict, ask, web, research_fn, llm=None) -> Proposal | None:
    """The proposal for a question item: a fact about the world gets one by the policy; a story decision or a consistency problem gets none (its suggested
    options are the proposal, and it is never settled by the tool)."""
    kind = classify_gap(item, realism, ask)
    if kind["kind"] != "world_fact":
        return None
    p = propose_world_fact(project, kind["fact"], realism, policy, ask, web, research_fn, llm=llm)
    p.quote = kind["fact"]
    return p


def inbox_values(project) -> dict:
    from .layers.document import prompt_values
    return prompt_values(project)


def record_decision(project, item_id: str, action: str, text: str = "") -> None:
    """What you did with an item that had a proposal: accepted it as it was, edited it, or went another way (answered differently or dismissed).
    One line in validation/decisions.jsonl; the rates per outcome say how far the tool can be trusted."""
    proposal = load(project).get(item_id)
    if not proposal:
        return
    if action == "answer":
        verdict = "accepted" if " ".join(text.split()) == " ".join(proposal.get("answer", "").split()) else "edited"
    else:
        verdict = "overridden"
    _log(project, item_id, proposal, verdict)


def log_outcome(project, item_id: str, outcome: str, verdict: str, label: str = "tool decision", mode: str | None = None) -> None:
    """One line for a decision that is not an Inbox proposal (the intake's cast entries and developments): applied | accepted | overridden | undone.
    The same file feeds `decision_stats`, the demotion rule and the morning report."""
    _log(project, item_id, {"outcome": outcome, "label": label, "mode": mode or answers_mod.load(project)["mode"]}, verdict)


def _log(project, item_id: str, proposal: dict, verdict: str) -> None:
    from datetime import datetime, timezone
    p = path(project).with_name("decisions.jsonl")
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "item": item_id, "outcome": proposal.get("outcome"), "label": proposal.get("label"),
                            "mode": proposal.get("mode", "shadow"), "verdict": verdict}, ensure_ascii=False) + "\n")


def _decisions(project) -> list[dict]:
    try:
        lines = path(project).with_name("decisions.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _rate(row: dict) -> float | None:
    """Of the decisions made about an outcome (you accepted, edited or overrode a suggestion, or the tool applied it), the share you did not agree with
    (edited, overrode, or undid). An application you never undid counts as agreement."""
    total = row["accepted"] + row["edited"] + row["overridden"] + row["applied"]
    return round(min(1.0, (row["edited"] + row["overridden"] + row["undone"]) / total), 2) if total else None


def decision_stats(project) -> dict[str, dict]:
    """Per outcome: how often the tool's proposal was accepted, edited, overridden, applied by the tool and undone by you."""
    out: dict[str, dict] = {}
    for rec in _decisions(project):
        row = out.setdefault(rec.get("outcome", "?"), {"proposed": 0, "accepted": 0, "edited": 0, "overridden": 0, "applied": 0, "undone": 0})
        verdict = rec.get("verdict", "overridden")
        row[verdict] = row.get(verdict, 0) + 1
        if verdict in ("accepted", "edited", "overridden"):
            row["proposed"] += 1
    for row in out.values():
        row["override_rate"] = _rate(row)
    return out


DEMOTE_WINDOW = 10  # the last decisions about an outcome that count
DEMOTE_MIN = 5  # fewer than this and there is nothing to judge yet
DEMOTE_RATE = 0.4  # more of them than this disagreed with: the tool stops deciding that outcome


def demoted(project) -> dict[str, dict]:
    """Outcomes the tool has stopped deciding on its own because you keep overriding it: {outcome: {rate, of, since}}. Judged over the last DEMOTE_WINDOW
    decisions since you last re-enabled the outcome. They are suggestions again until you switch them back on."""
    since = answers_mod.load(project)["reenabled"]
    by: dict[str, list[dict]] = {}
    for rec in _decisions(project):
        if rec.get("outcome") and rec.get("at", "") > since.get(rec["outcome"], ""):
            by.setdefault(rec["outcome"], []).append(rec)
    out = {}
    for outcome, recs in by.items():
        recent = [r for r in recs if r.get("verdict") in ("accepted", "edited", "overridden", "applied", "undone")][-DEMOTE_WINDOW:]
        row = {"accepted": 0, "edited": 0, "overridden": 0, "applied": 0, "undone": 0}
        for r in recent:
            row[r["verdict"]] += 1
        rate = _rate(row)
        if rate is not None and len(recent) >= DEMOTE_MIN and rate > DEMOTE_RATE:
            out[outcome] = {"rate": rate, "of": len(recent), "since": since.get(outcome, "")}
    return out
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        row = out.setdefault(rec.get("outcome", "?"), {"proposed": 0, "accepted": 0, "edited": 0, "overridden": 0, "applied": 0, "undone": 0})
        verdict = rec.get("verdict", "overridden")
        row[verdict] = row.get(verdict, 0) + 1
        if verdict not in ("applied",):  # a decision you made about a proposal; an application is the tool acting, an undo is you taking it back
            row["proposed"] += 1 if verdict != "undone" else 0
    for row in out.values():
        judged = row["accepted"] + row["edited"] + row["overridden"] + row["undone"]
        row["override_rate"] = round((row["edited"] + row["overridden"] + row["undone"]) / judged, 2) if judged else None
    return out
