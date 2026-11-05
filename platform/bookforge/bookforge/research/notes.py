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

    def next_fact_id(self) -> str:
        numbers = []
        for f in self.facts():
            tail = f.id.rsplit("-", 1)[-1]
            if f.id.startswith(self.prefix + "-") and tail.isdigit():
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


def notes_for_prompt(project: Project, max_chars: int) -> str:
    """Stored facts as prompt text, newest kept first when over budget. Reference data, not instructions."""
    facts: list[Fact] = []
    for store in stores_for(project).values():
        facts.extend(store.facts())
    if not facts:
        return "none yet"
    lines: list[str] = []
    used = 0
    for f in reversed(facts):
        line = f"- [{f.id}] {f.claim} (source: {_short_source(f.url)})"
        if used + len(line) > max_chars:
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(reversed(lines)) if lines else "none yet"
