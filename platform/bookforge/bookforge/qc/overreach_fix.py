"""A chapter whose own wording is wrong in a way one narrow call can fix is corrected in that wording, once, instead of being sent back to you.

Two cases: a chapter that reports the outcome of an event a later chapter tells (`fix`), and a chapter whose purpose and summary retell an event an earlier
chapter already told (`fix_retells`, below).

The first case:

The whole-book check finds a chapter whose summary or end_state says an event's outcome is already done (a chapter about deciding to do something
that ends with it done), and a model has confirmed it (qc/repeat_confirm.py). Planning the whole act again tends to repeat the slip, and the fix is
small: the chapter's own summary and end_state are rewritten, nothing else. The rewrite is kept only if the check no longer finds the overreach in
that chapter. A chapter that cannot be fixed this way stays a finding.
"""

import logging

from ..ask import word_count
from ..validators import HARD
from ..validators import state_claims
from .support import ask_json

log = logging.getLogger("platform_bookforge.qc")
MAX_FIXES = 8


def _check(original: tuple[str, str]):
    def check(data: dict) -> list[str]:
        s, e = data.get("summary"), data.get("end_state")
        if not isinstance(s, str) or not isinstance(e, str) or not s.strip() or not e.strip():
            return ['the reply must be {"summary": "...", "end_state": "..."}, both non-empty']
        out = []
        for name, new, old in (("summary", s, original[0]), ("end_state", e, original[1])):
            n, n_old = word_count(new), max(1, word_count(old))
            if n < 0.4 * n_old or n > 2.0 * n_old + 10:
                out.append(f"the {name} has {n} words; keep it close to the original {n_old}")
        return out
    return check


def fix(ctx, chapters: list, events: list[dict], findings: list) -> list[str]:
    """Rewrite the summary and end_state of each chapter a confirmed hard end_state_overreach points to. Returns one note per chapter fixed."""
    project = ctx.project
    if ctx.llm is None or not project.config.qc.fix_overreach:
        return []
    by_id = {c.id: c for c in chapters}
    by_event = {e["id"]: e for e in events}
    notes: list[str] = []
    done: set[str] = set()
    for f in findings[:MAX_FIXES]:
        if f.severity != HARD or f.accepted or f.code != "end_state_overreach" or len(f.items) < 2:
            continue
        cid, ev_id = f.items[0], f.items[1]
        ch, ev = by_id.get(cid), by_event.get(ev_id)
        if ch is None or ev is None or cid in done:
            continue
        old = (ch.summary, ch.end_state)
        claim = next((t for t in f.evidence if t.startswith("chapter:")), "")[len("chapter:"):].strip()
        try:
            data = ask_json(ctx, f"fix overreach {cid}", project.config.layers["chapters"].model, "overreach_fix", _check(old), max_tokens=900,
                            title=ch.title, summary=ch.summary, end_state=ch.end_state, event=f"{ev_id}: {ev['text']}", quote=claim)
        except Exception as e:  # no rewrite is no change: the finding stays
            log.info("%s: overreach not fixed (%s)", cid, e)
            continue
        ch.summary, ch.end_state = data["summary"].strip(), data["end_state"].strip()
        still = [x for x in state_claims.end_state_overreach([c.model_dump() for c in chapters], events) if x.items[:2] == [cid, ev_id]]
        if still:
            ch.summary, ch.end_state = old  # the rewrite did not take the claim out: the saved wording stands
            log.info("%s: overreach not fixed (the check still finds it)", cid)
            continue
        done.add(cid)
        notes.append(f"{cid}: its summary and end_state reported the outcome of {ev_id}, which a later chapter tells; the wording was rewritten and the check passes")
    return notes


