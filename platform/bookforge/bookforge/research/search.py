"""Web access for research, always through the platform Playwright web tool.

Bookforge never makes direct HTTP calls to the internet (CLAUDE.md, Security).
This wrapper adds what the tool itself does not: URL checks (http/https only, no
private or loopback hosts), query encoding, retries, and call logging.

"""

import ipaddress
import logging
import socket
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol
from urllib.parse import quote_plus, urlparse

from ..calllog import CallLog
from ..errors import BookforgeError

log = logging.getLogger("platform_bookforge.web")

AGENT_NAME = "platform_bookforge_research"
PLATFORM_DIR = Path(__file__).resolve().parents[3]  # platform/
MAX_QUERY_CHARS = 300


class WebError(BookforgeError):
    pass


@dataclass
class WebResult:
    kind: str  # "search" | "fetch"
    target: str  # the query or the URL
    text: str
    links: list[dict] = field(default_factory=list)  # [{"text", "href"}] found on the page


class WebClient(Protocol):
    def search(self, query: str) -> WebResult: ...
    def fetch(self, url: str) -> WebResult: ...


@dataclass
class FakeWebClient:
    """Scripted pages for tests. Records every call."""

    searches: dict[str, str] = field(default_factory=dict)  # query -> results page text
    pages: dict[str, str] = field(default_factory=dict)  # url -> page text
    links: dict[str, list[dict]] = field(default_factory=dict)  # query or url -> links on that page
    calls: list[tuple[str, str]] = field(default_factory=list)

    def search(self, query: str) -> WebResult:
        self.calls.append(("search", query))
        if query not in self.searches:
            raise WebError(f"no scripted search result for {query!r}")
        return WebResult("search", query, self.searches[query], list(self.links.get(query, [])))

    def fetch(self, url: str) -> WebResult:
        self.calls.append(("fetch", url))
        if url not in self.pages:
            raise WebError(f"no scripted page for {url!r}")
        return WebResult("fetch", url, self.pages[url], list(self.links.get(url, [])))


def load_web_tool_class():
    """Import tools.web_tool.WebTool, adding platform/ to the import path if needed."""
    try:
        from tools.web_tool import WebTool
    except ImportError:
        if str(PLATFORM_DIR) not in sys.path:
            sys.path.append(str(PLATFORM_DIR))  # appended, so it can never shadow installed packages
        try:
            from tools.web_tool import WebTool
        except ImportError as e:
            raise WebError(f"platform web tool not importable (looked in {PLATFORM_DIR}): {e}") from e
    return WebTool


def playwright_installed() -> bool:
    try:
        import playwright.async_api  # noqa: F401
        return True
    except ImportError:
        return False


def check_url(url: str, resolver: Callable = socket.getaddrinfo) -> str:
    """Allow only public http(s) URLs. Raises WebError otherwise.

    Pages found during research are untrusted; without this a crafted link could
    make the browser read local files or the platform's own services (admin panel,
    Ollama, colibri). Resolution happens here and again in the browser, so a
    hostile DNS server could still answer differently the second time.
    """
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise WebError(f"only http and https URLs are allowed: {url!r}")
    host = parsed.hostname
    if not host:
        raise WebError(f"URL has no host: {url!r}")
    try:
        infos = resolver(host, None)
    except OSError as e:
        raise WebError(f"cannot resolve {host}: {e}") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if not ip.is_global:
            raise WebError(f"refusing to fetch non-public address {ip} ({host})")
    return url.strip()


