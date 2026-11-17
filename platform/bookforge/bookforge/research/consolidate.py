"""Merge the needs of one topic into one (a tap, undoable), and settle a contradiction between two rules.

A consolidation never deletes: each member keeps its record with `merged_into` set, the merged need lists `merged_from`, and a snapshot of
the needs file is kept (versions.keep). Undo clears `merged_into` on the members and retires the merged need.
"""
from __future__ import annotations

import logging

from .. import versions
from ..qc.support import ask_json
from . import topics
from .notes import MAX_RULE_CHARS_STORED, Need, stores_for

log = logging.getLogger("platform_bookforge.research")

STANCE_RANK = {"bend": 3, "invent": 2, "extrapolate": 1, "ground": 0}


def _scope_of(project, need_id: str) -> str:
    return next(scope for scope, st in stores_for(project).items() if any(n.id == need_id for n in st.needs()))


def preview(project) -> list[dict]:
    """The clusters of two or more live needs, as {topic, ids, questions}: what a consolidation would merge. No model call."""
    out = []
    for scope, store in stores_for(project).items():
        for group in topics.clusters(store.live_needs()):
            if len(group) >= 2:
                out.append({"scope": scope, "topic": topics.topic_key(topics.need_stems(group[0])), "ids": [n.id for n in group],
                            "questions": [n.question for n in group]})
    return out


def _check(data: dict) -> list[str]:
    problems = []
    if not str(data.get("rule", "")).strip():
        problems.append("'rule' must be one or two plain sentences")
    if not str(data.get("question", "")).strip():
        problems.append("'question' must be the topic as a short question")
    return problems


def consolidate(ctx) -> dict:
    """Merge every cluster of two or more needs of one topic into one need each. Returns {"merged": [{"id", "from"}], "before", "after"}."""
    project = ctx.project
    result = {"merged": [], "before": 0, "after": 0, "snapshot": None}
    stores = stores_for(project)
    result["before"] = sum(len(st.live_needs()) for st in stores.values())
    result["snapshot"] = versions.keep(project, [st.needs_path for st in stores.values()], "consolidate-needs")
    role = project.config.layers["chapters"].model
    for scope, store in stores.items():
        for group in topics.clusters(store.live_needs()):
            if len(group) < 2:
                continue
            block = "\n".join(f"- [{n.status}{', ' + n.decided_by if n.decided_by else ''}] {n.question}" + (f" Rule: {n.rule}" if n.rule else "") for n in group)
            try:
                data = ask_json(ctx, f"merge needs {group[0].id}", role, "need_merge", _check, max_tokens=500, members=block)
            except Exception as e:  # nothing merged for this topic: the members stay as they were
                log.info("needs %s not merged (%s)", group[0].id, e)
                continue
            decided = [n for n in group if n.status == "approved" and n.decided_by == "author"]
            stance = max((n.stance for n in group), key=lambda s: STANCE_RANK.get(s, 0))
            places = list(group[0].applies_to)
            for n in group[1:]:
                places = topics.widen_scope(places, n.applies_to)
            merged = store.add_need(
                layer=group[0].layer, question=" ".join(str(data["question"]).split())[:200], stance=stance, reason=f"merged from {len(group)} decisions on one topic",
                rule=" ".join(str(data["rule"]).split())[:MAX_RULE_CHARS_STORED], query=next((n.query for n in group if n.query), ""),
                context=next((n.context for n in group if n.context), ""), sensitive=any(n.sensitive for n in group),
                fact_ids=list(dict.fromkeys(i for n in group for i in n.fact_ids)), applies_to=places,
                status="approved" if decided else "proposed", decided_by="tool" if decided else "", topic=topics.topic_key(topics.need_stems(group[0])),
                merged_from=[n.id for n in group])
            for n in group:
                n.merged_into = merged.id
                store.save_need(n)
            result["merged"].append({"id": merged.id, "from": [n.id for n in group]})
        store.write_needs_md()
    result["after"] = sum(len(st.live_needs()) for st in stores.values())
    return result


