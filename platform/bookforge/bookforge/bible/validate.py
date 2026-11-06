"""Parse and check what a model returns for layers 4-6, and cross-check the finished files.

Every parser returns (result, problems). With problems the result is None, and the problem
list is what gets sent back to the model for a correction round. Problems are written for a
model to act on: they say what is wrong and what is expected.
"""

import re
from dataclasses import dataclass, field

import yaml
from pydantic import ValidationError

from ..project import Project
from . import store
from .models import Act, Chapter, Constants, Entity, Rule, Scene, TimelineEntry, Track, problems_from
from .positions import act_id, canonical, chapter_id, parse_act_id, parse_position, scene_id


# A model often writes `summary: Anna finds it: the ledger` with the colon unquoted, which is not valid YAML.
_KEY_LINE = re.compile(r"^(?P<lead>\s*(?:-\s+)*)(?P<key>[A-Za-z_][\w .-]*?):[ \t]+(?P<value>\S.*?)\s*$")
_ALREADY_FINE = ('"', "'", "|", ">", "[", "{", "&", "*", "!", "#")


def quote_plain_colons(text: str) -> str:
    """Wrap in double quotes the plain `key: value` values that contain ': ', ' #' or end in ':' (YAML cannot read them).

    Only used after the text failed to parse, and only on single-line values; anything else is left as it was.
    """
    out = []
    block_indent: int | None = None  # inside a `|` or `>` block: its lines are text, not keys
    for line in text.splitlines():
        indent = len(line) - len(line.lstrip())
        if block_indent is not None:
            if not line.strip() or indent > block_indent:
                out.append(line)
                continue
            block_indent = None
        m = _KEY_LINE.match(line)
        if m and re.fullmatch(r"[|>][+-]?\d*", m["value"]):
            block_indent = indent
        elif m and not m["value"].startswith(_ALREADY_FINE) and (": " in m["value"] or " #" in m["value"] or m["value"].endswith(":")):
            value = m["value"].replace("\\", "\\\\").replace('"', '\\"')
            line = f'{m["lead"]}{m["key"]}: "{value}"'
        out.append(line)
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


def load_reply_yaml(text: str):
    """The YAML in a model reply. Returns (data, error). A reply with unquoted colons in its text is repaired and read."""
    try:
        return yaml.safe_load(text), None
    except yaml.YAMLError as first_error:
        try:
            return yaml.safe_load(quote_plain_colons(text)), None
        except yaml.YAMLError:
            pass
        e = first_error
    first = str(e).splitlines()[0] if str(e) else "unknown error"
    mark = getattr(e, "problem_mark", None)
    lines = text.splitlines()
    where = ""
    if mark is not None and 0 <= mark.line < len(lines):
        where = f" at line {mark.line + 1}: {lines[mark.line].strip()[:120]!r}"
    return None, f"the reply is not valid YAML ({first}){where}. Put double quotes around every text value that contains a colon."


def _items(data, key: str, problems: list[str], required: bool = True) -> list:
    if not isinstance(data, dict):
        problems.append(f"the top level must be a mapping with a '{key}:' list")
        return []
    value = data.get(key)
    if value is None and not required:
        return []
    if not isinstance(value, list):
        problems.append(f"'{key}' must be a list")
        return []
    return value


def _validate(cls, raw, label: str, problems: list[str]):
    try:
        return cls.model_validate(raw)
    except ValidationError as e:
        problems.extend(f"{label}.{p}" for p in problems_from(e, limit=4))
        return None


def entity_map(constants: Constants) -> dict[str, Entity]:
    return {e.id: e for e in constants.entities}


def _check_entity(entities: dict[str, Entity], eid: str, kind: str | None, label: str, problems: list[str],
                  also: tuple[str, ...] = ()) -> None:
    """The entity must exist and be of `kind` (or one of the `also` kinds). A wrong kind lists the ids that would do."""
    e = entities.get(eid)
    if e is None:
        problems.append(f"{label}: '{eid}' is not in the cast (known ids: {', '.join(sorted(entities)) or 'none'})")
    elif kind and e.kind != kind and e.kind not in also:
        fitting = sorted(i for i, x in entities.items() if x.kind == kind or x.kind in also)
        problems.append(f"{label}: '{eid}' is a {e.kind}, expected a {kind}"
                        + (f" (use one of: {', '.join(fitting[:15])})" if fitting else f" (the cast has no {kind} yet)"))