def _check_retell(original: tuple[str, str]):
    def check(data: dict) -> list[str]:
        p, s = data.get("purpose"), data.get("summary")
        if not isinstance(p, str) or not isinstance(s, str) or not p.strip() or not s.strip():
            return ['the reply must be {"purpose": "...", "summary": "..."}, both non-empty']
        out = []
        for name, new, old in (("purpose", p, original[0]), ("summary", s, original[1])):
            n, n_old = word_count(new), max(1, word_count(old))
            if n < 0.4 * n_old or n > 2.0 * n_old + 10:
                out.append(f"the {name} has {n} words; keep it close to the original {n_old}")
        return out
    return check


RETOLD_CODES = ("chapter_retells_event", "event_repeated", "chapter_replans_chapter")


def fix_retells(ctx, chapters: list, events: list[dict], findings: list) -> list[str]:
    """Rewrite the purpose and summary of a chapter that retells what an earlier chapter already tells, so it describes only its own events. Three
    findings point to this: a chapter text that describes an event told earlier (chapter_retells_event), and two chapters that plan the same event
    (event_repeated, chapter_replans_chapter), where the LATER chapter is rewritten. Kept only if the check then no longer finds it. One note per chapter."""
    from ..validators import ledger as ledger_checks, repeats

    project = ctx.project
    if ctx.llm is None or not project.config.qc.fix_retells:
        return []
    by_id = {c.id: c for c in chapters}
    by_event = {e["id"]: e for e in events}
    notes: list[str] = []
    done: set[str] = set()

    def still_found(f, cid: str, other: str) -> bool:
        plain = [c.model_dump() for c in chapters]
        if f.code == "chapter_retells_event":
            return any(x.code == "chapter_retells_event" and x.severity == HARD and x.items[:2] == [cid, other] for x in ledger_checks.check_chapter_texts(plain, events))
        return any(x.severity == HARD and x.code in ("event_repeated", "chapter_replans_chapter") and cid in x.items and other in x.items
                   for x in repeats.repeated_events(plain, [], ledger_events=events))

    for f in findings[:MAX_FIXES]:
        if f.severity != HARD or f.accepted or f.code not in RETOLD_CODES or len(f.items) < 2:
            continue
        if f.code == "chapter_retells_event":
            cid, ev_id = f.items[0], f.items[1]
            ch, ev = by_id.get(cid), by_event.get(ev_id)
            if ch is None or ev is None:
                continue
            told_in = next((c.id for c in chapters if ev_id in c.events_covered and c.id != cid), "an earlier chapter")
            jobs = [(ch, f"{ev_id}: {ev['text']}", told_in, ev_id)]
        else:
            ids = [x for x in f.items if x in by_id]
            if len(ids) < 2:
                continue
            ids.sort(key=lambda x: chapters.index(by_id[x]))
            first = by_id[ids[0]]
            jobs = [(by_id[x], f"{first.title}: {first.summary}", first.id, first.id) for x in ids[1:]]
        for ch, forbidden, told_in, other in jobs:
            if ch.id in done:
                continue
            own = [by_event[x] for x in list(ch.events_covered) + list(ch.events_continued) if x in by_event]
            if not own:
                continue  # a chapter with no events of its own cannot be rewritten into one: that takes judgement
            old = (ch.purpose, ch.summary)
            try:
                data = ask_json(ctx, f"fix retold {ch.id}", project.config.layers["chapters"].model, "retell_fix", _check_retell(old), max_tokens=900,
                                title=ch.title, purpose=ch.purpose, summary=ch.summary, own_events="\n".join(f"- {e['id']}: {e['text']}" for e in own),
                                forbidden=forbidden, told_in=told_in)
            except Exception as e:  # no rewrite is no change: the finding stays
                log.info("%s: retold text not fixed (%s)", ch.id, e)
                continue
            ch.purpose, ch.summary = data["purpose"].strip(), data["summary"].strip()
            if still_found(f, ch.id, other):
                ch.purpose, ch.summary = old  # the rewrite still retells it: the saved wording stands
                log.info("%s: retold text not fixed (the check still finds it)", ch.id)
                continue
            done.add(ch.id)
            what = f"{other}, which {told_in} already tells" if f.code == "chapter_retells_event" else f"what {told_in} already tells"
            notes.append(f"{ch.id}: its purpose and summary retold {what}; the wording was rewritten and the check passes")
    return notes


