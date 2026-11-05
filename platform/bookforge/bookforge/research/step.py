"""The research step: questions, search, read pages, keep facts that quote their source.

Runs after a layer's document has been written. It is best-effort: a blocked search or
an unreadable page costs that question, not the layer (unless `research.required`).
Page text is untrusted. The model only sees it as quoted data, and a fact is kept only
if the quote it gives really appears in the page, so a hostile page cannot plant facts
that its text does not contain.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlparse

from ..errors import BookforgeError
from ..prompts import render
from .hits import Hit, search_hits
from .notes import QuestionRecord, normalize_question, notes_for_prompt, stores_for

log = logging.getLogger("platform_bookforge.research")

MAX_CLAIM_CHARS = 300
MIN_QUOTE_CHARS = 15
MAX_QUOTE_CHARS = 400
MAX_FACTS_PER_PAGE = 3
MAX_QUERY_CHARS = 200
DOCUMENT_CHARS = 6000
STORY_EXCERPT_CHARS = 1500
MAX_CONTEXT_CHARS = 200
MIN_PAGE_CHARS = 40  # a page with less text than this is a failed fetch (script-only or blocked: it came back empty), not an answer
LIST_TITLE_PREFIXES = ("list of", "lists of", "index of", "outline of", "timeline of")
WINDOW_CHARS = 1500  # a long page is cut into windows this size; the ones that mention the question are read
_COMMON = frozenset("what were was the how did does and for with from that this which when where who why are their they about into over under during between".split())


@dataclass
class ResearchOutcome:
    asked: int = 0
    answered: int = 0
    facts: int = 0
    failures: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if not self.asked:
            return "research: no new questions" + (f" ({self.failures[0]})" if self.failures else "")
        text = f"research: {self.answered}/{self.asked} questions answered, {self.facts} facts"
        return text + (f" ({self.failures[0]})" if self.failures and self.answered < self.asked else "")


@dataclass
class Question:
    question: str
    query: str
    sensitive: bool
    context: str = ""  # the time, place and world an answer must fit, e.g. "England, 1880s"


def parse_json_object(text: str) -> dict | None:
    """The first JSON object in a model reply, tolerating fences and chatter."""
    text = text.strip()
    for candidate in (text, text[text.find("{"): text.rfind("}") + 1] if "{" in text else ""):
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _norm_text(s: str) -> str:
    s = (s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
          .replace("–", "-").replace("—", "-").replace(" ", " "))
    return " ".join(s.split()).casefold()


def quote_in_page(quote: str, page_text: str) -> bool:
    return _norm_text(quote) in _norm_text(page_text)


def generate_questions(ctx, already_answered: set[str], focus: str, document: str, max_questions: int) -> list[Question]:
    cfg = ctx.project.config
    prompt = render(
        "research_questions", ctx.project.root,
        layer_focus=focus, document=document[:DOCUMENT_CHARS], max_questions=str(max_questions),
        research_notes=notes_for_prompt(ctx.project, cfg.research.notes_max_chars),
        language=cfg.book.language,
    )
    reply = ctx.llm.complete(
        cfg.layers[ctx.layer].model,
        [{"role": "system", "content": render("research_system", ctx.project.root)},
         {"role": "user", "content": prompt}],
        max_tokens=1200,
    )
    data = parse_json_object(reply) or {}
    raw = data.get("questions") if isinstance(data.get("questions"), list) else []
    asked = set(already_answered)
    out: list[Question] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        question = " ".join(str(item.get("question", "")).split())
        query = " ".join(str(item.get("query", "")).split())[:MAX_QUERY_CHARS]
        key = normalize_question(question)
        if not question or not query or key in asked:
            continue
        asked.add(key)
        context = " ".join(str(item.get("setting", "")).split())[:MAX_CONTEXT_CHARS]
        out.append(Question(question, query, bool(item.get("sensitive", False)), context))
        if len(out) >= max_questions:
            break
    return out


def check_facts(ctx, question: str, context: str, story: str, facts: list[dict], dropped: list[dict] | None = None) -> list[dict]:
    """Keep only the facts that answer the question for this story's time and place.

    A fact with a real quote can still be useless: right words, wrong century. One model call judges the facts of
    a page together. An answer that cannot be read drops every fact, never keeps them.
    """
    if not facts:
        return []
    cfg = ctx.project.config
    listing = "\n".join(f"{n}. {f['claim']} (quote: \"{f['quote']}\")" for n, f in enumerate(facts, 1))
    reply = ctx.llm.complete(
        cfg.research.notes_model,
        [{"role": "system", "content": render("research_system", ctx.project.root)},
         {"role": "user", "content": render("research_check", ctx.project.root, question=question,
                                            setting=context or "not stated: use the story below",
                                            story=story[:STORY_EXCERPT_CHARS], facts=listing)}],
        max_tokens=400,
    )
    data = parse_json_object(reply) or {}
    keep = data.get("keep") if isinstance(data.get("keep"), list) else []
    wanted = {n for n in keep if isinstance(n, int) and not isinstance(n, bool)}
    if dropped is not None:
        why = {d.get("n"): " ".join(str(d.get("why", "")).split())[:200] for d in (data.get("drop") if isinstance(data.get("drop"), list) else [])
               if isinstance(d, dict)}
        dropped += [{**f, "why": why.get(n) or "no reason given"} for n, f in enumerate(facts, 1) if n not in wanted]
    return [f for n, f in enumerate(facts, 1) if n in wanted]


def relevant_excerpt(text: str, question: str, max_chars: int) -> str:
    """At most `max_chars` of the page: all of it if it fits, else the windows that mention the question's words most.

    A web page begins with menus and cookie notices, and a long article hides its answer deep inside, so the first
    characters are a poor choice. The windows are cheap to score (no model), and are kept in page order.
    """
    if len(text) <= max_chars:
        return text
    words = {w for w in re.findall(r"[a-z]{4,}", question.casefold()) if w not in _COMMON}
    windows = [text[i: i + WINDOW_CHARS] for i in range(0, len(text), WINDOW_CHARS)]
    scored = sorted(range(len(windows)), key=lambda k: (-sum(1 for w in words if w in windows[k].casefold()), k))
    keep = sorted(scored[: max(1, max_chars // WINDOW_CHARS)])
    return "\n[...]\n".join(windows[k] for k in keep)


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def era_terms(setting: str) -> list[str]:
    """Words that mark a page as being about the setting's time: "1880s", "1883", "19th century", and "victorian" for 1837-1901."""
    terms: list[str] = []
    for m in re.finditer(r"\b(1[0-9]{3}|20[0-9]{2})s?\b", setting):
        year = int(m.group(1))
        terms += [f"{year // 10 * 10}s", str(year), f"{_ordinal((year - 1) // 100 + 1)} century"]
        if 1837 <= year <= 1901:
            terms.append("victorian")
    return list(dict.fromkeys(terms))


