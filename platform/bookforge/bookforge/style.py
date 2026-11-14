"""The suggested style guide.

When the synopsis is accepted and the series has no style guide, Bookforge suggests one (`style/guide.md`), for the author to edit at the
direction checkpoint:

1. the planner model names the genre, the intended style (from the north stars) and a few successful published novels of the same genre;
2. web searches look for what critics, readers and writing guides say about the PROSE STYLE of those books and the genre; the pages are read
   and every observation must carry a short verbatim quote from its page (the same rule as for research facts);
3. a title counts as checked only if a page that was read names it; only checked titles may appear in the guide;
4. the model writes the guide in its own words from the findings. A guide that copies a run of twelve words from a page is refused: the
   style of successful books is learned from, never copied.

Without a web client the guide is written from the north stars and the model's knowledge of the genre, with no titles named.
A guide you already have is never overwritten: the suggestion goes to `style/guide.suggested.md` (unless you ask to replace it, which first
commits what is there). What was found and where from is kept in `style/suggestion.json`.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import scenefiles, vcs
from .ask import ask_until_valid, word_count
from .errors import BookforgeError
from .prompts import render
from .qc.support import ask_json, messages
from .research.hits import search_hits
from .research.step import parse_json_object, quote_in_page, relevant_excerpt, skipped
from .validators.text import shingles

log = logging.getLogger("platform_bookforge.style")

SECTIONS = ("Voice and point of view", "Sentence rhythm", "Diction", "Dialogue", "Description and sensory detail", "Pacing and scene shape", "Tone", "Never")
COPY_RUN = 12  # consecutive words shared with a source that make a guide a copy
PAGE_CHARS = 7000
MAX_PAGES = 10
MAX_NOTES_PER_PAGE = 6
GUIDE_PATH = "style/guide.md"
SUGGESTED_PATH = "style/guide.suggested.md"
SUGGESTION_META = "style/suggestion.json"


def guide_is_empty(project) -> bool:
    """True when the series has no style guide of its own: the file is missing, empty or only its placeholder heading."""
    text = scenefiles.read(project.root / GUIDE_PATH) or ""
    return all(not line.strip() or line.lstrip().startswith("#") for line in text.splitlines())


@dataclass
class Findings:
    genre: str = ""
    subgenres: list[str] = field(default_factory=list)
    intended_style: str = ""
    comparables: list[dict] = field(default_factory=list)  # as named by the model: title, author, why
    queries: list[str] = field(default_factory=list)
    observations: list[dict] = field(default_factory=list)  # observation, about, quote, url
    sources: list[dict] = field(default_factory=list)  # url, title
    verified: list[dict] = field(default_factory=list)  # comparables a page that was read names: + sources
    pages: dict[str, str] = field(default_factory=dict)  # url -> text, kept to refuse a guide that copies them
    web: bool = False
    problems: list[str] = field(default_factory=list)  # what could not be done (searches that failed...), told to the author


def _north_stars(project) -> dict[str, str]:
    read = lambda rel: (project.root / rel).read_text(encoding="utf-8").strip()  # noqa: E731
    return {"series_north_star": read("north-star.md"), "book_north_star": read(f"books/{project.book}/north-star.md"),
            "synopsis": read(f"books/{project.book}/synopsis.md")}


def _fixed(project) -> dict[str, str]:
    cfg = project.config.book
    return {"pov": cfg.pov, "tense": cfg.tense, "language": cfg.language}


def _check_identify(data: dict) -> list[str]:
    problems = []
    if not str(data.get("genre", "")).strip():
        problems.append('"genre" is missing')
    comps = data.get("comparables")
    if not isinstance(comps, list) or not comps or not all(isinstance(c, dict) and str(c.get("title", "")).strip() and str(c.get("author", "")).strip() for c in comps):
        problems.append('"comparables" must be a non-empty list of {"title", "author", "why"}')
    queries = data.get("queries")
    if not isinstance(queries, list) or not queries or not all(isinstance(q, str) and q.strip() for q in queries):
        problems.append('"queries" must be a non-empty list of search queries')
    return problems


def identify(ctx) -> Findings:
    project, cfg = ctx.project, ctx.project.config.style
    data = ask_json(ctx, "style identify", "critic", "style_identify", _check_identify, max_tokens=900, **_north_stars(project), **_fixed(project),
                    max_titles=str(cfg.comparables), max_queries=str(cfg.queries))
    f = Findings(genre=str(data["genre"]).strip(), subgenres=[str(s) for s in data.get("subgenres") or []][:3],
                 intended_style=str(data.get("intended_style", "")).strip())
    f.comparables = [{"title": str(c["title"]).strip(), "author": str(c["author"]).strip(), "why": str(c.get("why", "")).strip()} for c in data["comparables"]][:cfg.comparables]
    f.queries = [" ".join(q.split()) for q in data["queries"]][:cfg.queries]
    return f


def _check_notes(data: dict) -> list[str]:
    if not isinstance(data.get("observations"), list):
        return ['"observations" must be a list']
    bad = [i for i, o in enumerate(data["observations"]) if not isinstance(o, dict) or not str(o.get("observation", "")).strip() or not str(o.get("quote", "")).strip()]
    return [f"observations[{i}] needs an observation and a quote" for i in bad]


def research(ctx, web, f: Findings) -> None:
    """Search, read, and keep the observations a page can back with a quote. Never raises: what failed is listed in `f.problems`."""
    project = ctx.project
    cfg, rcfg = project.config.style, project.config.research
    f.web = True
    titles = "\n".join(f"- {c['title']} by {c['author']}" for c in f.comparables) + f"\n- the genre: {f.genre}"
    seen: set[str] = set()
    named: dict[str, set[str]] = {c["title"]: set() for c in f.comparables}
    for query in f.queries:
        if len(f.pages) >= MAX_PAGES:
            break
        try:
            hits = search_hits(web, query, rcfg.results_per_question)
        except BookforgeError as e:
            f.problems.append(f"search '{query}': {str(e)[:120]}")
            continue
        taken = 0
        for hit in hits:
            if taken >= cfg.pages_per_query or len(f.pages) >= MAX_PAGES:
                break
            if hit.url in seen or skipped(hit.url, rcfg.skip_domains):
                continue
            seen.add(hit.url)
            try:
                page = web.fetch(hit.url)
            except BookforgeError as e:
                f.problems.append(f"page {hit.url}: {str(e)[:100]}")
                continue
            if len(page.text.strip()) < 400:
                continue
            taken += 1
            f.pages[hit.url] = page.text
            f.sources.append({"url": hit.url, "title": hit.title})
            for c in f.comparables:  # a title is checked when a page that was read names it
                if c["title"].casefold() in page.text.casefold():
                    named[c["title"]].add(hit.url)
            excerpt = relevant_excerpt(page.text, f"{query} prose style voice rhythm dialogue pacing description", PAGE_CHARS)
            try:
                data = ask_json(ctx, f"style notes {hit.url}", rcfg.notes_model, "style_notes", _check_notes, max_tokens=1200,
                                titles=titles, url=hit.url, page=excerpt, max_notes=str(MAX_NOTES_PER_PAGE))
            except Exception as e:  # a page the model cannot read is skipped, not fatal
                f.problems.append(f"notes from {hit.url}: {str(e)[:100]}")
                continue
            for o in data["observations"][:MAX_NOTES_PER_PAGE]:
                if quote_in_page(str(o["quote"]), page.text):
                    f.observations.append({"observation": str(o["observation"]).strip(), "about": str(o.get("about", "")).strip(), "quote": str(o["quote"]).strip(), "url": hit.url})
    f.verified = [{**c, "sources": sorted(named[c["title"]])} for c in f.comparables if named[c["title"]]]


def _observations_text(f: Findings) -> str:
    if not f.observations:
        return "(nothing found on the web: rely on the north stars and what is known of the genre's conventions)"
    return "\n".join(f"- {o['observation']} (about {o['about'] or 'the genre'})" for o in f.observations[:30])


def _titles_text(f: Findings) -> str:
    return "\n".join(f"- {c['title']} by {c['author']}: {c['why']}" for c in f.verified) or "none: do not name any book"


def validate_guide(text: str, f: Findings, words: tuple[int, int]) -> list[str]:
    problems = []
    headings = [m.group(1).strip().casefold() for m in re.finditer(r"^##\s+(.+?)\s*#*\s*$", text, re.M)]
    for s in SECTIONS:
        if s.casefold() not in headings:
            problems.append(f"missing the section '## {s}'")
    if f.verified:
        if "touchstones" not in headings:
            problems.append("missing the section '## Touchstones'")
    elif "touchstones" in headings:
        problems.append("remove '## Touchstones': no title was checked on the web, so none may be named")
    n = word_count(text)
    if n < words[0] // 2 or n > words[1] * 1.3:
        problems.append(f"{n} words; the guide must be between {words[0]} and {words[1]}")
    low = text.casefold()
    checked = {v["title"] for v in f.verified}
    for c in f.comparables:
        if c["title"] not in checked and len(c["title"]) > 3 and c["title"].casefold() in low:
            problems.append(f"'{c['title']}' was not checked on the web: do not name it")
    mine = shingles(text, COPY_RUN)
    if mine:
        for url, page in f.pages.items():
            if mine & shingles(page, COPY_RUN):
                problems.append(f"the guide copies a run of {COPY_RUN} or more words from {url}: describe the style in your own words")
                break
    return problems


def draft(ctx, f: Findings) -> str:
    project = ctx.project
    cfg = project.config.style
    banned = scenefiles.read(project.root / project.config.qc.banned_phrases) or ""
    banned = "\n".join(l for l in banned.splitlines() if l.strip() and not l.lstrip().startswith("#"))[:1500] or "none yet"
    genre = f"{f.genre}" + (f" ({', '.join(f.subgenres)})" if f.subgenres else "") + (f". Intended style: {f.intended_style}" if f.intended_style else "")
    touch = "## Touchstones   (successful titles to learn the register from, each with one line on what to take from it; not to imitate)" if f.verified else ""
    values = {**_north_stars(project), **_fixed(project), "genre": genre, "observations": _observations_text(f), "titles": _titles_text(f),
              "banned": banned, "words_min": str(cfg.words[0]), "words_max": str(cfg.words[1]), "touchstones_section": touch}
    msgs = [{"role": "system", "content": render("system", project.root, **{"language": project.config.book.language})},
            {"role": "user", "content": render("style_guide", project.root, **values)}]
    text = ask_until_valid(ctx, "style guide", "critic", msgs, lambda t: validate_guide(t, f, cfg.words), {"max_tokens": 3000}, strip_preamble=True)
    return text.strip() + "\n"


@dataclass
class Suggestion:
    path: str  # where the guide was written, relative to the series
    words: int
    verified: list[str]
    web: bool
    problems: list[str]
    replaced_existing: bool = False


def suggest_style_guide(ctx, web=None, replace: bool = False) -> Suggestion:
    """Make a suggested guide. Writes style/guide.md if the series has none; else style/guide.suggested.md, or (replace) guide.md after committing the old one."""
    project = ctx.project
    if ctx.llm is None:
        raise BookforgeError("no model client available")
    f = identify(ctx)
    if web is not None and project.config.research.enabled:
        research(ctx, web, f)
    text = draft(ctx, f)
    empty = guide_is_empty(project)
    target = GUIDE_PATH if (empty or replace) else SUGGESTED_PATH
    if replace and not empty and project.config.git.commit_each_step:
        vcs.commit(project.root, f"{project.book}: style guide as it was, before a suggestion replaces it", [project.root / GUIDE_PATH])
    path = project.root / target
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    meta = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "file": target, "genre": f.genre, "subgenres": f.subgenres, "intended_style": f.intended_style,
            "web": f.web, "verified_titles": f.verified, "unchecked_titles": [c["title"] for c in f.comparables if c["title"] not in {v["title"] for v in f.verified}],
            "observations": f.observations, "sources": f.sources, "problems": f.problems, "words": word_count(text)}
    (project.root / SUGGESTION_META).write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if project.config.git.commit_each_step:
        vcs.commit(project.root, f"{project.book}: suggested style guide ({f.genre})", [path, project.root / SUGGESTION_META])
    return Suggestion(target, meta["words"], [v["title"] for v in f.verified], f.web, f.problems, replaced_existing=replace and not empty)


def load_suggestion(project) -> dict | None:
    try:
        return json.loads((project.root / SUGGESTION_META).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def maybe_suggest(ctx) -> tuple[list[str], str]:
    """The automatic step after the synopsis: (files written, a note). Never raises: a guide that could not be made is a note, not a failure."""
    project = ctx.project
    if not project.config.style.auto_suggest or not guide_is_empty(project) or ctx.llm is None:
        return [], ""
    try:
        s = suggest_style_guide(ctx, ctx.web)
    except Exception as e:  # the pipeline goes on without a guide, as it always could
        log.warning("style guide suggestion failed: %s", e)
        return [], f"no style guide could be suggested ({str(e)[:120]}); write one in the Documents tab or try Suggest there"
    note = f"style guide suggested ({s.words} words" + (f", learned from {', '.join(s.verified)}" if s.verified else ", no titles checked on the web") + "); edit it before you approve"
    return [s.path, SUGGESTION_META], note