class PlaywrightWebClient:
    source_name = "duckduckgo"  # what raw use of this client means: search-engine result pages

    def __init__(
        self,
        call_log: CallLog | None = None,
        session_id: str | None = None,
        tool=None,
        attempts: int = 2,
        backoff_seconds: float = 2.0,
        sleep: Callable[[float], None] = time.sleep,
        resolver: Callable = socket.getaddrinfo,
        allowed_origins: frozenset[str] | set[str] | None = None,
    ):
        # Origins ("http://127.0.0.1:8060") that may be fetched although they are local: the configured SearXNG only.
        self._allowed = frozenset(o.lower().rstrip("/") for o in (allowed_origins or ()))
        self._log = call_log or CallLog(None)
        self._session_id = session_id
        self._tool = tool
        self._attempts = max(1, attempts)
        self._backoff = backoff_seconds
        self._sleep = sleep
        self._resolver = resolver

    def search(self, query: str) -> WebResult:
        query = " ".join(query.split())
        if not query:
            raise WebError("empty search query")
        if len(query) > MAX_QUERY_CHARS:
            raise WebError(f"search query too long ({len(query)} > {MAX_QUERY_CHARS} chars)")
        # The tool inserts the query into a URL without encoding it.
        return self._call("search", query, {"op": "search", "query": quote_plus(query)})

    def fetch(self, url: str) -> WebResult:
        p = urlparse(url.strip())
        if p.scheme in ("http", "https") and f"{p.scheme}://{p.netloc}".lower() in self._allowed:
            url = url.strip()  # the configured search service: allowed although it is a local address
        else:
            url = check_url(url, self._resolver)
        return self._call("fetch", url, {"op": "fetch_page", "url": url})

    def _tool_instance(self):
        if self._tool is None:
            if not playwright_installed():
                raise WebError("playwright is not installed in this environment (pip install playwright; playwright install chromium)")
            self._tool = load_web_tool_class()(session_id=self._session_id, agent_name=AGENT_NAME)
        return self._tool

    def _call(self, kind: str, target: str, params: dict) -> WebResult:
        tool = self._tool_instance()
        started = time.monotonic()
        error = "unknown error"
        for attempt in range(1, self._attempts + 1):
            result = tool.execute(params)
            if result.success:
                self._record(kind, target, started, attempt, chars=len(result.output))
                links = (result.metadata or {}).get("links")
                return WebResult(kind, target, result.output, links if isinstance(links, list) else [])
            error = result.error or error
            if attempt < self._attempts:
                log.warning("web %s failed (%s); retrying", kind, error)
                self._sleep(self._backoff * 2 ** (attempt - 1))
        self._record(kind, target, started, self._attempts, error=error)
        raise WebError(f"web {kind} failed after {self._attempts} attempts: {error}")

    def _record(self, kind: str, target: str, started: float, attempts: int, **extra) -> None:
        self._log.write({"kind": "web", "op": kind, "target": target, "attempts": attempts,
                         "duration_seconds": round(time.monotonic() - started, 3), "ok": "error" not in extra, **extra})


def make_web_client(research, base: PlaywrightWebClient | None = None, **kw) -> WebClient:
    """The client for `research.source`.

    searxng: results from your SearXNG instance. wikipedia: Wikipedia's API. auto: SearXNG if it answers, otherwise
    Wikipedia (and a warning, so a missing search service is not silent). duckduckgo: raw search-engine pages.
    """
    source = research.source
    if source in ("auto", "searxng"):
        from .searxng import SearxngWebClient, origin_of, probe  # imported here: searxng.py imports this module
        if source == "auto":
            status = probe(research.searxng_url)
            if not (status["reachable"] and status["json"]):
                log.warning("research: SearXNG at %s is not usable (%s); using Wikipedia only", research.searxng_url,
                            status["error"] or "no answer")
                source = "wikipedia"
        if source == "searxng" or source == "auto":
            base = base or PlaywrightWebClient(allowed_origins={origin_of(research.searxng_url)}, **kw)
            return SearxngWebClient(base, research.searxng_url, research.search_language, research.results_per_question,
                                    research.wikipedia_language)
    base = base or PlaywrightWebClient(**kw)
    if source == "wikipedia":
        from .wikipedia import WikipediaWebClient  # imported here: wikipedia.py imports this module
        return WikipediaWebClient(base, research.wikipedia_language, research.results_per_question)
    return base


def build_web_client(project) -> WebClient:
    return make_web_client(
        project.config.research,
        call_log=CallLog(project.book_dir / "logs" / "calls.jsonl"),
        session_id=f"bookforge:{project.root.name}:{project.book}",
    )