# A setting is where a scene happens: a place, or a thing people are inside (a ship, a carriage) that the cast lists as an object.
SETTING_ALSO = ("object",)


# ── layer 4: acts ───────────────────────────────────────────────────────────

def parse_acts(text: str, project: Project) -> tuple[list[Act] | None, list[str]]:
    data, error = load_reply_yaml(text)
    if error:
        return None, [error]
    problems: list[str] = []
    raw = _items(data, "acts", problems)
    cfg = project.config.layers
    lo, hi = cfg["acts"].count or (3, 4)
    if raw and not lo <= len(raw) <= hi:
        problems.append(f"expected {lo} to {hi} acts, got {len(raw)}")
    acts: list[Act] = []
    for i, item in enumerate(raw):
        act = _validate(Act, item, f"acts[{i}]", problems)
        if act is None:
            continue
        expected = act_id(project.book, i + 1)
        try:
            ok = parse_act_id(act.id) == (project.book, i + 1)
        except ValueError:
            ok = False
        if not ok:
            problems.append(f"acts[{i}].id is '{act.id}', expected '{expected}'")
        act.id = expected
        acts.append(act)
    clo, chi = cfg["chapters"].count or (25, 35)
    total = sum(a.chapter_count for a in acts)
    if acts and len(acts) == len(raw) and not clo <= total <= chi:
        problems.append(f"the chapter_count values add up to {total}; they must add up to between {clo} and {chi}")
    return (None, problems) if problems else (acts, [])


# ── layer 5a: the cast and world ────────────────────────────────────────────

def parse_cast(text: str, existing: Constants) -> tuple[Constants | None, list[str]]:
    """The NEW entities and rules a reply proposes. `existing` entries must not be repeated."""
    data, error = load_reply_yaml(text)
    if error:
        return None, [error]
    problems: list[str] = []
    entities_raw = _items(data, "entities", problems)
    rules_raw = _items(data, "rules", problems, required=False)
    known = {e.id for e in existing.entities}
    known_rules = {r.id for r in existing.rules}
    entities: list[Entity] = []
    for i, item in enumerate(entities_raw):
        e = _validate(Entity, item, f"entities[{i}]", problems)
        if e is None:
            continue
        if e.id in known:
            problems.append(f"entities[{i}]: '{e.id}' already exists; list only new entities")
        known.add(e.id)
        entities.append(e)
    rules: list[Rule] = []
    for i, item in enumerate(rules_raw):
        r = _validate(Rule, item, f"rules[{i}]", problems)
        if r is None:
            continue
        if r.id in known_rules:
            problems.append(f"rules[{i}]: '{r.id}' already exists")
        known_rules.add(r.id)
        rules.append(r)
    kinds = {e.kind for e in existing.entities} | {e.kind for e in entities}
    for needed in ("character", "place"):
        if needed not in kinds and not problems:
            problems.append(f"the cast needs at least one {needed}")
    return (None, problems) if problems else (Constants(entities=entities, rules=rules), [])


def merge_constants(existing: Constants, new: Constants) -> Constants:
    return Constants(entities=existing.entities + new.entities, rules=existing.rules + new.rules)


# ── tracks (shared by layers 5 and 6) ───────────────────────────────────────

def _owner_from_id(track_id: str, entities: dict[str, Entity]) -> str | None:
    """The cast id a track id starts with (anna-trust -> anna), the longest match if several; None if there is no single answer."""
    matches = sorted((eid for eid in entities if track_id.startswith(eid + "-")), key=len, reverse=True)
    if not matches or (len(matches) > 1 and len(matches[0]) == len(matches[1])):
        return None
    return matches[0]