def _check_scene(original: tuple[str, list[str]]):
    def check(data: dict) -> list[str]:
        p, b = data.get("purpose"), data.get("beats")
        if not isinstance(p, str) or not p.strip() or not isinstance(b, list) or not b or not all(isinstance(x, str) and x.strip() for x in b):
            return ['the reply must be {"purpose": "...", "beats": ["...", ...]}, with at least one beat']
        out = []
        n, n_old = word_count(p + " " + " ".join(b)), max(1, word_count(original[0] + " " + " ".join(original[1])))
        if n < 0.4 * n_old or n > 2.0 * n_old + 10:
            out.append(f"the purpose and beats have {n} words in all; keep them close to the original {n_old}")
        if len(b) > 10:
            out.append("at most 10 beats")
        return out
    return check


SCENE_RETOLD_CODES = ("scene_retells_event", "scene_repeats_scene", "event_repeated")


def _scene_still_found(f, scenes: list, chapters: list, events: list[dict], sid: str, other: str) -> bool:
    from ..validators import ledger as ledger_checks, repeats

    plain = [s.model_dump() for s in scenes]
    chs = [c.model_dump() for c in chapters]
    if f.code == "scene_retells_event":
        return any(x.code == "scene_retells_event" and x.severity == HARD and x.items[:2] == [sid, other] for x in ledger_checks.check_scene_texts(plain, chs, events))
    if f.code == "event_repeated":
        mine = next((s.chapter for s in scenes if s.id == sid), "")
        return any(x.severity == HARD and x.code == "event_repeated" and mine in x.items and other in x.items for x in repeats.repeated_events(chs, plain, ledger_events=events, stage="scenes"))
    return any(x.severity == HARD and x.code == "scene_repeats_scene" and sid in x.items and other in x.items for x in repeats.scene_repeats_in_chapters(plain))


def _rewrite_scene(ctx, project, sc, chapters: list, events: list[dict], f, forbidden: str, told_in: str, other: str, by_event: dict, notes: list[str], scenes: list) -> bool:
    """One narrow rewrite of a scene's purpose and beats; kept only if the check no longer finds the finding. True when it was kept."""
    own = [by_event[x] for x in sc.events if x in by_event]
    if not own and f.code == "scene_retells_event":
        return False  # a scene that shows no event of its own cannot be rewritten into one: that takes judgement
    old = (sc.purpose, list(sc.beats))
    try:
        data = ask_json(ctx, f"fix retold {sc.id}", project.config.layers["scenes"].model, "retell_fix_scene", _check_scene(old), max_tokens=1200,
                        purpose=sc.purpose, beats="\n".join(f"- {b}" for b in sc.beats), own_events="\n".join(f"- {e['id']}: {e['text']}" for e in own) or "none: it goes on with what the scene before it shows",
                        forbidden=forbidden, told_in=told_in)
    except Exception as e:  # no rewrite is no change: the finding stays
        log.info("%s: retold scene text not fixed (%s)", sc.id, e)
        return False
    sc.purpose, sc.beats = data["purpose"].strip(), [b.strip() for b in data["beats"]]
    if _scene_still_found(f, scenes, chapters, events, sc.id, other):
        sc.purpose, sc.beats = old  # the rewrite still retells it: the saved wording stands
        log.info("%s: retold scene text not fixed (the check still finds it)", sc.id)
        return False
    if f.code == "scene_retells_event":
        what = f"{other}, which {told_in} already tells"
    else:
        what = f"what {told_in} already shows"
    notes.append(f"{sc.id}: its purpose and beats retold {what}; the wording was rewritten and the check passes")
    return True


