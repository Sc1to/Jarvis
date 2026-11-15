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
    quote: str = ""  # the synopsis sentence it concerns, in full


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


def propose_all(project, llm=None) -> dict:
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

    def ask(**slots) -> dict:
        if llm is None:
            return {}
        try:
            text = llm.complete(project.config.layers["ledger"].model, [{"role": "system", "content": render("system", project.root, **inbox_values(project))},
                                                                         {"role": "user", "content": render("coverage_resolve", project.root, **slots)}], max_tokens=500)
        except Exception as e:  # a failed call is no proposal
            log.info("coverage proposal: model call failed (%s)", e)
            return {}
        return parse_json_object(text) or {}

    for item in inbox.collect(project, include_done=False):
        if item["kind"] != "finding" or item.get("code") != "sentence_not_covered" or item["id"] in known:
            continue
        fragment = (item["quotes"] or [""])[0]
        proposal = propose_coverage(project, synopsis, fragment, events, ask if llm is not None else None)
        if proposal:
            known[item["id"]] = asdict(proposal)
    if mode == "assist":
        apply_housekeeping(project, known, answered)
    save(project, known)
    return known


HOUSEKEEPING = ("widen", "attach", "waive")  # outcomes the tool may settle itself in assist mode: they change no event and add none


def apply_housekeeping(project, proposals: dict, answered: dict) -> int:
    """In assist mode: settle the housekeeping proposals (a sentence attached to the event it elaborates, description waived) and mark them applied.
    A new event, anything else the tool proposes, and every sentence you took back stay yours. Returns how many were applied."""
    n = 0
    for item_id, p in proposals.items():
        if p.get("applied") or p.get("outcome") not in HOUSEKEEPING or not p.get("quote") or answers_mod.is_undone(answered, p["quote"]):
            continue
        if p["outcome"] == "waive":
            answers_mod.waive(project, p["quote"], p.get("rationale", ""))
        p["applied"], p["mode"] = True, "assist"
        _log(project, item_id, p, "applied")
        n += 1
    return n


def repair_coverage(raw_events: list, synopsis: str, answered: dict) -> list[str]:
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
        if answers_mod.is_undone(answered, sentence):
            continue
        owner = covered_by_meaning(sentence, plain) or elaborates_previous(flat, index, plain)
        if owner is not None:
            owner.setdefault("also", []).append(sentence)
            notes.append(f"{owner['id']} also tells \"{sentence[:70]}...\" (attached by the tool, mode assist)")
    return notes


def undo(project, item_id: str) -> None:
    """Take back a decision the tool made: the sentence is no longer waived or attached, and the tool leaves it alone from now on."""
    proposals = load(project)
    p = proposals.get(item_id)
    if not p or not p.get("applied"):
        from .errors import BookforgeError
        raise BookforgeError("the tool has not decided that item")
    answers_mod.take_back(project, p.get("quote", ""))
    p["applied"] = False
    _log(project, item_id, p, "undone")
    save(project, proposals)


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


def _log(project, item_id: str, proposal: dict, verdict: str) -> None:
    from datetime import datetime, timezone
    p = path(project).with_name("decisions.jsonl")
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "item": item_id, "outcome": proposal.get("outcome"), "label": proposal.get("label"),
                            "mode": proposal.get("mode", "shadow"), "verdict": verdict}, ensure_ascii=False) + "\n")


def decision_stats(project) -> dict[str, dict]:
    """Per outcome: how often the tool's proposal was accepted, edited or overridden."""
    out: dict[str, dict] = {}
    try:
        lines = path(project).with_name("decisions.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
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
