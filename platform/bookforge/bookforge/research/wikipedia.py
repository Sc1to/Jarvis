"""Wikipedia as the research source, reached through the platform web tool like any other page.

Search-engine result pages (DuckDuckGo, Bing, Brave) answer a headless browser with a block page or an
empty page, so they cannot be used. Wikipedia's API is meant for programs: a search request returns the
matching article titles as JSON, and an extracts request returns an article as plain text. Both are
ordinary pages to the web tool, so its logging, the URL checks and the retries all still apply.

A fact's source URL is the article's normal address (https://en.wikipedia.org/wiki/Title). The quote that
backs the fact is checked against the plain text the API returned for that article.

Limits: only what Wikipedia covers; one article is cut off at what the web tool returns (50,000
characters of JSON), and the model is shown the first `research.page_max_chars` of it.
"""

import json
import re
from urllib.parse import quote, quote_plus, unquote, urlparse

from .search import WebClient, WebError, WebResult

_TITLE_SAFE = "()_,'-:!$*;=@"


def api_url(language: str) -> str:
    return f"https://{language}.wikipedia.org/w/api.php"


def page_url(language: str, title: str) -> str:
    return f"https://{language}.wikipedia.org/wiki/" + quote(title.replace(" ", "_"), safe=_TITLE_SAFE)


def wiki_title(url: str) -> tuple[str, str] | None:
    """(language, title) if the URL is a Wikipedia article address, else None."""
    p = urlparse(url)
    m = re.match(r"^([a-z]{2,8}(?:-[a-z0-9]+)?)\.wikipedia\.org$", (p.hostname or "").lower())
    if not m or not p.path.startswith("/wiki/") or len(p.path) <= len("/wiki/"):
        return None
    return m.group(1), unquote(p.path[len("/wiki/"):]).replace("_", " ")


def _json(raw: str, what: str) -> dict:
    try:
        data = json.loads(raw)
    except ValueError:
        preview = " ".join(raw.split())[:140]
        raise WebError(f"Wikipedia {what} did not return JSON (rate limited or blocked?). It said: {preview!r}") from None
    if not isinstance(data, dict):
        raise WebError(f"Wikipedia {what} returned an unexpected reply")
    if "error" in data:
        raise WebError(f"Wikipedia {what} failed: {data['error'].get('info', data['error'])}")
    return data


def _truncated_extract(raw: str) -> str | None:
    """The article text from a JSON reply that the web tool cut off in the middle of the "extract" string."""
    m = re.search(r'"extract":"', raw)
    if not m:
        return None
    body = raw[m.end():]
    end = re.search(r'(?<!\\)(?:\\\\)*"', body)
    body = body[: end.end() - 1] if end else body
    body = re.sub(r"\\u[0-9a-fA-F]{0,3}$", "", body)
    body = re.sub(r"(?<!\\)\\$", "", body)
    try:
        return json.loads('"' + body + '"')
    except ValueError:
        return None


def article_text(raw: str, title: str) -> str:
    try:
        data = json.loads(raw)
    except ValueError:
        text = _truncated_extract(raw)
        if text:
            return text
        return _json(raw, f"article '{title}'") and ""  # raises with a useful message
    if isinstance(data, dict) and "error" in data:
        _json(raw, f"article '{title}'")
    pages = (data.get("query") or {}).get("pages") or []
    page = pages[0] if pages else {}
    if page.get("missing"):
        raise WebError(f"Wikipedia has no article called '{title}'")
    text = page.get("extract") or ""
    if not text.strip():
        raise WebError(f"Wikipedia returned no text for '{title}'")
    return text


class WikipediaWebClient:
    """A WebClient whose search results and article text come from Wikipedia. Other URLs pass straight through."""

    def __init__(self, inner: WebClient, language: str = "en", results: int = 5):
        self._inner = inner
        self._lang = language
        self._results = max(1, results)

    def search(self, query: str) -> WebResult:
        query = " ".join(query.split())
        if not query:
            raise WebError("empty search query")
        url = (f"{api_url(self._lang)}?action=query&list=search&srsearch={quote_plus(query)}"
               f"&srlimit={self._results}&format=json&formatversion=2")
        raw = self._inner.fetch(url)
        data = _json(raw.text, "search")
        hits = (data.get("query") or {}).get("search") or []
        links = [{"text": h["title"], "href": page_url(self._lang, h["title"])} for h in hits if isinstance(h, dict) and h.get("title")]
        return WebResult("search", query, raw.text, links)

    def fetch(self, url: str) -> WebResult:
        parsed = wiki_title(url)
        if parsed is None:
            return self._inner.fetch(url)
        lang, title = parsed
        api = (f"{api_url(lang)}?action=query&prop=extracts&explaintext=1&exsectionformat=plain&redirects=1"
               f"&format=json&formatversion=2&titles={quote_plus(title)}")
        raw = self._inner.fetch(api)
        return WebResult("fetch", url, article_text(raw.text, title))
