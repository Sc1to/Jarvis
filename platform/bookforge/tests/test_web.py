import json
import socket

import pytest

from bookforge.calllog import CallLog
from bookforge.errors import BookforgeError
from bookforge.research import search as web
from bookforge.research.search import FakeWebClient, PlaywrightWebClient, WebError, check_url

web.load_web_tool_class()  # puts platform/ on sys.path, as the CLI does, so `tools` imports
from tools.base import ToolResult  # noqa: E402


def resolver(*ips):
    def fake(host, port):
        return [(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 0)) for ip in ips]
    return fake


PUBLIC = resolver("93.184.216.34")


class FakeTool:
    def __init__(self, *results):
        self.results = list(results)
        self.params = []

    def execute(self, params):
        self.params.append(params)
        return self.results.pop(0)


def good(text="page text"):
    return ToolResult(success=True, output=text)


def bad(err="net::ERR_FAILED"):
    return ToolResult(success=False, output="", error=err)


# ── URL checks ────────────────────────────────────────────────────────────────

def test_public_https_and_http_are_allowed():
    assert check_url("https://example.com/a?b=1", PUBLIC) == "https://example.com/a?b=1"
    assert check_url("  http://example.com  ", PUBLIC) == "http://example.com"


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "ftp://example.com/x", "javascript:alert(1)", "data:text/html,hi", "//example.com", "https://",
])
def test_other_schemes_and_hostless_urls_are_refused(url):
    with pytest.raises(WebError):
        check_url(url, PUBLIC)


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.5", "192.168.1.10", "172.16.0.1", "169.254.169.254", "::1", "fe80::1", "0.0.0.0"])
def test_loopback_private_and_link_local_hosts_are_refused(ip):
    with pytest.raises(WebError, match="non-public"):
        check_url("http://anything.example/", resolver(ip))


def test_localhost_and_the_platform_ports_are_refused():
    for url in ("http://localhost:8000/admin", "http://127.0.0.1:11434/api/tags", "http://[::1]:8041/v1/models"):
        with pytest.raises(WebError):
            check_url(url)  # real resolver: these resolve to loopback


def test_a_host_that_resolves_to_both_public_and_private_is_refused():
    with pytest.raises(WebError, match="non-public"):
        check_url("https://rebind.example", resolver("93.184.216.34", "10.0.0.1"))


def test_unresolvable_host_is_a_web_error():
    def boom(host, port):
        raise socket.gaierror("no such host")

    with pytest.raises(WebError, match="cannot resolve"):
        check_url("https://nope.invalid", boom)


# ── client ────────────────────────────────────────────────────────────────────

def make(tool, tmp_path, **kw):
    sleeps = []
    c = PlaywrightWebClient(CallLog(tmp_path / "calls.jsonl"), tool=tool, sleep=sleeps.append, resolver=PUBLIC, **kw)
    c.sleeps = sleeps
    return c


def test_search_encodes_the_query_and_logs(tmp_path):
    tool = FakeTool(good("results"))
    r = make(tool, tmp_path).search("  tea   &  coffee #1 ")
    assert r.text == "results" and r.kind == "search" and r.target == "tea & coffee #1"
    assert tool.params == [{"op": "search", "query": "tea+%26+coffee+%231"}]
    rec = json.loads((tmp_path / "calls.jsonl").read_text())
    assert rec["kind"] == "web" and rec["op"] == "search" and rec["ok"] is True and rec["chars"] == 7


def test_bad_queries_never_reach_the_tool(tmp_path):
    tool = FakeTool()
    c = make(tool, tmp_path)
    for q in ("", "   ", "x" * 301):
        with pytest.raises(WebError):
            c.search(q)
    assert tool.params == []


def test_fetch_checks_the_url_first(tmp_path):
    tool = FakeTool(good("x"))
    c = PlaywrightWebClient(tool=tool, resolver=resolver("10.0.0.1"))
    with pytest.raises(WebError, match="non-public"):
        c.fetch("http://intranet.example/")
    with pytest.raises(WebError, match="only http"):
        c.fetch("file:///etc/passwd")
    assert tool.params == []


def test_fetch_passes_the_url(tmp_path):
    tool = FakeTool(good("body"))
    assert make(tool, tmp_path).fetch("https://example.com/a").text == "body"
    assert tool.params == [{"op": "fetch_page", "url": "https://example.com/a"}]


def test_failures_are_retried_then_reported(tmp_path):
    tool = FakeTool(bad("timeout"), good("second time"))
    c = make(tool, tmp_path)
    assert c.fetch("https://example.com").text == "second time"
    assert c.sleeps == [2.0]

    tool = FakeTool(bad("e1"), bad("e2"))
    c = make(tool, tmp_path)
    with pytest.raises(WebError, match="after 2 attempts: e2"):
        c.fetch("https://example.com")
    last = json.loads((tmp_path / "calls.jsonl").read_text().splitlines()[-1])
    assert last["ok"] is False and last["error"] == "e2"


def test_missing_playwright_is_a_clear_error(monkeypatch):
    monkeypatch.setattr(web, "playwright_installed", lambda: False)
    with pytest.raises(WebError, match="playwright is not installed"):
        PlaywrightWebClient(resolver=PUBLIC).fetch("https://example.com")


def test_real_tool_is_built_with_agent_name_and_session(monkeypatch):
    made = {}

    class Recorder:
        def __init__(self, session_id=None, agent_name="unknown"):
            made.update(session_id=session_id, agent_name=agent_name)

        def execute(self, params):
            return good("ok")

    monkeypatch.setattr(web, "playwright_installed", lambda: True)
    monkeypatch.setattr(web, "load_web_tool_class", lambda: Recorder)
    PlaywrightWebClient(session_id="bookforge:s:b1", resolver=PUBLIC).fetch("https://example.com")
    assert made == {"session_id": "bookforge:s:b1", "agent_name": "platform_bookforge_research"}


def test_platform_web_tool_can_be_imported_from_the_service():
    assert web.load_web_tool_class().__name__ == "WebTool"


def test_build_web_client_names_the_session(project):
    from bookforge.research.wikipedia import WikipediaWebClient
    c = web.build_web_client(project)  # the default source is Wikipedia, wrapped around the web-tool client
    assert isinstance(c, WikipediaWebClient)
    assert c._inner._session_id == f"bookforge:{project.root.name}:b1"
    assert c._inner._log.path == project.book_dir / "logs" / "calls.jsonl"
    project.config.research.source = "duckduckgo"
    plain = web.build_web_client(project)
    assert isinstance(plain, web.PlaywrightWebClient) and plain._session_id == c._inner._session_id


# ── fake ──────────────────────────────────────────────────────────────────────

def test_fake_web_client():
    f = FakeWebClient(searches={"q": "r"}, pages={"https://a.example": "p"})
    assert f.search("q").text == "r" and f.fetch("https://a.example").text == "p"
    assert f.calls == [("search", "q"), ("fetch", "https://a.example")]
    with pytest.raises(BookforgeError):
        f.fetch("https://unknown.example")


def test_links_from_the_tool_are_passed_on(tmp_path):
    tool = FakeTool(ToolResult(success=True, output="page", metadata={"links": [{"text": "a", "href": "https://x.example/"}]}))
    assert make(tool, tmp_path).fetch("https://example.com").links == [{"text": "a", "href": "https://x.example/"}]


def test_missing_or_malformed_links_become_an_empty_list(tmp_path):
    tool = FakeTool(good("p"), ToolResult(success=True, output="p", metadata={"links": "oops"}))
    c = make(tool, tmp_path)
    assert c.fetch("https://example.com").links == [] and c.fetch("https://example.com").links == []
