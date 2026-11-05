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

from ..errors import BookforgeError
from ..prompts import render
from .hits import search_hits
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
LIST_TITLE_PREFIXES = ("list of", "lists of", "index of", "outline of", "timeline of")


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


def check_facts(ctx, question: str, context: str, story: str, facts: list[dict]) -> list[dict]:
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
    return [f for n, f in enumerate(facts, 1) if n in wanted]


def extract_facts(ctx, question: str, url: str, page_text: str, context: str = "", story: str = "") -> tuple[list[dict], int]:
    """Facts a page states in answer to the question, each with a verbatim quote that is really in the page.

    Returns (facts kept, number of facts dropped because they do not fit the question and setting).
    """
    cfg = ctx.project.config
    reply = ctx.llm.complete(
        cfg.research.notes_model,
        [{"role": "system", "content": render("research_system", ctx.project.root)},
         {"role": "user", "content": render("research_facts", ctx.project.root, question=question, url=url,
                                            setting=context or "not stated: use the story's own time and place",
                                            page_text=page_text[: cfg.research.page_max_chars])}],
        max_tokens=1200,
    )
    data = parse_json_object(reply) or {}
    raw = data.get("facts") if isinstance(data.get("facts"), list) else []
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
            continue
        facts.append({"claim": claim, "quote": quote})
    if not cfg.research.check_relevance:
        return facts, 0
    kept = check_facts(ctx, question, context, story, facts)
    if len(kept) < len(facts):
        log.info("dropped %d fact(s) from %s that do not fit %r", len(facts) - len(kept), url, question)
    return kept, len(facts) - len(kept)


def _list_like(hit) -> bool:
    return hit.title.casefold().startswith(LIST_TITLE_PREFIXES)


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
        fact_ids: list[str] = []
        reason = ""
        rejected = 0
        try:
            hits = [h for h in search_hits(web, q.query, cfg.results_per_question) if h.url not in seen_urls]
            hits.sort(key=_list_like)  # list articles last: they are broad and rarely answer a question
            if not hits:
                reason = "every result was already read"
            pages_read = 0
            for hit in hits:
                if pages_read >= cfg.pages_per_question:
                    break
                try:
                    page = web.fetch(hit.url)
                    seen_urls.add(hit.url)
                    pages_read += 1
                    found, dropped = extract_facts(ctx, q.question, hit.url, page.text, q.context, document)
                    rejected += dropped
                except BookforgeError as e:
                    log.warning("%s: page %s skipped: %s", ctx.layer, hit.url, e)
                    reason = reason or f"page {hit.url} failed: {e}"
                    continue
                for f in found:
                    fact = store.add_fact(claim=f["claim"], url=hit.url, title=hit.title, fetched=today,
                                          quote=f["quote"], layer=ctx.layer, question=q.question, sensitive=q.sensitive)
                    fact_ids.append(fact.id)
            if not fact_ids and not reason:
                reason = (f"{rejected} fact(s) found but none fit the question and the story's setting"
                          if rejected else f"no supported facts in the {pages_read} page(s) read")
        except BookforgeError as e:
            reason = str(e)
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
