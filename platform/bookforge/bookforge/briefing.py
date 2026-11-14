"""The briefing pack: everything a model is given to write one scene, within a token budget.

Never the whole book. The pack has six parts (docs/BOOKFORGE.md): the north stars; the style guide
and sample passages; the cast and rules, the state of every track for the people and places in the
scene, and when it happens; the scene's beats, its chapter and its research notes; summaries of the
story so far, compressed the older they are; and the end of the previous scene verbatim.

If the pack is over budget it is cut down in a fixed order, least harmful first (older summaries,
research notes, the previous scene's tail, sample passages, the style guide). The beats, the story
state and the north stars are never cut. If they alone do not fit, building fails.

Token counts are estimates (about 3.5 characters per token), good enough to stay under a budget.
"""

import math
from dataclasses import dataclass, field
from urllib.parse import urlparse

from . import rules, scenefiles
from .bible import store
from .bible.lookup import day_of, scene_entities, state_at
from .bible.models import Chapter, Constants, Scene, TimelineEntry
from .bible.positions import parse_position
from .deps import Deps, tag
from .errors import BookforgeError
from .project import Project
from .qc.mechanical import load_banned
from .research.notes import approved_decisions, stores_for

CHARS_PER_TOKEN = 3.5
MAX_RESEARCH_NOTES = 3  # research informs accuracy and texture; a handful of notes cannot steer the scene
ONE_LINER_CHARS = {0: 200, 1: 200, 2: 160, 3: 120}


class BriefingError(BookforgeError):
    pass


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN)


@dataclass
class Section:
    heading: str
    body: str

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.heading + self.body)


@dataclass
class Briefing:
    scene_id: str
    sections: list[Section]
    deps: Deps
    budget: int
    trimmed: list[str] = field(default_factory=list)  # what was cut to fit the budget

    @property
    def tokens(self) -> int:
        return sum(s.tokens for s in self.sections)

    def text(self) -> str:
        return "\n\n".join(f"## {s.heading}\n\n{s.body}" for s in self.sections)

    def breakdown(self) -> list[tuple[str, int]]:
        return [(s.heading, s.tokens) for s in self.sections]


@dataclass
class _Knobs:
    summaries: int = 0  # 0 = as configured, 1-3 = progressively shorter
    research_chars: int | None = None
    previous_words: int = 1500
    samples: int = 2
    sample_chars: int | None = None
    guide_chars: int | None = None


def _ladder(project: Project) -> list[tuple[_Knobs, str]]:
    cfg = project.config.briefing
    base = dict(previous_words=cfg.previous_scene_words, samples=cfg.sample_passages)
    steps = [
        (dict(), ""),
        (dict(summaries=1), "older chapter summaries shortened"),
        (dict(summaries=2), "chapter summaries cut to one line each"),
        (dict(summaries=3), "only the most recent chapters are summarised"),
        (dict(research_chars=1500), "research notes shortened"),
        (dict(previous_words=min(cfg.previous_scene_words, 150)), "previous scene tail cut to 150 words"),
        (dict(samples=min(cfg.sample_passages, 1), sample_chars=2500), "one sample passage, shortened"),
        (dict(samples=min(cfg.sample_passages, 1), sample_chars=1200), "sample passage cut to 1200 characters"),
        (dict(guide_chars=2500), "style guide shortened"),
    ]
    out, acc = [], dict(base)
    for change, note in steps:
        acc.update(change)
        out.append((_Knobs(**acc), note))
    return out


def _clip(text: str, chars: int | None) -> str:
    if chars is None or len(text) <= chars:
        return text
    return text[: chars - 3].rstrip() + "..."


def _tail_words(text: str, n: int) -> str:
    """The last n words, starting at a sentence start when one is near."""
    parts = text.split()
    if len(parts) <= n:
        return text.strip()
    tail = " ".join(parts[-n:])
    for i, ch in enumerate(tail[:400]):
        if ch in ".!?" and i + 2 < len(tail) and tail[i + 1] == " ":
            return tail[i + 2:]
    return tail


def _source(url: str) -> str:
    p = urlparse(url)
    return (p.hostname or "") + (p.path if len(p.path) < 40 else p.path[:37] + "...")