_PLACES = {
    "england": ["england", "english", "britain", "british", "london", ".uk"], "britain": ["britain", "british", "england", "english", ".uk"],
    "scotland": ["scotland", "scottish", "scots", ".uk"], "wales": ["wales", "welsh", ".uk"], "ireland": ["ireland", "irish"],
    "france": ["france", "french", "paris"], "germany": ["germany", "german", "berlin"], "america": ["america", "american", "united states", "u.s."],
    "usa": ["america", "american", "united states", "u.s."], "canada": ["canada", "canadian"], "australia": ["australia", "australian"],
    "india": ["india", "indian"],
}
_NOT_PLACES = frozenset("any time today modern century early late mid around about the and of in".split())


def place_terms(setting: str) -> list[str]:
    """Words that mark a page as being about the setting's place: "England" also means english, british, london and .uk addresses."""
    terms: list[str] = []
    for w in re.findall(r"[A-Za-z]+", setting):
        lw = w.casefold()
        if lw in _PLACES:
            terms += _PLACES[lw]
        elif len(lw) >= 4 and lw not in _NOT_PLACES:
            terms.append(lw)
    return list(dict.fromkeys(terms))


def rank_hits(hits: list[Hit], question: str, setting: str) -> list[tuple[Hit, int]]:
    """Results ordered by how well their title, address and excerpt match the question and the setting's era and place (ties keep the
    search engine's order). Cheap, no model: the page itself is judged later; this only decides which pages are read first."""
    words = {w for w in re.findall(r"[a-z]{4,}", question.casefold()) if w not in _COMMON}
    era, places = era_terms(setting), place_terms(setting)
    scored = []
    for i, h in enumerate(hits):
        text = f"{h.title} {h.snippet} {h.url}".casefold()
        score = (min(4, sum(1 for w in words if w in text)) + (3 if any(t in text for t in era) else 0)
                 + (2 if any(t in text for t in places) else 0))
        scored.append((-score, i, h, score))
    scored.sort(key=lambda x: (x[0], x[1]))
    return [(h, score) for _, _, h, score in scored]