def _parse_tracks(
    raw_tracks: list, *, entities: dict[str, Entity], existing: dict[str, Track], allowed_from: set[str],
    prefix: str, problems: list[str],
) -> list[Track]:
    out: list[Track] = []
    seen_ids: set[str] = set()
    for i, raw in enumerate(raw_tracks):
        label = f"{prefix}[{i}]"
        if isinstance(raw, dict) and not raw.get("entity"):
            if raw.get("id") in existing:
                raw = {**raw, "entity": existing[raw["id"]].entity}  # extending an existing track: the entity is known
            elif (owner := _owner_from_id(str(raw.get("id", "")), entities)):
                raw = {**raw, "entity": owner}  # a new track named after its owner, like anna-trust-in-jonas
            elif raw.get("id"):
                problems.append(f"{label}: track '{raw['id']}' is not an existing track and has no entity. To extend an existing track repeat "
                                f"one of its ids ({', '.join(sorted(existing)) or 'none yet'}); for a new track give 'entity:' (one of: "
                                f"{', '.join(sorted(entities))}) and 'kind:'")
                continue
        track = _validate(Track, raw, label, problems)
        if track is None:
            continue
        if track.id in seen_ids:
            problems.append(f"{label}: track '{track.id}' appears twice; put all its entries under one track")
        seen_ids.add(track.id)
        _check_entity(entities, track.entity, None, f"{label}.entity", problems)
        if track.id in existing and existing[track.id].entity != track.entity:
            problems.append(f"{label}: track '{track.id}' belongs to '{existing[track.id].entity}', not '{track.entity}'")
        froms: set[str] = set()
        for j, entry in enumerate(track.plan):
            where = f"{label}.plan[{j}]"
            try:
                entry.from_ = canonical(entry.from_)
            except ValueError as e:
                problems.append(f"{where}.from: {e}")
                continue
            if entry.from_ not in allowed_from:
                problems.append(f"{where}.from: '{entry.from_}' is not one of: {', '.join(sorted(allowed_from))}")
            if entry.from_ in froms:
                problems.append(f"{where}.from: '{entry.from_}' is used twice in track '{track.id}'")
            froms.add(entry.from_)
        track.plan.sort(key=lambda e: parse_position(e.from_).key if _is_position(e.from_) else (0, 0))
        track.version = existing[track.id].version if track.id in existing else 1
        track.observed = []
        out.append(track)
    return out


def _is_position(text: str) -> bool:
    try:
        parse_position(text)
        return True
    except ValueError:
        return False


def _check_research_ids(ids: list[str], known: set[str], label: str, problems: list[str]) -> None:
    unknown = [i for i in ids if i not in known]
    if unknown:
        problems.append(f"{label}: unknown research fact id(s) {', '.join(unknown)} (use only ids from the research notes)")


# ── layer 5b: chapters of one act ───────────────────────────────────────────

@dataclass
class ChaptersBundle:
    chapters: list[Chapter] = field(default_factory=list)
    tracks: list[Track] = field(default_factory=list)


def parse_chapters(
    text: str, *, project: Project, act: Act, first_number: int, constants: Constants,
    tracks_so_far: list[Track], fact_ids: set[str],
) -> tuple[ChaptersBundle | None, list[str]]:
    data, error = load_reply_yaml(text)
    if error:
        return None, [error]
    problems: list[str] = []
    raw = _items(data, "chapters", problems)
    entities = entity_map(constants)
    if raw and len(raw) != act.chapter_count:
        problems.append(f"{act.id} needs exactly {act.chapter_count} chapters, got {len(raw)}")
    chapters: list[Chapter] = []
    for i, item in enumerate(raw):
        label = f"chapters[{i}]"
        ch = _validate(Chapter, item, label, problems)
        if ch is None:
            continue
        expected = chapter_id(project.book, first_number + i)
        try:
            ok = canonical(ch.id) == expected
        except ValueError:
            ok = False
        if not ok:
            problems.append(f"{label}.id is '{ch.id}', expected '{expected}'")
        ch.id, ch.act = expected, act.id
        _check_entity(entities, ch.pov, "character", f"{label}.pov", problems)
        _check_entity(entities, ch.setting, "place", f"{label}.setting", problems, SETTING_ALSO)
        _check_research_ids(ch.research, fact_ids, label, problems)
        chapters.append(ch)
    allowed = {chapter_id(project.book, first_number + i) for i in range(act.chapter_count)}
    existing = {t.id: t for t in tracks_so_far}
    tracks = _parse_tracks(_items(data, "tracks", problems, required=False), entities=entities, existing=existing,
                           allowed_from=allowed, prefix="tracks", problems=problems)
    if raw and not any(t.plan for t in tracks):
        # Without tracks the story's changes (injuries, who knows what, where people are) are neither planned nor checked later.
        problems.append(f"{act.id} defines no state tracks: add a 'tracks:' list with at least one track created or extended in these chapters "
                        "(an injury, where a key character is, a relationship, a possession, who knows which secret)")
    return (None, problems) if problems else (ChaptersBundle(chapters, tracks), [])