class _Data:
    """Everything the builder reads, loaded once."""

    def __init__(self, project: Project, scene_id: str):
        self.project = project
        self.constants = store.load_constants(project)
        self.tracks = store.load_tracks(project)
        self.timeline = store.load_timeline(project)
        self.chapters = store.load_chapters(project)
        self.scenes = store.load_scenes(project)
        by_id = {s.id: s for s in self.scenes}
        if scene_id not in by_id:
            raise BriefingError(f"no scene {scene_id} in scenes.yaml (has the scenes layer run?)")
        self.scene: Scene = by_id[scene_id]
        chapters = {c.id: c for c in self.chapters}
        self.chapter: Chapter = chapters[self.scene.chapter]
        self.names = {e.id: e.name for e in self.constants.entities}
        self.facts = {f.id: f for s in stores_for(project).values() for f in s.facts()}

    def name(self, eid: str) -> str:
        return self.names.get(eid, eid)

    def timeline_entry(self, scene_id: str) -> TimelineEntry | None:
        return next((t for t in self.timeline if t.id == scene_id), None)


def build_briefing(project: Project, scene_id: str, max_tokens: int | None = None) -> Briefing:
    data = _Data(project, scene_id)
    budget = max_tokens or project.config.briefing.max_tokens
    trimmed: list[str] = []
    for knobs, note in _ladder(project):
        if note:
            trimmed.append(note)
        sections, deps = _assemble(data, knobs)
        briefing = Briefing(scene_id, sections, deps, budget, list(trimmed))
        if briefing.tokens <= budget:
            return briefing
    top = ", ".join(f"{h} ({t})" for h, t in sorted(briefing.breakdown(), key=lambda x: -x[1])[:4])
    raise BriefingError(f"the briefing for {scene_id} is about {briefing.tokens} tokens, over the budget of {budget}, "
                        f"even after cutting everything that can be cut. Largest parts: {top}")