def undo(project, merged_id: str) -> list[str]:
    """Take a consolidation back: the members stand again, the merged need is retired. Returns the ids restored."""
    scope = _scope_of(project, merged_id)
    store = stores_for(project)[scope]
    merged = next(n for n in store.needs() if n.id == merged_id)
    restored = []
    for n in store.needs():
        if n.merged_into == merged_id:
            n.merged_into = ""
            store.save_need(n)
            restored.append(n.id)
    merged.merged_into = "undone"
    store.save_need(merged)
    store.write_needs_md()
    return restored


def contradiction_items(project) -> list[dict]:
    """Each pair of rules on one topic that disagree about a quantity: {a, b, options}. Neither is canon until one is chosen."""
    items = []
    for store in stores_for(project).values():
        for a, b in topics.contradictions(store.live_needs()):
            items.append({"a": {"id": a.id, "rule": a.rule}, "b": {"id": b.id, "rule": b.rule},
                          "text": f"These two rules disagree: {a.id} says \"{a.rule}\"; {b.id} says \"{b.rule}\".",
                          "options": [{"id": "merge", "label": "Merge into one rule (recommended)", "recommended": True},
                                      {"id": "a", "label": f"Use {a.id}"}, {"id": "b", "label": f"Use {b.id}"}]})
    return items


def resolve_contradiction(ctx, a_id: str, b_id: str, choice: str) -> str:
    """Settle one disagreement: 'a' or 'b' keeps that rule and rejects the other; 'merge' consolidates the two into one. Returns the surviving need id."""
    from ..errors import BookforgeError
    project = ctx.project
    if choice not in ("a", "b", "merge"):
        raise BookforgeError("choice must be a, b or merge")
    scope = _scope_of(project, a_id)
    store = stores_for(project)[scope]
    by_id = {n.id: n for n in store.needs()}
    if a_id not in by_id or b_id not in by_id:
        raise BookforgeError("both needs must be in the same scope")
    a, b = by_id[a_id], by_id[b_id]
    if choice in ("a", "b"):
        keep, drop = (a, b) if choice == "a" else (b, a)
        keep.status, keep.decided_by = "approved", "author"
        drop.status, drop.decided_by = "rejected", "author"
        for n in (keep, drop):
            store.save_need(n)
        store.write_needs_md()
        return keep.id
    versions.keep(project, [store.needs_path], "merge-contradiction")
    block = "\n".join(f"- [{n.status}] {n.question} Rule: {n.rule}" for n in (a, b))
    data = ask_json(ctx, f"merge {a_id} {b_id}", project.config.layers["chapters"].model, "need_merge", _check, max_tokens=500, members=block)
    merged = store.add_need(layer=a.layer, question=" ".join(str(data["question"]).split())[:200], stance=max((a.stance, b.stance), key=lambda s: STANCE_RANK.get(s, 0)),
                            reason="merged from two rules that disagreed", rule=" ".join(str(data["rule"]).split())[:MAX_RULE_CHARS_STORED],
                            context=a.context or b.context, applies_to=[], status="approved", decided_by="author", topic=a.topic or b.topic, merged_from=[a.id, b.id])
    for n in (a, b):
        n.merged_into = merged.id
        store.save_need(n)
    store.write_needs_md()
    return merged.id


def settle_minor(project) -> list[str]:
    """The book's policy decides the minor ones: in `assist` or `auto` mode, for a book whose policy is invent or extrapolate, a proposed rule
    that decides nothing about what happens (resolve.size_of) is approved as the tool's decision (undone like any need: reject or edit it).
    A major one stays waiting for you. Returns the ids settled."""
    from .. import answers
    from ..resolve import size_of
    if answers.load(project)["mode"] == "shadow" or answers.policy_for(project)["world_facts"] not in ("invent", "extrapolate"):
        return []
    settled = []
    for store in stores_for(project).values():
        for n in store.live_needs():
            if n.status == "proposed" and n.rule and size_of(f"{n.question} {n.rule}", False) == "minor":
                n.status, n.decided_by = "approved", "tool"
                store.save_need(n)
                settled.append(n.id)
        if settled:
            store.write_needs_md()
    return settled