# ── layer 6: scenes of one chapter ──────────────────────────────────────────

@dataclass
class ScenesBundle:
    scenes: list[Scene] = field(default_factory=list)
    timeline: list[TimelineEntry] = field(default_factory=list)
    tracks_after: list[Track] = field(default_factory=list)  # the full track list with this chapter's entries refined


def _in_chapter(entry_from: str, book: str, chapter: int) -> bool:
    try:
        p = parse_position(entry_from)
    except ValueError:
        return False
    return p.book == book and p.chapter == chapter


def parse_scenes(
    text: str, *, project: Project, chapter: Chapter, prev_day: int | None, constants: Constants,
    tracks_so_far: list[Track], fact_ids: set[str],
) -> tuple[ScenesBundle | None, list[str]]:
    data, error = load_reply_yaml(text)
    if error:
        return None, [error]
    problems: list[str] = []
    raw = _items(data, "scenes", problems)
    entities = entity_map(constants)
    lo, hi = project.config.layers["scenes"].per_chapter or (2, 4)
    if raw and not lo <= len(raw) <= hi:
        problems.append(f"{chapter.id} needs {lo} to {hi} scenes, got {len(raw)}")
    ch_num = parse_position(chapter.id).chapter
    scenes: list[Scene] = []
    timeline: list[TimelineEntry] = []
    main_day = prev_day
    for i, item in enumerate(raw):
        label = f"scenes[{i}]"
        scene = _validate(Scene, item, label, problems)
        when = _validate(TimelineEntry, item, label, problems)
        if scene is None or when is None:
            continue
        expected = scene_id(project.book, ch_num, i + 1)
        try:
            ok = canonical(scene.id) == expected
        except ValueError:
            ok = False
        if not ok:
            problems.append(f"{label}.id is '{scene.id}', expected '{expected}'")
        scene.id = when.id = expected
        scene.chapter = chapter.id
        _check_entity(entities, scene.pov, "character", f"{label}.pov", problems)
        _check_entity(entities, scene.setting, "place", f"{label}.setting", problems, SETTING_ALSO)
        for c in scene.characters:
            _check_entity(entities, c, "character", f"{label}.characters", problems)
        if scene.pov not in scene.characters:
            scene.characters.insert(0, scene.pov)  # the point-of-view character is always present
        _check_research_ids(scene.research, fact_ids, label, problems)
        if not when.flashback:
            if main_day is not None and when.day < main_day:
                problems.append(f"{label}: day {when.day} is before day {main_day} of the previous scene; "
                                "put the scenes in story order, or set flashback: true")
            main_day = when.day
        scenes.append(scene)
        timeline.append(when)

    allowed = {scene_id(project.book, ch_num, i + 1) for i in range(len(raw))}
    existing = {t.id: t for t in tracks_so_far}
    refined = _parse_tracks(_items(data, "tracks", problems, required=False), entities=entities, existing=existing,
                            allowed_from=allowed, prefix="tracks", problems=problems)
    tracks_after = _apply_refinement(refined, tracks_so_far, project.book, ch_num, chapter.id, problems)
    return (None, problems) if problems else (ScenesBundle(scenes, timeline, tracks_after), [])


def _apply_refinement(
    refined: list[Track], tracks_so_far: list[Track], book: str, ch_num: int, chapter_ref: str, problems: list[str],
) -> list[Track]:
    """Replace each track's entries for this chapter with the scene-level ones the model gave.

    Guards against silent loss: every track that already has entries in this chapter has to be
    restated, with at least as many entries and as many must_show entries as before.
    """
    by_id = {t.id: t.model_copy(deep=True) for t in tracks_so_far}
    order = [t.id for t in tracks_so_far]
    given = {t.id: t for t in refined}
    for t in tracks_so_far:
        old = [e for e in t.plan if _in_chapter(e.from_, book, ch_num)]
        if not old:
            continue
        new = given.get(t.id)
        if new is None:
            problems.append(f"track '{t.id}' already has planned states in {chapter_ref}; restate it at scene level "
                            "(keep every state, even unchanged ones)")
            continue
        if len(new.plan) < len(old):
            problems.append(f"track '{t.id}' had {len(old)} state(s) in {chapter_ref} but you gave {len(new.plan)}; do not drop states")
        if sum(e.must_show for e in new.plan) < sum(e.must_show for e in old):
            problems.append(f"track '{t.id}' lost a must_show state in {chapter_ref}; keep every must_show state, placed in the scene where it happens")
    for t in refined:
        if t.id in by_id:
            cur = by_id[t.id]
            before = [(e.from_, e.value, e.must_show) for e in cur.plan if _in_chapter(e.from_, book, ch_num)]
            kept = [e for e in cur.plan if not _in_chapter(e.from_, book, ch_num)]
            cur.plan = sorted(kept + t.plan, key=lambda e: parse_position(e.from_).key)
            after = [(e.from_, e.value, e.must_show) for e in t.plan]
            if before != after:
                cur.version += 1
        else:
            by_id[t.id] = t
            order.append(t.id)
    return [by_id[i] for i in order]


