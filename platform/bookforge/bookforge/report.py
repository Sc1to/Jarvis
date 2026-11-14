"""The morning report: where to look after a run, so you read 5 scenes instead of 80.

Written to `books/<book>/reports/<date>.md` at the end of every run (and by `report --write`). Sections:
progress (with the model time and tokens used), needs you, unsure, suggestions for banned.txt, facts to
verify, and three before/after samples of revisions. Everything is read from files the pipeline already
keeps (state.json, each scene's review.json, change requests, the research sources, logs/calls.jsonl),
so the report costs no model calls and can be made at any time.
"""

import json
import math
import random
import re
from collections import Counter
from datetime import datetime, timezone

from . import changes, review_notes, scenefiles, stale
from .bible import store
from .bible.models import Scene
from .constants import CHECKPOINTS, LAYER_ORDER
from .errors import BookforgeError
from .project import Project
from .qc.mechanical import STOPWORDS, _banned_regex, load_banned
from .research.notes import stores_for, waiting_decisions
from .state import Item

SUGGEST_NGRAM = 4
SUGGEST_MIN_SCENES = 3
SUGGEST_MAX = 10
SAMPLES = 3
_WORD = re.compile(r"[\w'’-]+")


def _read_json(path) -> dict:
    raw = scenefiles.read(path)
    try:
        data = json.loads(raw) if raw else {}
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def call_totals(project: Project, since: str | None = None) -> dict:
    """Model calls, tokens and time from logs/calls.jsonl (only calls at or after `since`, an ISO timestamp)."""
    totals = {"calls": 0, "failed": 0, "prompt_tokens": 0, "completion_tokens": 0, "seconds": 0.0, "web_calls": 0}
    path = project.book_dir / "logs" / "calls.jsonl"
    if not path.exists():
        return totals
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if since and str(rec.get("ts", "")) < since:
            continue
        if rec.get("kind") != "llm":
            totals["web_calls"] += 1
            continue
        totals["calls"] += 1
        totals["failed"] += 0 if rec.get("ok", True) else 1
        usage = rec.get("usage") or {}
        totals["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
        totals["completion_tokens"] += int(usage.get("completion_tokens") or 0)
        totals["seconds"] += float(rec.get("duration_seconds") or 0)
    return totals


def _duration(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 3600}h {s % 3600 // 60}m" if s >= 3600 else f"{s // 60}m {s % 60}s"


def suggest_banned(texts: list[str], banned: list[str], names: set[str]) -> list[tuple[str, int]]:
    """Four-word phrases found in many scenes that are not banned yet: (phrase, number of scenes)."""
    if len(texts) < SUGGEST_MIN_SCENES:
        return []
    need = max(SUGGEST_MIN_SCENES, math.ceil(0.1 * len(texts)))
    seen: Counter = Counter()
    for text in texts:
        tokens = [t.lower() for t in _WORD.findall(text)]
        seen.update({tuple(tokens[i: i + SUGGEST_NGRAM]) for i in range(len(tokens) - SUGGEST_NGRAM + 1)})
    rules = [rx for rx in (_banned_regex(b) for b in banned) if rx]
    out = []
    for gram, n in seen.most_common():
        if n < need:
            break
        if sum(1 for t in gram if t not in STOPWORDS) < 2 or any(t in names for t in gram):
            continue
        phrase = " ".join(gram)
        if any(rx.search(phrase) for rx in rules):
            continue
        out.append((phrase, n))
    # a longer overlap of the same phrase adds nothing: keep a phrase only if its words are not mostly in a better one
    kept: list[tuple[str, int]] = []
    for phrase, n in out:
        if not any(len(set(phrase.split()) & set(k.split())) >= SUGGEST_NGRAM - 1 for k, _ in kept):
            kept.append((phrase, n))
        if len(kept) == SUGGEST_MAX:
            break
    return kept


def _scene_rows(project: Project, scenes: list[Scene]) -> list[tuple[Scene, Item, dict]]:
    return [(s, project.state.items.get(s.id, Item()), _read_json(scenefiles.review_path(project, s.id))) for s in scenes]


def _samples(rows, seed: str) -> list[dict]:
    pool = []
    for s, _, review in rows:
        passages = [p for rd in review.get("rounds") or [] for p in rd.get("revisions") or []]
        passages += [p for fx in review.get("stale_fixes") or [] for p in fx.get("passages") or []]
        pool += [{"scene": s.id, **p} for p in passages if p.get("mode") == "rewrite" and p.get("before") and p.get("after")]
    random.Random(seed).shuffle(pool)
    return pool[:SAMPLES]


def build_report(project: Project, since: str | None = None, today: str | None = None) -> str:
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    scenes = store.load_scenes(project) if store.scenes_path(project).exists() else []
    rows = _scene_rows(project, scenes)
    cfg = project.config
    out = [f"# Morning report: {project.book}, {today}", ""]

    # ── progress
    counts = Counter(item.status for _, item, _ in rows)
    n_pending = len(scenes) - sum(counts.values())
    accepted_words = 0
    for s, item, _ in rows:
        if item.status in ("accepted", "stale"):
            text = scenefiles.read(scenefiles.final_path(project, s.id))
            accepted_words += len(_WORD.findall(text)) if text else 0
    out += ["## Progress", ""]
    out += [f"- Layers: " + ", ".join(f"{n} {project.state.layers[n].status}" for n in LAYER_ORDER)]
    if scenes:
        parts = [f"{counts[k]} {k}" for k in ("accepted", "flagged", "stale", "drafted", "checked") if counts[k]]
        out.append(f"- Scenes: {len(scenes)} planned: " + ", ".join(parts + ([f"{n_pending} pending"] if n_pending else [])))
        out.append(f"- Words in accepted scenes: {accepted_words} (target {cfg.book.target_words})")
    t = call_totals(project, since)
    out.append(f"- {'This run' if since else 'So far'}: {t['calls']} model calls ({t['failed']} failed), {_duration(t['seconds'])} of model time, "
               f"{t['prompt_tokens'] + t['completion_tokens']} tokens ({t['prompt_tokens']} in, {t['completion_tokens']} out)"
               + ("" if t["prompt_tokens"] + t["completion_tokens"] else " (the server did not report usage)")
               + (f", {t['web_calls']} web calls" if t["web_calls"] else ""))
    out.append("")

    # ── needs you
    needs: list[str] = []
    for cp in CHECKPOINTS:
        if project.state.checkpoints[cp].status == "waiting":
            needs.append(f"The **{cp}** checkpoint is waiting: review, then `approve {cp}`.")
    for name in LAYER_ORDER:
        item = project.state.layers[name]
        if item.status == "flagged":
            needs.append(f"Layer **{name}** is flagged: {item.note or 'see the log'}.")
    for s, item, review in rows:
        if item.status == "flagged":
            reasons = review.get("blocking") or ([item.note] if item.note else [])
            needs.append(f"Scene **{s.id}** is flagged: " + "; ".join(reasons))
        elif item.status == "stale":
            needs.append(f"Scene **{s.id}** is stale ({item.note or 'something it was built from changed'}): `stale --fix`.")
    for cr in changes.list_requests(project):
        if cr.status == "pending":
            needs.append(f"Change request **{cr.id}** ({cr.proposed_by}, {cr.entity or cr.track}): plan '{cr.planned}', prose '{cr.observed}'; "
                         f"{len(cr.affects)} scene(s), {cr.scope}. `changes --approve {cr.id}` or `--reject {cr.id}`.")
    for n in waiting_decisions(project):
        needs.append(f"Decision **{n.id}** ({n.stance}): {n.question} Proposed: {(n.rule or 'no text yet').rstrip('. ')}. "
                     f"`needs --approve {n.id}` or `--reject {n.id}`.")
    try:
        needs += [f"{p.kind.capitalize()} **{p.id}** needs a look: {p.reason}. `stale --accept {p.id}` once it is fine." for p in stale._scan_plan(project)]
    except BookforgeError:
        pass
    for rec in review_notes.read(project):
        needs.append(f"Plan review, {rec['layer']} {rec['item']}: " + "; ".join(rec["problems"]))
    from .validators import store as findings_store
    for f in findings_store.load(project, "prose")["findings"]:
        if f["severity"] == "hard":
            needs.append(f"Prose check **{f['code']}**: {f['message']}" + (f" (e.g. \"{f['evidence'][0]}\")" if f["evidence"] else ""))
    out += ["## Needs you", ""] + ([f"- {n}" for n in needs] or ["- Nothing."]) + [""]

    # ── unsure
    unsure: list[str] = []
    for s, item, review in rows:
        for u in (review.get("continuity") or {}).get("unsure") or []:
            unsure.append(f"{s.id}: continuity, '{u['question']}' (answered {u['answer']}, confidence {u['confidence']})")
        scores = (review.get("critic") or {}).get("scores") or {}
        near = [f"{k} {v}" for k, v in scores.items() if v <= cfg.qc.critic_min_score]
        if near and item.status == "accepted":
            unsure.append(f"{s.id}: critic scores at the minimum ({', '.join(near)})")
        for g in (review.get("extraction") or {}).get("gaps") or []:
            unsure.append(f"{s.id}: the prose shows '{g['observed']}' where the plan says '{g['planned']}' ({g['track']})")
    soft_prose = [f for f in findings_store.load(project, "prose")["findings"] if f["severity"] == "soft"]
    if soft_prose:
        unsure.append(f"prose checks: {len(soft_prose)} soft finding(s) ("
                      + ", ".join(f"{c} x{n}" for c, n in sorted({(c, sum(1 for f in soft_prose if f['code'] == c)) for c in {f['code'] for f in soft_prose}})) + ") in validation/prose.json")
    out += ["## Unsure", ""] + ([f"- {u}" for u in unsure] or ["- Nothing."]) + [""]

    # ── suggestions
    constants = store.load_constants(project) if store.constants_path(project).exists() else None
    names = {t.lower() for e in (constants.entities if constants else []) for t in _WORD.findall(e.name)}
    texts = [t for s, item, _ in rows if item.status in ("accepted", "stale") and (t := scenefiles.read(scenefiles.final_path(project, s.id)))]
    banned = load_banned(scenefiles.read(project.root / cfg.qc.banned_phrases) or "")
    suggestions = suggest_banned(texts, banned, names)
    out += ["## Suggestions for banned.txt", "",
            *([f"- `{p}` (in {n} scenes)" for p, n in suggestions] or ["- No phrase stands out."]), ""]

    # ── facts to verify
    cited: dict[str, list[str]] = {}
    chapters = {c.id: c for c in store.load_chapters(project)} if store.chapters_path(project).exists() else {}
    for s in scenes:
        for fid in s.research + (chapters[s.chapter].research if s.chapter in chapters else []):
            cited.setdefault(fid, []).append(s.id)
    facts = [f for st in stores_for(project).values() for f in st.facts() if f.sensitive]
    out += ["## Facts to verify", ""]
    for f in facts:
        used = ", ".join(dict.fromkeys(cited.get(f.id, []))) or "not cited yet"
        out.append(f"- [{f.id}] {f.claim} ({f.url}; used in {used})")
    if not facts:
        out.append("- None marked sensitive.")
    out.append("")

    # ── samples
    out += ["## Revision samples", ""]
    samples = _samples(rows, today)
    for smp in samples:
        out += [f"**{smp['scene']}**", "", f"> Before: {smp['before']}", ">", f"> After: {smp['after']}", ""]
    if not samples:
        out += ["No passage was revised.", ""]
    return "\n".join(out).rstrip() + "\n"


def write_report(project: Project, since: str | None = None) -> str:
    """Write the report and return its path relative to the series. Later reports on the same day get a time suffix."""
    now = datetime.now(timezone.utc)
    text = build_report(project, since, now.strftime("%Y-%m-%d"))
    d = project.book_dir / "reports"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{now:%Y-%m-%d}.md"
    if path.exists():
        path = d / f"{now:%Y-%m-%d}-{now:%H%M%S}.md"
    path.write_text(text, encoding="utf-8")
    return str(path.relative_to(project.root))