def skipped(url: str, skip_domains: list[str]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in skip_domains)


def diversify(hits: list[Hit]) -> list[Hit]:
    """Each site's first result first, the rest after: three pages from three sites beat three from one."""
    firsts, rest, seen = [], [], set()
    for h in hits:
        host = (urlparse(h.url).hostname or "").lower()
        (rest if host in seen else firsts).append(h)
        seen.add(host)
    return firsts + rest


def extract_facts(ctx, question: str, url: str, page_text: str, context: str = "", story: str = "",
                  stats: dict | None = None) -> tuple[list[dict], int]:
    """Facts a page states in answer to the question, each with a verbatim quote that is really in the page.

    Returns (facts kept, number of facts dropped because they do not fit the question and setting).
    """
    cfg = ctx.project.config
    shown = relevant_excerpt(page_text, f"{question} {context}", cfg.research.page_max_chars)
    reply = ctx.llm.complete(
        cfg.research.notes_model,
        [{"role": "system", "content": render("research_system", ctx.project.root)},
         {"role": "user", "content": render("research_facts", ctx.project.root, question=question, url=url,
                                            setting=context or "not stated: use the story's own time and place",
                                            page_text=shown)}],
        max_tokens=1200,
    )
    data = parse_json_object(reply) or {}
    raw = data.get("facts") if isinstance(data.get("facts"), list) else []
    if stats is not None:
        stats.update(excerpt_chars=len(shown), model_facts=len(raw), quote_rejected=0)
    facts = []
    for item in raw[:MAX_FACTS_PER_PAGE]:
        if not isinstance(item, dict):
            continue
        claim = " ".join(str(item.get("claim", "")).split())[:MAX_CLAIM_CHARS]
        quote = " ".join(str(item.get("quote", "")).split())
        if not claim or not (MIN_QUOTE_CHARS <= len(quote) <= MAX_QUOTE_CHARS):
            continue
        if not quote_in_page(quote, page_text):
            log.info("dropped a fact whose quote is not in %s", url)
            if stats is not None:
                stats["quote_rejected"] += 1
            continue
        facts.append({"claim": claim, "quote": quote})
    if not cfg.research.check_relevance:
        return facts, 0
    dropped_facts: list[dict] = []
    kept = check_facts(ctx, question, context, story, facts, dropped_facts)
    if stats is not None:
        stats["dropped_facts"] = dropped_facts
    if len(kept) < len(facts):
        log.info("dropped %d fact(s) from %s that do not fit %r", len(facts) - len(kept), url, question)
    return kept, len(facts) - len(kept)


def _list_like(hit) -> bool:
    return hit.title.casefold().startswith(LIST_TITLE_PREFIXES)


@dataclass
class PageTrace:
    url: str
    title: str
    chars: int = 0
    excerpt_chars: int = 0
    model_facts: int = 0  # facts the model reported
    quote_rejected: int = 0  # of those, dropped because the quote is not on the page
    fit_rejected: int = 0  # dropped because they do not fit the question and the setting
    kept: list[dict] = field(default_factory=list)
    dropped: list[dict] = field(default_factory=list)  # facts the relevance check dropped, each with its reason
    error: str = ""


@dataclass
class Attempt:
    """What happened to one question: the search results, each page read, the facts kept, and why none if none."""
    hits: list[Hit] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # results not read (skipped site, or already read)
    order: list[tuple[Hit, int]] = field(default_factory=list)  # the results in the order they are read, with their rank score
    pages: list[PageTrace] = field(default_factory=list)
    facts: list[tuple[Hit, dict]] = field(default_factory=list)
    reason: str = ""