def fix_scene_retells(ctx, scenes: list, chapters: list, events: list[dict], findings: list) -> list[str]:
    """The scene-level twin of `fix_retells`: a scene whose purpose and beats retell an event of another chapter (`scene_retells_event`), or what an
    earlier scene of the same chapter already shows (`scene_repeats_scene`, the LATER scene is rewritten), has them rewritten in one narrow call to
    describe only its own events. Kept only if the check then no longer finds it."""
    project = ctx.project
    if ctx.llm is None or not project.config.qc.fix_retells:
        return []
    by_id = {s.id: s for s in scenes}
    by_event = {e["id"]: e for e in events}
    notes: list[str] = []
    done: set[str] = set()

    for f in findings[:MAX_FIXES]:
        if f.severity != HARD or f.accepted or f.code not in SCENE_RETOLD_CODES or len(f.items) < 2:
            continue
        if f.code == "event_repeated":  # raised by the scene-level check: the items are chapters; the scenes of the later ones whose beats carry the passage are rewritten
            if f.stage != "scenes" or len(f.items) < 2:
                continue
            chapter_ids = [c.id for c in chapters if c.id in f.items]
            if len(chapter_ids) < 2:
                continue
            first_ch = chapter_ids[0]
            first_text = " ".join(f"{x.purpose} " + " ".join(x.beats) for x in scenes if x.chapter == first_ch)
            passages = [t for t in f.evidence if t.strip()]
            jobs = []
            for cid in chapter_ids[1:]:
                carrier = next((x for x in scenes if x.chapter == cid and any(p[:40] in (" ".join(x.beats) + " " + x.purpose) for p in passages)), None) \
                    or next((x for x in scenes if x.chapter == cid), None)
                if carrier is not None:
                    jobs.append((carrier, first_text[:600], first_ch, first_ch))
            for sc, forbidden, told_in, other in jobs:
                if sc.id in done:
                    continue
                if _rewrite_scene(ctx, project, sc, chapters, events, f, forbidden, told_in, other, by_event, notes, scenes):
                    done.add(sc.id)
            continue
        if f.code == "scene_retells_event":
            sid, ev_id = f.items[0], f.items[1]
            sc, ev = by_id.get(sid), by_event.get(ev_id)
            if sc is None or ev is None:
                continue
            told_in = next((c.id for c in chapters if ev_id in c.events_covered), "another chapter")
            jobs = [(sc, f"{ev_id}: {ev['text']}", told_in, ev_id)]
        else:
            ids = [x for x in f.items if x in by_id]
            if len(ids) < 2:
                continue
            ids.sort(key=lambda x: scenes.index(by_id[x]))
            first = by_id[ids[0]]
            jobs = [(by_id[x], f"{first.purpose} " + " ".join(first.beats), first.id, first.id) for x in ids[1:]]
        for sc, forbidden, told_in, other in jobs:
            if sc.id in done:
                continue
            if _rewrite_scene(ctx, project, sc, chapters, events, f, forbidden, told_in, other, by_event, notes, scenes):
                done.add(sc.id)
    return notes


def _check_tension(ids: list[str]):
    def check(data: dict) -> list[str]:
        t = data.get("tension")
        if not isinstance(t, dict):
            return ['the reply must be {"tension": {"<chapter id>": <1-10>, ...}}']
        out = [f"{i} has no tension value" for i in ids if i not in t]
        out += [f"{i}: tension must be a whole number from 1 to 10" for i in ids if i in t and not (isinstance(t[i], int) and not isinstance(t[i], bool) and 1 <= t[i] <= 10)]
        return out
    return check