# ── whole-book cross-check ──────────────────────────────────────────────────

def validate_bible(project: Project, require_scenes: bool = False) -> list[str]:
    """Problems across the files on disk: references that do not resolve, gaps, ordering."""
    try:
        constants = store.load_constants(project)
        tracks = store.load_tracks(project)
        timeline = store.load_timeline(project)
        acts = store.load_acts(project)
        chapters = store.load_chapters(project)
        scenes = store.load_scenes(project)
    except store.BibleError as e:
        return [str(e)]
    book = project.book
    problems: list[str] = []
    entities = entity_map(constants)

    act_ids = {a.id for a in acts}
    for n, ch in enumerate(chapters, 1):
        if ch.id != chapter_id(book, n):
            problems.append(f"chapters.yaml: chapter {n} has id '{ch.id}', expected '{chapter_id(book, n)}'")
        if acts and ch.act not in act_ids:
            problems.append(f"{ch.id}: act '{ch.act}' is not in acts.yaml")
        _check_entity(entities, ch.pov, "character", f"{ch.id}.pov", problems)
        _check_entity(entities, ch.setting, "place", f"{ch.id}.setting", problems, SETTING_ALSO)
    chapter_ids = {c.id for c in chapters}

    scene_ids = {s.id for s in scenes}
    if require_scenes and not scenes:
        problems.append("scenes.yaml has no scenes")
    lo, hi = project.config.layers["scenes"].per_chapter or (2, 4)
    counts: dict[str, int] = {}
    for s in scenes:
        counts[s.chapter] = counts.get(s.chapter, 0) + 1
        if s.chapter not in chapter_ids:
            problems.append(f"{s.id}: chapter '{s.chapter}' is not in chapters.yaml")
        _check_entity(entities, s.pov, "character", f"{s.id}.pov", problems)
        _check_entity(entities, s.setting, "place", f"{s.id}.setting", problems, SETTING_ALSO)
        for c in s.characters:
            _check_entity(entities, c, "character", f"{s.id}.characters", problems)
    if scenes:
        for ch in chapters:
            if not lo <= counts.get(ch.id, 0) <= hi:
                problems.append(f"{ch.id}: has {counts.get(ch.id, 0)} scenes, expected {lo} to {hi}")
        timed = {t.id for t in timeline}
        for s in scenes:
            if s.id not in timed:
                problems.append(f"{s.id}: missing from timeline.yaml")
        main_day = None
        by_id = {t.id: t for t in timeline}
        for s in scenes:
            t = by_id.get(s.id)
            if t is None or t.flashback:
                continue
            if main_day is not None and t.day < main_day:
                problems.append(f"timeline.yaml: {s.id} is on day {t.day}, before day {main_day}")
            main_day = t.day

    for t in tracks:
        _check_entity(entities, t.entity, None, f"track {t.id}", problems)
        seen: set[str] = set()
        for e in t.plan:
            try:
                p = parse_position(e.from_)
            except ValueError as err:
                problems.append(f"track {t.id}: {err}")
                continue
            if e.from_ in seen:
                problems.append(f"track {t.id}: two entries start at {e.from_}")
            seen.add(e.from_)
            if p.book != book:
                continue
            if chapters and p.chapter_ref not in chapter_ids:
                problems.append(f"track {t.id}: {e.from_} is not a chapter in chapters.yaml")
            if scenes:
                if p.is_scene and e.from_ not in scene_ids:
                    problems.append(f"track {t.id}: {e.from_} is not a scene in scenes.yaml")
                if not p.is_scene and e.must_show:
                    problems.append(f"track {t.id}: the must_show state at {e.from_} is not pinned to a scene")
    return problems
