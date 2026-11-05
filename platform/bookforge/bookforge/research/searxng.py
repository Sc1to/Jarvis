"""SearXNG as the research search engine: your own metasearch instance, so questions reach the real web.

Search engines answer a headless browser with a block page, so bookforge does not ask them directly. SearXNG, running
on this machine (docs/STACK.md), asks several engines at once and returns their results as JSON. The request goes through
the platform web tool like any other page (so it is logged with the rest of the internet access), with one narrow
exception: the configured SearXNG address, which the URL check would otherwise refuse as a local address. Result pages
are fetched through the web tool as usual, and Wikipedia articles through Wikipedia's text API.

If every engine behind SearXNG fails or refuses, the error names them (SearXNG reports which engines did not answer),
so a block is never mistaken for "nothing found".
"""

import json
import logging
from urllib.parse import quote_plus, urlparse

import httpx

from .search import WebClient, WebError, WebResult
from .wikipedia import WikipediaWebClient, wiki_title

log = logging.getLogger("platform_bookforge.searxng")


def origin_of(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}".lower()


def _unresponsive(data: dict) -> str:
    bad = data.get("unresponsive_engines") or []
    parts = []
    for item in bad:
        if isinstance(item, (list, tuple)) and item:
            parts.append(f"{item[0]} ({item[1]})" if len(item) > 1 else str(item[0]))
    return ", ".join(parts)


def _salvage(raw: str) -> list[dict]:
    """The complete result objects in a JSON reply the web tool cut off (it keeps at most 50,000 characters)."""
    start = raw.find('"results"')
    bracket = raw.find("[", start) if start >= 0 else -1
    if bracket < 0:
        return []
    decoder, i, out = json.JSONDecoder(), bracket + 1, []
    while i < len(raw):
        while i < len(raw) and raw[i] in " \n\r\t,":
            i += 1
        if i >= len(raw) or raw[i] != "{":
            break
        try:
            obj, i = decoder.raw_decode(raw, i)
        except ValueError:
            break
        if isinstance(obj, dict):
            out.append(obj)
    return out


def parse_results(raw: str, query: str) -> tuple[list[dict], str]:
    """(results, engines that did not answer). Raises WebError with the reason if there is nothing usable."""
    try:
        data = json.loads(raw)
        results = data.get("results") if isinstance(data, dict) else None
        failed = _unresponsive(data) if isinstance(data, dict) else ""
    except ValueError:
        salvaged = _salvage(raw)
        if not salvaged:
            preview = " ".join(raw.split())[:140]
            raise WebError("SearXNG did not answer with JSON. Is `json` listed under search.formats in its settings.yml "
                           f"(see docs/STACK.md)? It said: {preview!r}") from None
        return salvaged, ""
    if not isinstance(results, list) or not results:
        raise WebError(f"SearXNG found nothing for {query!r}" + (f"; engines that did not answer: {failed}" if failed else
                                                                 " (try other words, or check that its engines are enabled)"))
    return results, failed


class SearxngWebClient:
    """A WebClient whose search results come from SearXNG. Pages come from the inner client (Wikipedia via its text API)."""

    source_name = "searxng"

    def __init__(self, inner: WebClient, base_url: str, language: str = "en", results: int = 8, wikipedia_language: str = "en"):
        self._inner = inner
        self._base = base_url.rstrip("/")
        self._language = language
        self._results = max(1, results)
        self._wiki = WikipediaWebClient(inner, wikipedia_language)

    def search(self, query: str) -> WebResult:
        query = " ".join(query.split())
        if not query:
            raise WebError("empty search query")
        url = f"{self._base}/search?q={quote_plus(query)}&format=json&language={quote_plus(self._language)}&safesearch=0"
        raw = self._inner.fetch(url)
        results, failed = parse_results(raw.text, query)
        links = []
        for r in results:
            if isinstance(r, dict) and isinstance(r.get("url"), str) and r["url"]:
                links.append({"text": " ".join(str(r.get("title") or "").split())[:200], "href": r["url"]})
        if failed:
            log.info("searxng: %d result(s) for %r; engines that did not answer: %s", len(links), query, failed)
        return WebResult("search", query, raw.text, links[: self._results * 3])

    def fetch(self, url: str) -> WebResult:
        if wiki_title(url) is not None:
            return self._wiki.fetch(url)
        return self._inner.fetch(url)


def probe(base_url: str, timeout: float = 3.0, transport: httpx.BaseTransport | None = None) -> dict:
    """What is at the SearXNG address: reachable, answering JSON, and which engines respond to a test search.

    A direct call to a service on this machine (like the model endpoints in `doctor`), not internet access.
    """
    out = {"reachable": False, "json": False, "results": 0, "failed_engines": "", "error": ""}
    try:
        with httpx.Client(timeout=httpx.Timeout(timeout, read=max(timeout, 20.0)), transport=transport) as client:
            resp = client.get(f"{base_url.rstrip('/')}/search", params={"q": "history", "format": "json"})
    except httpx.HTTPError as e:
        out["error"] = f"cannot reach {base_url}: {e}"
        return out
    out["reachable"] = True
    if resp.status_code == 403:
        out["error"] = "SearXNG refused the JSON format (HTTP 403): add `json` under search.formats in its settings.yml"
        return out
    if resp.status_code != 200:
        out["error"] = f"SearXNG answered HTTP {resp.status_code}"
        return out
    try:
        data = resp.json()
    except ValueError:
        out["error"] = "SearXNG did not answer with JSON: add `json` under search.formats in its settings.yml"
        return out
    out["json"] = True
    out["results"] = len(data.get("results") or []) if isinstance(data, dict) else 0
    out["failed_engines"] = _unresponsive(data) if isinstance(data, dict) else ""
    return out