def fix_tension(ctx, chapters: list, findings: list) -> list[str]:
    """Rate the tension of each flat stretch of chapters again, from what happens in them (one narrow call per stretch); kept only if the check then no
    longer finds that stretch flat. Tension is a number the planning model wrote down, not part of the story's facts."""
    from ..validators import tension as tension_checks

    project = ctx.project
    if ctx.llm is None or not project.config.qc.fix_tension:
        return []
    notes: list[str] = []
    for f in findings[:4]:
        if f.severity != HARD or f.accepted or f.code != "flat_tension" or not f.items:
            continue
        ids = list(f.items)
        index = {c.id: i for i, c in enumerate(chapters)}
        picked = [chapters[index[x]] for x in ids if x in index]
        if len(picked) != len(ids):
            continue
        lo, hi = index[ids[0]], index[ids[-1]]
        around = [c for c in chapters[max(0, lo - 2):lo] + chapters[hi + 1:hi + 3]]
        old = {c.id: c.tension for c in picked}
        block = "\n".join(f"- {c.id} \"{c.title}\" (now {c.tension}): {c.purpose} {c.summary} End: {c.end_state}" for c in picked)
        near = "\n".join(f"- {c.id} \"{c.title}\" (tension {c.tension}): {c.summary[:240]}" for c in around) or "none"
        try:
            data = ask_json(ctx, f"fix flat tension {ids[0]}", project.config.layers["chapters"].model, "tension_fix", _check_tension(ids), max_tokens=500, chapters=block, around=near)
        except Exception as e:  # no new ratings is no change: the finding stays
            log.info("%s: flat tension not fixed (%s)", ids[0], e)
            continue
        values = data["tension"]
        if max(values[i] for i in ids) - min(values[i] for i in ids) < 3:
            log.info("%s: flat tension not fixed (the new ratings are still flat)", ids[0])
            continue
        for c in picked:
            c.tension = int(values[c.id])
        still = [x for x in tension_checks.flat_stretches([c.model_dump() for c in chapters]) if x.severity == HARD and set(x.items) & set(ids)]
        if still:
            for c in picked:
                c.tension = old[c.id]  # the new ratings are still a flat stretch: the saved ones stand
            log.info("%s: flat tension not fixed (the check still finds it)", ids[0])
            continue
        notes.append(f"{ids[0]} to {ids[-1]}: the tension stayed between {min(old.values())} and {max(old.values())}; it was rated again from what happens in each chapter and the check passes")
    return notes


def demote_unfixable(findings: list) -> list:
    """After the narrow fixes were tried: a hard finding that is still there and whose class never stops a stage (remedies/registry.py: wording, rating,
    advisory, and a decision below the ledger stage) becomes a soft one that says so. It stays in the stage checks, but the run goes on. Only a structural
    finding stops. A code the registry does not know is left hard (tests/test_registry.py keeps that from happening)."""
    from dataclasses import replace

    from ..remedies import registry
    from ..validators import SOFT

    out = []
    for f in findings:
        if f.severity == HARD and not f.accepted and not registry.stops_a_stage(f.code, f.stage):
            out.append(replace(f, severity=SOFT, message=f"(the tool tried to fix this and could not; kept as a warning) {f.message}"))
        else:
            out.append(f)
    return out


def _check_days(ids: list[str]):
    def check(data: dict) -> list[str]:
        d = data.get("days_later")
        if not isinstance(d, dict):
            return ['the reply must be {"days_later": {"<scene id>": <whole number>, ...}}']
        out = [f"{i} has no days_later value" for i in ids if i not in d]
        out += [f"{i}: days_later must be a whole number, 0 or more" for i in ids if i in d and not (isinstance(d[i], int) and not isinstance(d[i], bool) and d[i] >= 0)]
        return out
    return check