def _assemble(d: _Data, k: _Knobs) -> tuple[list[Section], Deps]:
    project, scene, chapter = d.project, d.scene, d.chapter
    deps = Deps(scene=tag(scene.id, [scene.model_dump(), (d.timeline_entry(scene.id) or TimelineEntry(id=scene.id, day=1, time="?")).model_dump()]),
                parent=tag(chapter.id, chapter.model_dump()))
    sections: list[Section] = []

    # 1. north stars
    series = (project.root / "north-star.md").read_text(encoding="utf-8").strip()
    book = (project.book_dir / "north-star.md").read_text(encoding="utf-8").strip()
    sections += [Section("Series north star", series), Section("Book north star", book)]
    deps.north_stars = [tag("series", series), tag(project.book, book)]

    # 2. style
    guide = scenefiles.read(project.root / "style" / "guide.md") or ""
    if all(not line.strip() or line.lstrip().startswith("#") for line in guide.splitlines()):
        guide = ""  # only the placeholder heading: there is no style guide yet
    guide_text = _clip(guide.strip(), k.guide_chars)
    sections.append(Section("Style guide", guide_text or "(no style guide yet: follow the tone in the north stars)"))
    deps.style.append(tag("guide", guide))
    sample_dir = project.root / "style" / "samples"
    samples = sorted(p for p in sample_dir.glob("*.md") if p.read_text(encoding="utf-8").strip()) if sample_dir.is_dir() else []
    chosen = samples[: k.samples]
    if chosen:
        body = "\n\n".join(f"### {p.stem}\n\n{_clip(p.read_text(encoding='utf-8').strip(), k.sample_chars)}" for p in chosen)
        sections.append(Section("Sample passages (the voice to match; do not copy their content)", body))
        deps.style += [tag(f"sample:{p.name}", p.read_text(encoding="utf-8")) for p in chosen]
    banned_file = scenefiles.read(project.root / project.config.qc.banned_phrases) or ""
    scene_rules = rules.rules_for(project, scene)
    banned = load_banned(banned_file) + [r.phrase.strip() for r in scene_rules if r.type == "banned_phrase" and r.severity in ("block", "warn")]
    if banned:
        shown = [b[3:] if b.startswith("re:") else b for b in banned][:80]
        sections.append(Section("Phrases never to use", "\n".join(f"- {b}" for b in shown)))
    deps.style.append(tag("banned", banned_file))
    style_part, constraint_part = rules.fingerprint_parts(project, scene)
    if style_part:  # only when there are rules, so books written before the rules panel do not all go stale
        deps.style.append(tag("rules", style_part))
    if constraint_part:
        deps.bible.append(tag("rules:hard-constraints", constraint_part))
    rule_text = rules.prose_rules_text(project, scene)
    if rule_text:
        sections.append(Section("The author's rules for this scene", rule_text))

    # 3. cast, rules, state, time
    entity_ids = scene_entities(d.scenes, scene.id)
    entities = [e for e in d.constants.entities if e.id in entity_ids]
    lines = [f"- {e.name} ({e.kind}, id {e.id}): " + "; ".join(e.facts) for e in entities]
    lines += [f"- Rule: {r.text}" for r in d.constants.rules]
    sections.append(Section("Cast and rules of the world (fixed facts)", "\n".join(lines) or "none"))
    deps.bible += [tag(f"entity:{e.id}", e.model_dump()) for e in entities]
    deps.bible += [tag(f"rule:{r.id}", r.model_dump()) for r in d.constants.rules]

    decisions = approved_decisions(project, scene.id)
    if decisions:
        kind = {"invent": "invented", "extrapolate": "assumed", "bend": "changed on purpose"}
        sections.append(Section("The author's decisions about this world (canon: " + "invented or changed on purpose, not real-world fact)",
                                "\n".join(f"- ({kind[n.stance]}) {n.rule}" for n in decisions)))
        deps.bible += [tag(f"decision:{n.id}", [n.stance, n.rule]) for n in decisions]

    states = state_at(d.tracks, scene.id, entity_ids)
    state_lines = []
    for s in states:
        line = f"- {d.name(s.entity)} ({s.kind}): {s.value}"
        if s.begins_here:
            line += "\n    " + ("This change happens IN THIS SCENE and must be shown on the page." if s.must_show
                                else "This state begins in this scene.")
            if s.previous:
                line += f" Before this: {s.previous}"
        state_lines.append(line)
        deps.bible.append(tag(f"track:{s.track_id}", [s.since, s.value, s.must_show, s.previous]))
    sections.append(Section("Story state at this scene (facts the scene must not contradict)",
                            "\n".join(state_lines) or "no tracked states apply yet"))

    when = d.timeline_entry(scene.id)
    prev = scenefiles.previous_scene(d.scenes, scene.id)
    prev_when = d.timeline_entry(prev.id) if prev else None
    if when:
        text = f"Story day {when.day}, {when.time}" + (f" ({when.date})" if when.date else "") + (" - a flashback" if when.flashback else "")
        if prev_when and not when.flashback:
            gap = when.day - prev_when.day
            text += ("; the same day as the previous scene" if gap == 0 else f"; {gap} day(s) after the previous scene")
        if when.travel:
            text += f"; travel: {when.travel}"
        sections.append(Section("When this scene happens", text))
        deps.timeline.append(tag(scene.id, when.model_dump()))
    if prev_when:
        deps.timeline.append(tag(prev_when.id, prev_when.model_dump()))

    # 4. the scene, the chapter, research
    beats = "\n".join(f"{i}. {b}" for i, b in enumerate(scene.beats, 1))
    sections.append(Section("This scene", f"Scene {scene.id}\nPurpose: {scene.purpose}\nViewpoint character: {d.name(scene.pov)}\n"
                                          f"Setting: {d.name(scene.setting)}\nPresent: {', '.join(d.name(c) for c in scene.characters)}\n"
                                          f"Beats, in order (what happens and why, not how to write it):\n{beats}"))
    sections.append(Section("This chapter", f"{chapter.id} {chapter.title}\nPurpose: {chapter.purpose}\nSummary: {chapter.summary}\n"
                                            f"Tension: {chapter.tension}/10"))
    fact_ids = list(dict.fromkeys(scene.research + chapter.research))[:MAX_RESEARCH_NOTES]
    facts = [d.facts[i] for i in fact_ids if i in d.facts]
    if facts:
        body = _clip("\n".join(f"- [{f.id}] {f.claim} (source: {_source(f.url)})" for f in facts), k.research_chars)
        sections.append(Section("Research notes (reference only: for accuracy and texture; never a beat, an obstacle or a plot device)", body))
        deps.research = [tag(f.id, [f.claim, f.url, f.quote]) for f in facts]

    # 4b. events that belong to later chapters (only when the book has a ledger): not to be used yet
    later = _reserved_events(d)
    if later:
        sections.append(Section("Not yet: story events reserved for later (do not show, hint at or resolve them)", later))
        deps.bible.append(tag("ledger:reserved", later))

    # 5. the story so far
    so_far, summary_tags = _story_so_far(d, k)
    if so_far:
        sections.append(Section("The story so far", so_far))
    deps.summaries = summary_tags

    # 6. the end of the previous scene
    if prev:
        text = scenefiles.best_text(project, prev.id)
        if text:
            tail = _tail_words(text, k.previous_words)
            sections.append(Section(f"How the previous scene ended ({prev.id}): continue the moment; do not restate or summarize it", tail))
            deps.previous = [tag(prev.id, tail)]
    return sections, deps


