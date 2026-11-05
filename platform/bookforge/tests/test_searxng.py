"""Research through SearXNG: parsing, the web wrapper's one local exception, source choice, page excerpts, the test command."""

import json
from urllib.parse import quote_plus

import httpx
import pytest
from typer.testing import CliRunner

from bookforge import cli, doctor
from bookforge.config import Config, Research
from bookforge.layers.runner import StepContext
from bookforge.research import probe as probe_mod, search as search_mod, searxng
from bookforge.research.hits import Hit
from bookforge.research.search import FakeWebClient, PlaywrightWebClient, WebError, WebResult, make_web_client
from bookforge.research.searxng import SearxngWebClient, parse_results
from bookforge.research.step import Question, answer_question, diversify, relevant_excerpt, skipped
from conftest import RuleLLM
from test_web import FakeTool, good  # noqa: F401  (good builds a successful tool result)

BASE = "http://127.0.0.1:8060"
PUBLIC = lambda host, port: [(2, 1, 6, "", ("93.184.216.34", 0))]  # noqa: E731


def reply(*urls, unresponsive=()):
    return json.dumps({"query": "q", "results": [{"url": u, "title": f"Title of {u}", "content": "c", "engine": "e"} for u in urls],
                       "unresponsive_engines": [list(x) for x in unresponsive]})


# ── reading SearXNG's reply ─────────────────────────────────────────────────

def test_a_normal_reply_gives_the_results_and_the_engines_that_failed():
    results, failed = parse_results(reply("https://a.example/1", "https://b.example/2", unresponsive=[("duckduckgo", "CAPTCHA"), ("brave", "timeout")]), "q")
    assert [r["url"] for r in results] == ["https://a.example/1", "https://b.example/2"] and failed == "duckduckgo (CAPTCHA), brave (timeout)"


def test_a_reply_cut_off_by_the_web_tool_still_gives_its_complete_results():
    raw = reply("https://a.example/1", "https://b.example/2", "https://c.example/3")
    cut = raw[: raw.index("https://c.example/3") + 10]  # in the middle of the third result
    results, _ = parse_results(cut, "q")
    assert [r["url"] for r in results] == ["https://a.example/1", "https://b.example/2"]


def test_html_instead_of_json_says_how_to_fix_it():
    with pytest.raises(WebError) as e:
        parse_results("<html><body>403 Forbidden</body></html>", "q")
    assert "search.formats" in str(e.value) and "json" in str(e.value)


def test_no_results_names_the_engines_that_did_not_answer():
    with pytest.raises(WebError) as e:
        parse_results(reply(unresponsive=[("google", "CAPTCHA"), ("bing", "access denied")]), "customs clerk")
    assert "found nothing for 'customs clerk'" in str(e.value) and "google (CAPTCHA), bing (access denied)" in str(e.value)
    with pytest.raises(WebError) as e:
        parse_results(reply(), "x")
    assert "engines are enabled" in str(e.value)


# ── the client ──────────────────────────────────────────────────────────────

def client(**pages):
    return SearxngWebClient(FakeWebClient(pages=pages), BASE, "en", 8)


def search_url(q):
    return f"{BASE}/search?q={quote_plus(q)}&format=json&language=en&safesearch=0"


def test_a_search_asks_searxng_for_json_and_returns_the_result_links():
    c = client(**{search_url("customs clerk duties"): reply("https://a.example/1", "https://b.example/2")})
    r = c.search("  customs   clerk duties ")
    assert [(l["text"], l["href"]) for l in r.links] == [("Title of https://a.example/1", "https://a.example/1"), ("Title of https://b.example/2", "https://b.example/2")]
    assert c.source_name == "searxng" and c._inner.calls == [("fetch", search_url("customs clerk duties"))]
    with pytest.raises(WebError):
        c.search("   ")


