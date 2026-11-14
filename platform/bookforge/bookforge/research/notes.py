"""Where research lives: facts with their sources, and the questions asked.

Per scope (the series, or one book) a `research/` folder holds
  sources.jsonl   one line per fact: id, claim, url, title, date fetched, quote, layer, question
  questions.jsonl one line per question asked, answered or not, with the reason when not
  <layer>.md      the same, readable (rewritten after each research step)
Fact ids are `s-0001` for the series and `<book>-0001` (for example `b1-0001`) for a book,
so a scene can refer to any fact by id.
"""

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from ..bible.positions import Position, parse_position
from ..project import Project

log = logging.getLogger("platform_bookforge.research")


@dataclass
class Fact:
    id: str
    claim: str
    url: str
    title: str
    fetched: str  # ISO date the page was read
    quote: str  # verbatim text from the page that supports the claim
    layer: str
    question: str
    sensitive: bool = False  # history, medicine, real places or people: verify before publishing


@dataclass
class QuestionRecord:
    layer: str
    question: str
    query: str
    answered: bool
    fact_ids: list[str] = field(default_factory=list)
    reason: str = ""  # why it was not answered
    sensitive: bool = False
    context: str = ""  # the time and place an answer had to fit


STANCES = ("ground", "extrapolate", "bend", "invent")
# ground: the real world must be right; extrapolate: a real basis, an imagined application; bend: the truth is known and
# deliberately changed; invent: nothing real to look up. Only ground needs no approval: a lookup changes nothing.
LOOKUP_STANCES = ("ground", "extrapolate", "bend")
NEED_STATUSES = ("proposed", "approved", "rejected")
MAX_RULE_CHARS_STORED = 500


@dataclass
class Need:
    """Something the story needs to know or decide, how it is to be handled, and what came of it."""
    id: str
    layer: str
    question: str
    stance: str = "ground"
    reason: str = ""  # the model's one-line reason for the stance
    rule: str = ""  # invent: the rule proposed; extrapolate: what the story assumes; bend: the deviation and why
    query: str = ""
    context: str = ""  # the time and place an answer had to fit
    sensitive: bool = False
    status: str = "proposed"
    fact_ids: list[str] = field(default_factory=list)
    decided_by: str = ""  # "auto" for a lookup, "author" once you decided
    applies_to: list[str] = field(default_factory=list)  # chapter or scene ids it applies to; empty = the whole book (or series)


def normalize_question(q: str) -> str:
    return " ".join(q.casefold().split())


def _read_jsonl(path: Path, cls):
    if not path.exists():
        return []
    out = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            out.append(cls(**json.loads(line)))
        except (ValueError, TypeError) as e:
            log.warning("%s line %d is not a valid record, skipped: %s", path, n, e)
    return out


def _append_jsonl(path: Path, records) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")