def _reserved_events(d: _Data) -> str:
    from .bible.store import active_ledger
    ledger = active_ledger(d.project)
    if ledger is None:
        return ""
    cur = parse_position(d.chapter.id).chapter
    covered_now_or_before = {ev for c in d.chapters if parse_position(c.id).chapter <= cur for ev in c.events_covered}
    return "\n".join(f"- {e.id}: {e.text}" for e in ledger.events if e.id not in covered_now_or_before and not e.carried_in)


def _scene_summary(d: _Data, s: Scene) -> tuple[str, str]:
    """(text, how it was made): the summary written after the accepted prose, else the scene's planned end state, else nothing.

    The story so far is what happened, never what was intended: a plan's purpose or beats are not given as history.
    """
    written = scenefiles.read(scenefiles.summary_path(d.project, s.id))
    if written:
        return written.strip(), "written"
    if s.end_state.strip():
        return f"(planned) {s.end_state.strip()}", "end_state"
    return "", "none"


def _story_so_far(d: _Data, k: _Knobs) -> tuple[str, list[str]]:
    cur = parse_position(d.chapter.id).chapter
    cfg = d.project.config.briefing
    full = {0: cfg.recent_chapters_full, 1: min(1, cfg.recent_chapters_full), 2: 0, 3: 0}[k.summaries]
    one_liner = ONE_LINER_CHARS[k.summaries]
    earlier = [c for c in d.chapters if parse_position(c.id).chapter < cur]
    if k.summaries == 3:
        earlier = earlier[-6:]
    by_chapter: dict[str, list[Scene]] = {}
    for s in d.scenes:
        by_chapter.setdefault(s.chapter, []).append(s)
    lines: list[str] = []
    tags: list[str] = []
    for idx, c in enumerate(earlier):
        scenes = by_chapter.get(c.id, [])
        pieces = [(s, *_scene_summary(d, s)) for s in scenes]
        if idx >= len(earlier) - full:
            told = [(s, text) for s, text, _ in pieces if text]
            if not told:
                continue  # nothing happened on the page yet, and a plan is not history
            lines.append(f"{c.id} {c.title}:")
            for s, text in told:
                lines.append(f"  - {s.id}: {text}")
                tags.append(tag(f"summary:{s.id}", text))
        else:
            joined = " ".join(t for _, t, _ in pieces if t) or c.end_state or ""
            if not joined:
                continue
            lines.append(f"- {c.id} {c.title}: {_clip(joined, one_liner)}")
            tags.append(tag(f"summary:{c.id}", joined))
    here = [s for s in by_chapter.get(d.chapter.id, []) if parse_position(s.id).scene < parse_position(d.scene.id).scene]
    if here:
        lines.append(f"Earlier in this chapter ({d.chapter.id}):")
        for s in here:
            text, _ = _scene_summary(d, s)
            if text:
                lines.append(f"  - {s.id}: {text}")
                tags.append(tag(f"summary:{s.id}", text))
    return "\n".join(lines), tags