def test_pages_come_from_the_inner_client_and_wikipedia_articles_from_its_text_api():
    api = ("https://en.wikipedia.org/w/api.php?action=query&prop=extracts&explaintext=1&exsectionformat=plain&redirects=1"
           "&format=json&formatversion=2&titles=Harbourmaster")
    c = client(**{"https://a.example/page": "A page.", api: json.dumps({"query": {"pages": [{"title": "Harbourmaster", "extract": "A harbourmaster runs a port."}]}})})
    assert c.fetch("https://a.example/page").text == "A page."
    assert c.fetch("https://en.wikipedia.org/wiki/Harbourmaster").text == "A harbourmaster runs a port."


# ── the web wrapper's one local exception ───────────────────────────────────

def wrapper(tool, **kw):
    kw.setdefault("resolver", PUBLIC)
    return PlaywrightWebClient(tool=tool, **kw)


def test_the_configured_searxng_address_may_be_fetched_and_no_other_local_address():
    tool = FakeTool(good("{}"), good("{}"))
    w = wrapper(tool, allowed_origins={BASE})
    w.fetch(f"{BASE}/search?q=x&format=json")
    assert tool.params[0]["url"] == f"{BASE}/search?q=x&format=json"
    for url in ("http://127.0.0.1:8100/health", "http://127.0.0.1:8061/search?q=x", "http://localhost:8060/search", "http://127.0.0.1:11434/api/tags"):
        with pytest.raises(WebError):
            wrapper(FakeTool(good()), allowed_origins={BASE}, resolver=lambda h, p: [(2, 1, 6, "", ("127.0.0.1", 0))]).fetch(url)


def test_without_the_exception_the_local_address_is_refused():
    with pytest.raises(WebError):
        wrapper(FakeTool(good()), resolver=lambda h, p: [(2, 1, 6, "", ("127.0.0.1", 0))]).fetch(f"{BASE}/search?q=x")


# ── which source is used ────────────────────────────────────────────────────

def test_searxng_source_builds_a_searxng_client_that_may_reach_its_address():
    c = make_web_client(Research(source="searxng"), resolver=PUBLIC, tool=FakeTool())
    assert isinstance(c, SearxngWebClient) and c._inner._allowed == frozenset({BASE})


def test_auto_uses_searxng_when_it_answers_and_wikipedia_when_it_does_not(monkeypatch):
    ok = {"reachable": True, "json": True, "results": 5, "failed_engines": "", "error": ""}
    monkeypatch.setattr(searxng, "probe", lambda url, **kw: ok)
    assert make_web_client(Research(), tool=FakeTool()).source_name == "searxng"
    down = {**ok, "reachable": False, "json": False, "error": "cannot reach"}
    monkeypatch.setattr(searxng, "probe", lambda url, **kw: down)
    assert make_web_client(Research(), tool=FakeTool()).source_name == "wikipedia"
    monkeypatch.setattr(searxng, "probe", lambda url, **kw: {**ok, "json": False})
    assert make_web_client(Research(), tool=FakeTool()).source_name == "wikipedia"


def test_the_other_sources_are_unchanged(monkeypatch):
    monkeypatch.setattr(searxng, "probe", lambda url, **kw: pytest.fail("not asked"))
    assert make_web_client(Research(source="wikipedia"), tool=FakeTool()).source_name == "wikipedia"
    assert make_web_client(Research(source="duckduckgo"), tool=FakeTool()).source_name == "duckduckgo"


# ── the probe (a direct call to the local service) ──────────────────────────

def transport(handler):
    return httpx.MockTransport(handler)


def test_probe_reports_reachable_json_results_and_failed_engines():
    t = transport(lambda r: httpx.Response(200, json={"results": [{"url": "u"}] * 3, "unresponsive_engines": [["google", "CAPTCHA"]]}))
    assert searxng.probe(BASE, transport=t) == {"reachable": True, "json": True, "results": 3, "failed_engines": "google (CAPTCHA)", "error": ""}


@pytest.mark.parametrize("response,needle", [
    (httpx.Response(403), "refused the JSON format"), (httpx.Response(200, text="<html>"), "did not answer with JSON"), (httpx.Response(500), "HTTP 500")])
def test_probe_names_what_is_wrong(response, needle):
    s = searxng.probe(BASE, transport=transport(lambda r: response))
    assert s["reachable"] is True and s["json"] is False and needle in s["error"]