class ResearchStore:
    def __init__(self, directory: Path, prefix: str, root: Path):
        self.dir = directory
        self.prefix = prefix
        self._root = root

    @property
    def sources_path(self) -> Path:
        return self.dir / "sources.jsonl"

    @property
    def questions_path(self) -> Path:
        return self.dir / "questions.jsonl"

    def rel(self, path: Path) -> str:
        return str(path.relative_to(self._root))

    def facts(self) -> list[Fact]:
        return _read_jsonl(self.sources_path, Fact)

    def questions(self) -> list[QuestionRecord]:
        return _read_jsonl(self.questions_path, QuestionRecord)

    def current_questions(self) -> list[QuestionRecord]:
        """One record per question, the latest attempt winning, so a retried question shows once."""
        latest: dict[str, QuestionRecord] = {}
        for r in self.questions():
            latest[normalize_question(r.question)] = r
        return list(latest.values())

    def answered_count(self, layer: str) -> int:
        return sum(1 for r in self.current_questions() if r.layer == layer and r.answered)

    @property
    def archive_dir(self) -> Path:
        return self.dir / "archive"

    def archived_fact_ids(self) -> set[str]:
        """Ids of facts moved to the archive by a redo, so that a new fact never takes an id an old one had."""
        ids: set[str] = set()
        for path in sorted(self.archive_dir.glob("*.jsonl")) if self.archive_dir.is_dir() else []:
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict) and rec.get("kind") == "fact" and isinstance(rec.get("record"), dict):
                    ids.add(str(rec["record"].get("id", "")))
        return ids

    def next_fact_id(self) -> str:
        numbers = []
        for fid in [f.id for f in self.facts()] + list(self.archived_fact_ids()):
            tail = fid.rsplit("-", 1)[-1]
            if fid.startswith(self.prefix + "-") and tail.isdigit():
                numbers.append(int(tail))
        return f"{self.prefix}-{max(numbers, default=0) + 1:04d}"

    def known_urls(self) -> set[str]:
        return {f.url for f in self.facts()}

    def add_fact(self, **fields) -> Fact:
        fact = Fact(id=self.next_fact_id(), **fields)
        _append_jsonl(self.sources_path, [fact])
        return fact

    def add_question(self, record: QuestionRecord) -> None:
        _append_jsonl(self.questions_path, [record])

    @property
    def needs_path(self) -> Path:
        return self.dir / "needs.jsonl"

    @property
    def needs_md_path(self) -> Path:
        return self.dir / "needs.md"

    def needs(self) -> list[Need]:
        """One record per need, the latest line for an id winning (a decision appends a line, it never rewrites one)."""
        latest: dict[str, Need] = {}
        for n in _read_jsonl(self.needs_path, Need):
            latest[n.id] = n
        return list(latest.values())

    def next_need_id(self) -> str:
        numbers = [int(n.id.rsplit("-n", 1)[-1]) for n in self.needs() if n.id.startswith(self.prefix + "-n") and n.id.rsplit("-n", 1)[-1].isdigit()]
        return f"{self.prefix}-n{max(numbers, default=0) + 1:03d}"

    def add_need(self, **fields) -> Need:
        need = Need(id=self.next_need_id(), **fields)
        _append_jsonl(self.needs_path, [need])
        return need

    def save_need(self, need: Need) -> None:
        _append_jsonl(self.needs_path, [need])

    def write_needs_md(self) -> Path | None:
        """needs.md: every need with its stance, status and outcome, for review at the checkpoints."""
        needs = self.needs()
        if not needs:
            return None
        facts = {f.id: f for f in self.facts()}
        lines = ["# What the story needs to know or decide", "",
                 "Each need has a stance: **ground** (the real world must be right), **extrapolate** (a real basis, an imagined",
                 "application), **bend** (the truth is known and changed on purpose) or **invent** (nothing real to look up).",
                 "A lookup runs at once. A rule, assumption or deviation has no effect until it is approved:",
                 "`python -m bookforge needs <series> --approve ID` (or `--reject ID`, `--stance`, `--rule \"...\"`).", ""]
        for n in needs:
            lines.append(f"## {n.id} [{n.stance}, {n.status}] {n.question}" + (" (sensitive: verify)" if n.sensitive else ""))
            if n.reason:
                lines.append(f"- why: {n.reason}")
            if n.rule:
                lines.append(f"- {'rule' if n.stance == 'invent' else 'assumption' if n.stance == 'extrapolate' else 'deviation'}: {n.rule}")
            if n.applies_to:
                lines.append(f"- applies to: {', '.join(n.applies_to)}")
            for fid in n.fact_ids:
                f = facts.get(fid)
                if f:
                    lines.append(f"- [{f.id}] {f.claim}")
            if n.stance in LOOKUP_STANCES and not n.fact_ids:
                lines.append("- no facts found yet")
            lines.append("")
        self.needs_md_path.parent.mkdir(parents=True, exist_ok=True)
        self.needs_md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        return self.needs_md_path

    def write_notes(self, layer: str) -> Path:
        """Rewrite <layer>.md from the two logs."""
        facts = {f.id: f for f in self.facts()}
        lines = [f"# Research notes: {layer}", ""]
        for q in (r for r in self.current_questions() if r.layer == layer):
            lines.append(f"## {q.question}" + (" (sensitive: verify)" if q.sensitive else ""))
            if q.answered:
                for fid in q.fact_ids:
                    f = facts.get(fid)
                    if f:
                        lines.append(f"- [{f.id}] {f.claim}")
                        lines.append(f"  - source: {f.url} (read {f.fetched})")
                        lines.append(f"  - quote: \"{f.quote}\"")
            else:
                lines.append(f"- No answer found: {q.reason}")
            lines.append("")
        path = self.dir / f"{layer}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        return path


def stores_for(project: Project) -> dict[str, ResearchStore]:
    return {
        "series": ResearchStore(project.root / "research", "s", project.root),
        "book": ResearchStore(project.book_dir / "research", project.book, project.root),
    }


def _short_source(url: str) -> str:
    p = urlparse(url)
    return (p.hostname or "") + (p.path if len(p.path) < 40 else p.path[:37] + "...")


DECISIONS_PROMPT_CHARS = 1500


def decisions_text(project: Project) -> str:
    """The author's approved decisions about the world, as prompt text ('' when there are none)."""
    kind = {"invent": "invented", "extrapolate": "assumed", "bend": "changed on purpose"}
    decided, used = [], 0
    for n in approved_decisions(project):
        line = f"- ({kind[n.stance]}) {n.rule}" + (f" [applies to {', '.join(n.applies_to)}]" if n.applies_to else "")
        if used + len(line) > DECISIONS_PROMPT_CHARS:
            break
        decided.append(line)
        used += len(line) + 1
    return "The author's decisions about this world (canon, not real-world fact):\n" + "\n".join(decided) if decided else ""


