"""Assembly: the scenes' accepted text, in order, as one clean Markdown manuscript.

`books/<book>/manuscript.md`: each act is a `#` heading, each chapter a `##` heading, scenes within a chapter
are separated by `* * *`. Nothing else: no title page, page breaks or styling (those are added at export).
The whole book is assembled only when every scene is accepted and nothing is stale; `partial=True` writes
whatever is accepted to `manuscript-partial.md` so a half-finished book can be read in one piece.

A full assembly is committed, tagged `<book>-draft-N` when the text changed, and reaches the `final`
checkpoint, which is where you read the whole book (`approve final` when you are done).
"""

import logging
from dataclasses import dataclass, field

from . import scenefiles, stale, vcs
from .bible import store
from .errors import BookforgeError
from .project import Project
from .qc.mechanical import words

log = logging.getLogger("platform_bookforge.assemble")


class AssembleError(BookforgeError):
    pass


@dataclass
class Assembly:
    path: str  # relative to the series
    words: int
    scenes: int
    missing: list[str] = field(default_factory=list)  # partial only: scenes left out
    tag: str | None = None


def manuscript_path(project: Project, partial: bool = False):
    return project.book_dir / ("manuscript-partial.md" if partial else "manuscript.md")


def _blockers(project: Project, scenes) -> list[str]:
    out = []
    for s in scenes:
        status = project.state.items.get(s.id)
        status = status.status if status else "pending"
        if status != "accepted":
            out.append(f"{s.id} is {status}")
    report = stale.scan(project)
    listed = {s.id for s in scenes if s.id in " ".join(out)}
    out += [f"{st.scene} is stale ({'; '.join(st.why())[:100]})" for st in report.scenes if st.scene not in listed]
    out += [f"{p.id}: plan out of date ({p.reason})" for p in report.plan]
    return out


def build_manuscript(project: Project, partial: bool = False) -> tuple[str, int, int, list[str]]:
    scenes, chapters, acts = store.load_scenes(project), store.load_chapters(project), store.load_acts(project)
    if not scenes:
        raise AssembleError("there are no scenes to assemble (the scenes layer has to run first)")
    if not partial:
        blockers = _blockers(project, scenes)
        if blockers:
            shown = "; ".join(blockers[:8]) + (f"; and {len(blockers) - 8} more" if len(blockers) > 8 else "")
            raise AssembleError(f"the book is not finished: {shown}. Fix these (or use --partial to read what exists)")
    act_title = {a.id: a.title for a in acts}
    by_chapter: dict[str, list] = {}
    for s in scenes:
        by_chapter.setdefault(s.chapter, []).append(s)
    parts: list[str] = []
    current_act = None
    n_words = n_scenes = 0
    missing: list[str] = []
    for ch in chapters:
        texts = []
        for s in by_chapter.get(ch.id, []):
            item = project.state.items.get(s.id)
            text = scenefiles.read(scenefiles.final_path(project, s.id)) if item and item.status in ("accepted", "stale") else None
            if text is None:
                missing.append(s.id)
                continue
            texts.append(text.strip())
            n_words += len(words(text))
            n_scenes += 1
        if not texts:
            continue
        if ch.act != current_act and ch.act in act_title:
            parts.append(f"# {act_title[ch.act]}")
            current_act = ch.act
        parts.append(f"## {ch.title}")
        parts.append("\n\n* * *\n\n".join(texts))
    return "\n\n".join(parts).rstrip() + "\n", n_words, n_scenes, missing


def assemble(project: Project, partial: bool = False) -> Assembly:
    text, n_words, n_scenes, missing = build_manuscript(project, partial)
    path = manuscript_path(project, partial)
    unchanged = path.exists() and path.read_text(encoding="utf-8") == text
    path.write_text(text, encoding="utf-8")
    rel = str(path.relative_to(project.root))
    result = Assembly(rel, n_words, n_scenes, missing)
    if partial:
        return result
    project.state.reach_checkpoint("final")
    project.save_state()
    if project.config.git.commit_each_step or project.config.git.tag_checkpoints:
        vcs.commit(project.root, f"{project.book}: manuscript assembled ({n_words} words)",
                   [rel, str(project.state_path.relative_to(project.root))])
    if project.config.git.tag_checkpoints and not unchanged:
        n = 1
        while vcs.tag_exists(project.root, f"{project.book}-draft-{n}"):
            n += 1
        result.tag = f"{project.book}-draft-{n}"
        vcs.tag(project.root, result.tag, f"{project.book}: draft {n}, {n_words} words")
    return result