def test_probe_when_nothing_is_listening():
    def refuse(request):
        raise httpx.ConnectError("refused")

    s = searxng.probe(BASE, transport=transport(refuse))
    assert s["reachable"] is False and "cannot reach" in s["error"]


def test_the_doctor_check(monkeypatch):
    def with_status(**status):
        monkeypatch.setattr(searxng, "probe", lambda url, **kw: {"reachable": True, "json": True, "results": 4, "failed_engines": "", "error": "", **status})
        return doctor.check_searxng(Research())

    assert with_status().level == "pass" and "4 result(s)" in with_status().detail
    assert "engines that did not answer: google (CAPTCHA)" in with_status(failed_engines="google (CAPTCHA)").detail
    assert with_status(results=0).level == "warn"
    assert with_status(json=False, error="no json").level == "warn" and "falls back to Wikipedia" in with_status(json=False, error="no json").detail
    monkeypatch.setattr(searxng, "probe", lambda url, **kw: {"reachable": False, "json": False, "results": 0, "failed_engines": "", "error": "down"})
    assert doctor.check_searxng(Research(source="searxng")).level == "fail"
    assert doctor.check_searxng(Research(source="wikipedia")) is None


# ── page excerpts, sites, diversity ─────────────────────────────────────────

def test_a_short_page_is_shown_whole_and_a_long_one_by_the_parts_that_mention_the_question():
    short = "The customs house kept ledgers."
    assert relevant_excerpt(short, "customs ledgers", 12000) == short
    filler = "Menu home about contact cookies. " * 60
    page = filler * 10 + " Customs clerks recorded cargo duties in bound ledgers every day. " + filler * 10
    out = relevant_excerpt(page, "What did customs clerks record in ledgers?", 3000)
    assert "Customs clerks recorded cargo duties" in out and len(out) <= 3000 + 20 and "[...]" in out
    assert "Customs clerks recorded cargo duties" not in page[:3000]  # the old cut (the first characters) would have missed it


def test_excerpt_windows_stay_in_page_order():
    page = ("a" * 1500) + "ledger " * 200 + ("b" * 1500) + "clerk " * 200
    out = relevant_excerpt(page, "ledger clerk", 3000)
    assert out.index("ledger") < out.index("clerk")


def test_skipped_sites_include_subdomains_but_not_look_alikes():
    skip = ["reddit.com", "youtube.com"]
    assert skipped("https://www.reddit.com/r/x", skip) and skipped("https://youtube.com/watch", skip) and skipped("https://old.reddit.com/x", skip)
    assert not skipped("https://notreddit.com/x", skip)
    assert not skipped("https://reddit.com.evil.example/x", skip)


def test_each_sites_first_result_comes_first():
    hits = [Hit("https://a.example/1", ""), Hit("https://a.example/2", ""), Hit("https://b.example/1", ""), Hit("https://a.example/3", ""), Hit("https://c.example/1", "")]
    assert [h.url for h in diversify(hits)] == ["https://a.example/1", "https://b.example/1", "https://c.example/1", "https://a.example/2", "https://a.example/3"]


# ── answering one question, and the test command ────────────────────────────

URL_A, URL_B, URL_R = "https://a.example/customs", "https://b.example/clerks", "https://www.reddit.com/r/history/x"
PAGE_A = "Customs clerks recorded the cargo of every ship in bound ledgers kept at the customs house."
PAGE_B = "A clerk in the 1880s earned about a pound a week."


def make_ctx(project, llm, web):
    return StepContext(project=project, layer="synopsis", llm=llm, web=web)


def scripted_web():
    return FakeWebClient(searches={"customs clerk 1880s": "r"}, pages={URL_A: PAGE_A, URL_B: PAGE_B},
                         links={"customs clerk 1880s": [{"text": "Reddit thread", "href": URL_R}, {"text": "Customs", "href": URL_A},
                                                        {"text": "Clerks", "href": URL_B}]})


def reader(project):
    return RuleLLM([
        (f"Source page: {URL_A}", json.dumps({"facts": [{"claim": "Clerks recorded cargo in ledgers.", "quote": "recorded the cargo of every ship in bound ledgers"}]})),
        (f"Source page: {URL_B}", json.dumps({"facts": [{"claim": "Clerks were paid a pound a week.", "quote": "a pound a week and a half and some beer"}]})),
        ("Which of these facts directly answer", json.dumps({"keep": [1]})),
    ])