def answer_question(ctx, web, q: Question, document: str, seen_urls: set[str]) -> Attempt:
    """Search for a question, read the best pages, keep the facts that quote them. Never raises: a failure is the reason."""
    cfg = ctx.project.config.research
    attempt = Attempt()
    rejected = 0
    try:
        found = search_hits(web, q.query, cfg.results_per_question)
        attempt.hits = found
        usable = []
        for h in found:
            if skipped(h.url, cfg.skip_domains):
                attempt.skipped.append(f"{h.url} (site skipped)")
            elif h.url in seen_urls:
                attempt.skipped.append(f"{h.url} (already read)")
            else:
                usable.append(h)
        ranked = rank_hits(usable, f"{q.question} {q.query}", q.context)
        ranked.sort(key=lambda x: _list_like(x[0]))  # list articles last: they are broad and rarely answer a question
        by_url = {h.url: score for h, score in ranked}
        usable = diversify([h for h, _ in ranked])
        attempt.order = [(h, by_url[h.url]) for h in usable]
        if not usable:
            attempt.reason = "every result was already read or from a skipped site"
        for hit in usable:
            if len([p for p in attempt.pages if not p.error]) >= cfg.pages_per_question:
                break
            if len(attempt.facts) >= cfg.facts_per_question and len({h.url for h, _ in attempt.facts}) >= cfg.sources_per_question:
                break  # enough facts, from enough different pages
            trace = PageTrace(hit.url, hit.title)
            try:
                page = web.fetch(hit.url)
                seen_urls.add(hit.url)
                trace.chars = len(page.text)
                if len(page.text.strip()) < MIN_PAGE_CHARS:
                    raise BookforgeError("no readable text (the page needs JavaScript, or refuses automated browsers)")
                stats: dict = {}
                found_facts, dropped = extract_facts(ctx, q.question, hit.url, page.text, q.context, document, stats)
                trace.excerpt_chars, trace.model_facts, trace.quote_rejected = (stats.get("excerpt_chars", 0), stats.get("model_facts", 0),
                                                                                stats.get("quote_rejected", 0))
                trace.fit_rejected, trace.kept, trace.dropped = dropped, found_facts, stats.get("dropped_facts", [])
                rejected += dropped
            except BookforgeError as e:
                log.warning("%s: page %s skipped: %s", ctx.layer, hit.url, e)
                trace.error = str(e)
                attempt.reason = attempt.reason or f"page {hit.url} failed: {e}"
                attempt.pages.append(trace)
                continue
            attempt.pages.append(trace)
            attempt.facts += [(hit, f) for f in found_facts]
        if not attempt.facts and not attempt.reason:
            read = len([p for p in attempt.pages if not p.error])
            failed = len(attempt.pages) - read
            attempt.reason = (f"{rejected} fact(s) found but none fit the question and the story's setting" if rejected
                              else f"no supported facts in the {read} page(s) read" + (f" ({failed} more had no readable text)" if failed else ""))
    except BookforgeError as e:
        attempt.reason = str(e)
    return attempt


def run_research(ctx, scope: str, focus: str, document: str, max_questions: int | None = None) -> ResearchOutcome:
    """Research for ctx.layer. `scope` is "series" or "book" (where the notes are kept)."""
    project, web = ctx.project, ctx.web
    cfg = project.config.research
    all_stores = stores_for(project)
    store = all_stores[scope]
    # Answered questions and pages already read count across the series and the book; unanswered ones are retried.
    answered = {normalize_question(r.question) for s in all_stores.values() for r in s.current_questions() if r.answered}
    outcome = ResearchOutcome()
    if web is None or ctx.llm is None:
        return outcome

    try:
        questions = generate_questions(ctx, answered, focus, document, max_questions or cfg.max_questions)
    except BookforgeError as e:
        outcome.failures.append(f"could not generate questions: {e}")
        log.warning("%s: %s", ctx.layer, outcome.failures[-1])
        return outcome

    seen_urls = set().union(*(s.known_urls() for s in all_stores.values()))
    today = datetime.now(timezone.utc).date().isoformat()
    for q in questions:
        outcome.asked += 1
        attempt = answer_question(ctx, web, q, document, seen_urls)
        fact_ids: list[str] = []
        for hit, f in attempt.facts:
            fact = store.add_fact(claim=f["claim"], url=hit.url, title=hit.title, fetched=today,
                                  quote=f["quote"], layer=ctx.layer, question=q.question, sensitive=q.sensitive)
            fact_ids.append(fact.id)
        reason = "" if fact_ids else attempt.reason
        if fact_ids:
            outcome.answered += 1
            outcome.facts += len(fact_ids)
        else:
            outcome.failures.append(reason)
            log.warning("%s: question not answered (%s): %s", ctx.layer, q.question, reason)
        store.add_question(QuestionRecord(layer=ctx.layer, question=q.question, query=q.query,
                                          answered=bool(fact_ids), fact_ids=fact_ids, reason=reason, sensitive=q.sensitive,
                                          context=q.context))

    if outcome.asked:
        outcome.files = [store.rel(store.sources_path), store.rel(store.questions_path),
                         store.rel(store.write_notes(ctx.layer))]
        outcome.files = [f for f in outcome.files if (project.root / f).exists()]
    return outcome
