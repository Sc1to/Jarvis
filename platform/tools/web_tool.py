import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from .base import Tool, ToolResult

try:
    from playwright.async_api import async_playwright
    _PLAYWRIGHT = True
except ImportError:
    async_playwright = None  # type: ignore
    _PLAYWRIGHT = False

DB_PATH = "/opt/platform/data/platform.db"
SEARCH_URL = "https://html.duckduckgo.com/html/?q={query}"
TIMEOUT_MS = 30_000
MAX_LINKS = 300
# A page that builds itself with scripts is empty when its HTML has loaded. Only if the text is nearly empty then,
# wait for the page's network activity to settle and for text to appear; a normal page is read at once, as before.
MIN_TEXT_CHARS = 200
SETTLE_MS = 8_000
POLL_MS = 3_000
POLL_STEP_MS = 250
_TEXT_JS = "document.body ? document.body.innerText : ''"
_LINKS_JS = (
    "Array.from(document.querySelectorAll('a[href]'))"
    ".map(a => ({text: (a.innerText || '').trim(), href: a.href}))"
)
_BLOCKED_DOMAINS = frozenset(["google-analytics.com", "doubleclick.net", "facebook.net", "ads.twitter.com"])


NAVIGATION_RETRIES = 3


async def _evaluate(page, js):
    """Run a script in the page. A page that redirects itself while we read it destroys the script's context
    ("Execution context was destroyed, most likely because of a navigation"): wait for the new page to load, then read again."""
    for attempt in range(NAVIGATION_RETRIES + 1):
        try:
            return await page.evaluate(js)
        except Exception as e:
            if "Execution context was destroyed" not in str(e) or attempt == NAVIGATION_RETRIES:
                raise
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=SETTLE_MS)
            except Exception:  # still loading: try reading anyway
                pass


async def _page_text(page) -> str:
    """The visible text of the page; for a nearly empty one, after waiting for scripts to fill it in (bounded)."""
    text = await _evaluate(page, _TEXT_JS)
    if len(text.strip()) >= MIN_TEXT_CHARS:
        return text
    try:
        await page.wait_for_load_state("networkidle", timeout=SETTLE_MS)
    except Exception:  # a page that never goes quiet (live updates, ads): look at what is there
        pass
    waited = 0
    while True:
        text = await _evaluate(page, _TEXT_JS)
        if len(text.strip()) >= MIN_TEXT_CHARS or waited >= POLL_MS:
            return text
        await page.wait_for_timeout(POLL_STEP_MS)
        waited += POLL_STEP_MS


def _clean_links(raw) -> list[dict]:
    """Keep well-formed {text, href} pairs from the page, capped in number and size."""
    links = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("href"), str) or not item["href"]:
            continue
        text = item.get("text") if isinstance(item.get("text"), str) else ""
        links.append({"text": text[:200], "href": item["href"][:2000]})
        if len(links) >= MAX_LINKS:
            break
    return links


def _is_blocked(method: str, url: str) -> bool:
    if method != "GET":
        return True
    return any(d in url for d in _BLOCKED_DOMAINS)


def _log_start(session_id: str | None, agent_name: str, action: str, url: str) -> int | None:
    if not session_id:
        return None
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.execute(
            "INSERT INTO internet_log (session_id, agent_name, action, url, timestamp) VALUES (?,?,?,?,?)",
            (session_id, agent_name, action, url, datetime.now(timezone.utc).isoformat()),
        )
        entry_id = cur.lastrowid
        conn.commit()
        conn.close()
        return entry_id
    except Exception:
        return None


def _log_finish(entry_id: int | None, summary: str) -> None:
    if entry_id is None:
        return
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("UPDATE internet_log SET results_summary=? WHERE id=?", (summary, entry_id))
        conn.commit()
        conn.close()
    except Exception:
        pass


class WebTool(Tool):
    def __init__(self, session_id: str | None = None, agent_name: str = "unknown"):
        self._session_id = session_id
        self._agent_name = agent_name

    @property
    def name(self) -> str:
        return "web"

    @property
    def description(self) -> str:
        return "Read-only sandboxed web access via Playwright — all calls logged to session memory"

    def execute(self, params: dict) -> ToolResult:
        op = params.get("op")
        try:
            match op:
                case "search":     return asyncio.run(self.search(params["query"]))
                case "fetch_page": return asyncio.run(self.fetch_page(params["url"]))
                case _:            return ToolResult(success=False, output="", error=f"Unknown op: {op}")
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))

    async def search(self, query: str) -> ToolResult:
        url = SEARCH_URL.format(query=query)
        entry_id = _log_start(self._session_id, self._agent_name, "search", url)
        result = await self._fetch(url)
        _log_finish(entry_id, f"search {query!r} → {len(result.output)} chars")
        return ToolResult(
            success=result.success,
            output=result.output,
            error=result.error,
            metadata={**result.metadata, "log_entry_id": entry_id},
        )

    async def fetch_page(self, url: str) -> ToolResult:
        entry_id = _log_start(self._session_id, self._agent_name, "fetch", url)
        result = await self._fetch(url)
        _log_finish(entry_id, f"fetch {url} → {len(result.output)} chars")
        return ToolResult(
            success=result.success,
            output=result.output,
            error=result.error,
            metadata={**result.metadata, "log_entry_id": entry_id},
        )

    async def _fetch(self, url: str) -> ToolResult:
        if not _PLAYWRIGHT:
            return ToolResult(success=False, output="", error="playwright not installed — run: playwright install chromium")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.route("**/*", lambda route, req=None: (
                    route.abort() if _is_blocked(
                        route.request.method, route.request.url
                    ) else route.continue_()
                ))
                await page.goto(url, timeout=TIMEOUT_MS, wait_until="domcontentloaded")
                text = await _page_text(page)
                links = _clean_links(await _evaluate(page, _LINKS_JS))
                return ToolResult(
                    success=True, output=text[:50_000],
                    metadata={"url": url, "chars": len(text), "links": links},
                )
            except Exception as e:
                return ToolResult(success=False, output="", error=str(e))
            finally:
                await browser.close()