def test_answering_a_question_skips_listed_sites_and_traces_every_page(project):
    web = scripted_web()
    attempt = answer_question(make_ctx(project, reader(project), web), web, Question("What did customs clerks do?", "customs clerk 1880s", False, "England, 1880s"), "story", set())
    assert [s.endswith("(site skipped)") for s in attempt.skipped] == [True] and ("fetch", URL_R) not in web.calls
    assert [p.url for p in attempt.pages] == [URL_A, URL_B]
    a, b = attempt.pages
    assert (a.model_facts, a.quote_rejected, len(a.kept)) == (1, 0, 1) and (b.model_facts, b.quote_rejected, len(b.kept)) == (1, 1, 0)  # B's quote is not on its page
    assert [f["claim"] for _, f in attempt.facts] == ["Clerks recorded cargo in ledgers."] and attempt.reason == ""


def test_a_question_with_no_facts_says_why(project):
    web = scripted_web()
    llm = RuleLLM([("Source page:", json.dumps({"facts": []}))])
    attempt = answer_question(make_ctx(project, llm, web), web, Question("q", "customs clerk 1880s", False, "any time"), "story", set())
    assert not attempt.facts and attempt.reason == "no supported facts in the 2 page(s) read"
    web2 = FakeWebClient(searches={"q": "r"}, links={"q": [{"text": "x", "href": URL_R}]})
    again = answer_question(make_ctx(project, llm, web2), web2, Question("q", "q", False, ""), "story", set())
    assert "every result was already read or from a skipped site" in again.reason


def test_a_failing_search_is_a_reason_not_an_exception(project):
    web = FakeWebClient()
    attempt = answer_question(make_ctx(project, RuleLLM([]), web), web, Question("q", "nothing scripted", False, ""), "story", set())
    assert not attempt.facts and "no scripted search result" in attempt.reason


def test_the_describe_output_names_results_pages_and_the_verdict(project):
    web = scripted_web()
    q = Question("What did customs clerks do?", "customs clerk 1880s", False, "England, 1880s")
    attempt = answer_question(make_ctx(project, reader(project), web), web, q, "story", set())
    text = "\n".join(probe_mod.describe(attempt, q, "searxng"))
    for needle in ("source: searxng", "searched for: customs clerk 1880s", "3 result(s):", "(not read: https://www.reddit.com/r/history/x (site skipped))",
                   "the model reported 1 fact(s): 1 dropped (quote not on the page)", "+ Clerks recorded cargo in ledgers.", "RESULT: 1 fact(s) kept"):
        assert needle in text, needle


def test_the_research_test_command(project, monkeypatch):
    web = scripted_web()
    monkeypatch.setattr(cli, "build_client", lambda p: reader(p))
    monkeypatch.setattr(cli, "build_web_client", lambda p: web)
    out = CliRunner().invoke(cli.app, ["research-test", str(project.root), "What did customs clerks do?", "--query", "customs clerk 1880s", "--setting", "England, 1880s"])
    assert out.exit_code == 0, out.output
    assert "RESULT: 1 fact(s) kept" in out.output and "searched for: customs clerk 1880s" in out.output
    assert not (project.root / "research" / "sources.jsonl").exists()  # it stores nothing
    monkeypatch.setattr(cli, "build_client", lambda p: RuleLLM([("Source page:", json.dumps({"facts": []}))]))
    none = CliRunner().invoke(cli.app, ["research-test", str(project.root), "q", "--query", "customs clerk 1880s"])
    assert none.exit_code == 1 and "RESULT: no facts" in none.output


# ── configuration ───────────────────────────────────────────────────────────

def test_research_defaults_for_the_real_web():
    r = Config().research
    assert (r.source, r.searxng_url, r.results_per_question, r.pages_per_question) == ("auto", "http://127.0.0.1:8060", 8, 3)
    assert "reddit.com" in r.skip_domains and "youtube.com" in r.skip_domains