def notes_for_prompt(project: Project, max_chars: int) -> str:
    """Stored facts as prompt text, newest kept first when over budget, then the author's approved decisions about the world.

    Reference data, not instructions. The decisions are shown so that planning does not contradict them (a plot that needs a
    loud laser when the author decided it is silent) and so a question already settled is not asked again.
    """
    facts: list[Fact] = []
    for store in stores_for(project).values():
        facts.extend(store.facts())
    lines: list[str] = []
    used = 0
    for f in reversed(facts):
        line = f"- [{f.id}] {f.claim} (source: {_short_source(f.url)})"
        if used + len(line) > max_chars:
            break
        lines.append(line)
        used += len(line) + 1
    text = "\n".join(reversed(lines)) if lines else "none yet"
    decided = decisions_text(project)
    if decided:
        text += "\n\n" + decided
    return text


def canonical_places(ids: list[str]) -> list[str]:
    """Chapter and scene ids in their standard spelling (b1.ch4 -> b1.ch04). Raises ValueError for anything else."""
    return list(dict.fromkeys(parse_position(i).id for i in ids))


def applies_to_scene(need: Need, scene_id: str | None) -> bool:
    """A need with no places applies everywhere; otherwise only to the chapters and scenes it names."""
    if scene_id is None or not need.applies_to:
        return True
    pos = parse_position(scene_id)
    return scene_id in need.applies_to or pos.id in need.applies_to or Position(pos.book, pos.chapter).id in need.applies_to


def approved_decisions(project: Project, scene_id: str | None = None) -> list[Need]:
    """The author's approved rules, assumptions and deviations (invent, extrapolate, bend), series first.

    With `scene_id`, only those that apply to that scene (a need raised while planning one chapter's scenes applies to
    that chapter; one raised earlier applies everywhere). These are canon: things the story invented or changed on
    purpose. A research fact says what the real world is like; a decision says what is true in this story, and the
    writer must not mistake one for the other.
    """
    out: list[Need] = []
    for store in stores_for(project).values():
        out += [n for n in store.needs() if n.status == "approved" and n.stance in ("invent", "extrapolate", "bend") and n.rule
                and applies_to_scene(n, scene_id)]
    return out


def waiting_decisions(project: Project) -> list[Need]:
    """Proposed rules, assumptions and deviations that wait for the author (a lookup needs no decision)."""
    return [n for store in stores_for(project).values() for n in store.needs()
            if n.status == "proposed" and (n.rule or n.stance == "invent")]


def _write_jsonl(path: Path, records) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(asdict(r), ensure_ascii=False) + "\n" for r in records), encoding="utf-8")


def archive_layers(project: Project, layers: list[str], stamp: str) -> dict:
    """Move the research the given layers made into `research/archive/`, so they can research from scratch (used by `redo`).

    Moved: their questions, their facts, the needs nobody decided (proposed ones and automatic lookups) and their notes
    file. Kept: every need the author decided (approved, rejected or edited in the Inbox), and the research of all other
    layers. The series-wide store is left alone when the series has more than one book: other books may cite its facts.
    Nothing is deleted; the archive file says what each record was.
    """
    from ..books import book_ids
    counts = {"questions": 0, "facts": 0, "needs": 0}
    shared = len(book_ids(project.root)) > 1
    for scope, store in stores_for(project).items():
        if scope == "series" and shared:
            continue
        facts = [f for f in store.facts() if f.layer in layers]
        questions = [q for q in store.questions() if q.layer in layers]
        log = _read_jsonl(store.needs_path, Need)
        gone_ids = {n.id for n in store.needs() if n.layer in layers and n.decided_by != "author"}
        notes = [store.dir / f"{layer}.md" for layer in layers if (store.dir / f"{layer}.md").is_file()]
        if not (facts or questions or gone_ids or notes):
            continue
        store.archive_dir.mkdir(parents=True, exist_ok=True)
        records = ([{"kind": "fact", "record": asdict(f)} for f in facts] + [{"kind": "question", "record": asdict(q)} for q in questions]
                   + [{"kind": "need", "record": asdict(n)} for n in log if n.id in gone_ids])
        if records:
            (store.archive_dir / f"{stamp}-{'+'.join(layers)}.jsonl").write_text(
                "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
        for path in notes:
            path.replace(store.archive_dir / f"{stamp}-{path.name}")
        dropped = {f.id for f in facts}
        if facts:
            _write_jsonl(store.sources_path, [f for f in store.facts() if f.layer not in layers])
        if questions:
            _write_jsonl(store.questions_path, [q for q in store.questions() if q.layer not in layers])
        if gone_ids or dropped:
            kept = [n for n in log if n.id not in gone_ids]
            for n in kept:
                n.fact_ids = [i for i in n.fact_ids if i not in dropped]  # a kept need must not point at a fact that moved
            _write_jsonl(store.needs_path, kept)
            if not store.write_needs_md():
                store.needs_md_path.unlink(missing_ok=True)
        counts["facts"] += len(facts)
        counts["questions"] += len(questions)
        counts["needs"] += len(gone_ids)
    return counts
