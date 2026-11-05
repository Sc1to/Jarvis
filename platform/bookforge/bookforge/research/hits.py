"""Turn a search results page into a list of pages worth reading.

The web tool returns the results page as text plus the page's links. The result
links on a DuckDuckGo page point at a redirect (duckduckgo.com/l/?uddg=<target>),
which is unwrapped here. A page with no usable links is reported as blocked or
empty, so a search engine's block page is never mistaken for an answer.
"""

from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from .search import WebClient, WebError

SKIP_EXTENSIONS = (".pdf", ".zip", ".gz", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".mp3", ".mp4",
                   ".exe", ".dmg", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx")
SEARCH_HOSTS = ("duckduckgo.com", "duck.co")


@dataclass
class Hit:
    url: str
    title: str


def _unwrap(href: str) -> str | None:
    """The page a result link leads to, or None if it is not a result link."""
    parsed = urlparse(href.strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    host = parsed.hostname.lower()
    if any(host == h or host.endswith("." + h) for h in SEARCH_HOSTS):
        target = parse_qs(parsed.query).get("uddg", [None])[0] if parsed.path in ("/l", "/l/") else None
        if not target:
            return None
        parsed = urlparse(target)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return None
        if any(parsed.hostname.lower().endswith(h) for h in SEARCH_HOSTS):
            return None
    if parsed.path.lower().endswith(SKIP_EXTENSIONS):
        return None
    return parsed._replace(fragment="").geturl()


def extract_hits(links: list[dict], limit: int) -> list[Hit]:
    hits: list[Hit] = []
    seen: set[str] = set()
    for link in links:
        url = _unwrap(str(link.get("href", "")))
        if url is None or url in seen:
            continue
        seen.add(url)
        hits.append(Hit(url=url, title=" ".join(str(link.get("text", "")).split())[:200]))
        if len(hits) >= limit:
            break
    return hits


def search_hits(web: WebClient, query: str, limit: int) -> list[Hit]:
    result = web.search(query)
    hits = extract_hits(result.links, limit)
    if not hits:
        preview = " ".join(result.text.split())[:120]
        raise WebError(f"search for {query!r} returned no result links (blocked or empty). Page started: {preview!r}")
    return hits