def fix_timeline(ctx, scenes: list, timeline: list, findings: list) -> list[str]:
    """Re-date the scenes of a book whose scenes all sit on one story day, from what happens in them (one narrow call, `days_later` per scene); kept only
    if the days then differ enough (`timeline_flat` no longer finds it). The days are a number the planning model wrote down, not a story fact."""
    from ..validators import state as state_checks

    project = ctx.project
    if ctx.llm is None or not project.config.qc.fix_timeline or not any(f.code == "timeline_flat" and f.severity == HARD and not f.accepted for f in findings):
        return []
    by_id = {t.id: t for t in timeline}
    main = [s for s in scenes if s.id in by_id and not by_id[s.id].flashback]
    if not main:
        return []
    ids = [s.id for s in main]
    listing = "\n".join(f"- {s.id} ({by_id[s.id].time}): {s.purpose}" for s in main)
    try:
        data = ask_json(ctx, "fix flat timeline", project.config.layers["scenes"].model, "timeline_fix", _check_days(ids), max_tokens=min(4000, 40 + 14 * len(ids)), scenes=listing)
    except Exception as e:  # no new dates is no change: the finding stays
        log.info("flat timeline not fixed (%s)", e)
        return []
    old = {t.id: t.day for t in timeline}
    day = 1
    for i, s in enumerate(main):
        day = 1 if i == 0 else day + int(data["days_later"][s.id])
        by_id[s.id].day = day
    after = [t.model_dump() for t in timeline]
    if state_checks.timeline_flat(after) or max(by_id[i].day for i in ids) == 1:
        for t in timeline:
            t.day = old[t.id]  # still flat: the saved days stand
        log.info("flat timeline not fixed (the new days are still flat)")
        return []
    return [f"the story days of the scenes were set again from what happens in them (day 1 to day {max(by_id[i].day for i in ids)}); the check passes"]


def _check_scene_overreach(original: tuple[str, list[str], str]):
    base = _check_scene((original[0], original[1]))

    def check(data: dict) -> list[str]:
        out = base(data)
        if not isinstance(data.get("end_state"), str) or not data["end_state"].strip():
            out.append('the reply must also have a non-empty "end_state"')
        return out
    return check


def fix_scene_overreach(ctx, scenes: list, chapters: list, events: list[dict], findings: list) -> list[str]:
    """A scene whose purpose, beats or end_state report the outcome of an event a later scene or chapter tells has those three texts rewritten in one
    narrow call; kept only if the check then no longer finds it (never on a scene you wrote yourself: these are plan texts, not prose)."""
    project = ctx.project
    if ctx.llm is None or not project.config.qc.fix_overreach:
        return []
    by_id = {s.id: s for s in scenes}
    by_event = {e["id"]: e for e in events}
    notes: list[str] = []
    done: set[str] = set()
    for f in findings[:MAX_FIXES]:
        if f.severity != HARD or f.accepted or f.code != "end_state_overreach" or f.stage != "scenes" or len(f.items) < 2:
            continue
        sid, ev_id = f.items[0], f.items[1]
        sc, ev = by_id.get(sid), by_event.get(ev_id)
        if sc is None or ev is None or sid in done:
            continue
        old = (sc.purpose, list(sc.beats), sc.end_state)
        quote = next((t for t in f.evidence if t.startswith("chapter:")), "")[len("chapter:"):].strip()
        try:
            data = ask_json(ctx, f"fix scene overreach {sid}", project.config.layers["scenes"].model, "scene_overreach_fix", _check_scene_overreach(old), max_tokens=1400,
                            purpose=sc.purpose, beats="\n".join(f"- {b}" for b in sc.beats), end_state=sc.end_state, event=f"{ev_id}: {ev['text']}", quote=quote)
        except Exception as e:
            log.info("%s: scene overreach not fixed (%s)", sid, e)
            continue
        sc.purpose, sc.beats, sc.end_state = data["purpose"].strip(), [b.strip() for b in data["beats"]], data["end_state"].strip()
        plain = [x.model_dump() for x in scenes]
        still = [x for x in state_claims.scene_end_state_overreach(plain, [c.model_dump() for c in chapters], events) if x.items[:2] == [sid, ev_id]]
        if still:
            sc.purpose, sc.beats, sc.end_state = old
            log.info("%s: scene overreach not fixed (the check still finds it)", sid)
            continue
        done.add(sid)
        notes.append(f"{sid}: its purpose, beats or end_state reported the outcome of {ev_id}, which a later scene or chapter tells; the wording was rewritten and the check passes")
    return notes
