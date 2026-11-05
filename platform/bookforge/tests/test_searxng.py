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
from bookforge.research.step import Question, answer_question, diversify, era_terms, place_terms, rank_hits, relevant_excerpt, skipped
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
    assert [p.url for p in attempt.pages] == [URL_B, URL_A]  # the page about "clerks" matches the question's words better
    b, a = attempt.pages
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
    (project.root / "config.yaml").write_text("research:\n  model_pick: false\n")
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
    assert (r.source, r.searxng_url, r.results_per_question, r.pages_per_question, r.facts_per_question) == ("auto", "http://127.0.0.1:8060", 10, 5, 3)
    assert "reddit.com" in r.skip_domains and "youtube.com" in r.skip_domains


# ── ranking, empty pages, early stop, and the reasons for dropped facts ─────

def test_era_terms_come_from_the_settings_years():
    assert era_terms("England, 1880s") == ["1880s", "1880", "19th century", "victorian"]
    assert era_terms("Rome, 44 BC") == [] and era_terms("any time") == []
    assert era_terms("France, 1923")[:3] == ["1920s", "1923", "20th century"] and "victorian" not in era_terms("France, 1923")


def test_results_about_the_era_and_the_question_are_read_first_and_ties_keep_the_engines_order():
    hits = [Hit("https://a.example/ports", "Merchant port books 1565-1799", "Records of the sixteenth century."),
            Hit("https://b.example/smuggling", "Coastal policing in 19th-century England", "How customs officers policed the coast."),
            Hit("https://c.example/dogs", "Dogs", ""), Hit("https://d.example/other", "Another page", "")]
    ranked = rank_hits(hits, "What did customs officers do?", "England, 1880s")
    assert [h.url for h, _ in ranked] == ["https://b.example/smuggling", "https://a.example/ports", "https://c.example/dogs", "https://d.example/other"]
    assert ranked[0][1] > ranked[1][1] and ranked[2][1] == ranked[3][1] == 0


def test_a_page_that_comes_back_empty_does_not_use_up_a_page_slot(project):
    web = FakeWebClient(searches={"q": "r"}, pages={"https://x.example/empty": "", "https://y.example/real": PAGE_A, "https://z.example/real": PAGE_B},
                        links={"q": [{"text": "Empty", "href": "https://x.example/empty"}, {"text": "Real", "href": "https://y.example/real"},
                                     {"text": "Real 2", "href": "https://z.example/real"}]})
    project.config.research.pages_per_question = 2
    project.config.research.facts_per_question = 9
    llm = RuleLLM([("Source page:", json.dumps({"facts": []}))])
    attempt = answer_question(make_ctx(project, llm, web), web, Question("customs", "q", False, ""), "story", set())
    assert [(p.url.split("/")[2], bool(p.error)) for p in attempt.pages] == [("x.example", True), ("y.example", False), ("z.example", False)]
    assert "no readable text" in attempt.pages[0].error and attempt.reason.startswith("page https://x.example/empty failed")


def test_reading_stops_once_enough_facts_are_kept(project):
    pages = {f"https://s{i}.example/p": PAGE_A for i in range(5)}
    web = FakeWebClient(searches={"q": "r"}, pages=pages, links={"q": [{"text": f"S{i}", "href": u} for i, u in enumerate(pages)]})
    project.config.research.facts_per_question = 2
    llm = RuleLLM([("Source page:", json.dumps({"facts": [{"claim": "Clerks recorded cargo.", "quote": "recorded the cargo of every ship"}]})),
                   ("Which of these facts directly answer", json.dumps({"keep": [1]}))])
    attempt = answer_question(make_ctx(project, llm, web), web, Question("customs", "q", False, ""), "story", set())
    assert len(attempt.pages) == 2 and len(attempt.facts) == 2  # not all five pages


PAGE_C = "Clavicle fractures are common. Most clavicle fractures heal in six weeks, although adults may need longer."


def test_a_dropped_fact_is_shown_with_the_checkers_reason(project):
    web = FakeWebClient(searches={"q": "r"}, pages={"https://x.example/p": PAGE_C}, links={"q": [{"text": "X", "href": "https://x.example/p"}]})
    llm = RuleLLM([("Source page:", json.dumps({"facts": [{"claim": "Fractures are common.", "quote": "Clavicle fractures are common"},
                                                           {"claim": "Most heal in six weeks.", "quote": "heal in six weeks"}]})),
                   ("Which of these facts directly answer", json.dumps({"keep": [1], "drop": [{"n": 2, "why": "a modern figure, not the 1880s"}]}))])
    q = Question("How do collarbones heal?", "q", False, "England, 1880s")
    attempt = answer_question(make_ctx(project, llm, web), web, q, "story", set())
    [page] = attempt.pages
    assert [f["claim"] for f in page.kept] == ["Fractures are common."]
    assert page.dropped == [{"claim": "Most heal in six weeks.", "quote": "heal in six weeks", "why": "a modern figure, not the 1880s"}]
    text = "\n".join(probe_mod.describe(attempt, q, "searxng"))
    assert "- dropped: Most heal in six weeks." in text and "why: a modern figure, not the 1880s" in text and "reading order" in text


def test_a_dropped_fact_without_a_reason_says_so(project):
    web = FakeWebClient(searches={"q": "r"}, pages={"https://x.example/p": PAGE_C}, links={"q": [{"text": "X", "href": "https://x.example/p"}]})
    llm = RuleLLM([("Source page:", json.dumps({"facts": [{"claim": "Fractures are common.", "quote": "Clavicle fractures are common"}]})),
                   ("Which of these facts directly answer", json.dumps({"keep": []}))])
    attempt = answer_question(make_ctx(project, llm, web), web, Question("q", "q", False, "England, 1880s"), "story", set())
    assert attempt.pages[0].dropped[0]["why"] == "no reason given"


def test_searxng_snippets_travel_with_the_results():
    c = SearxngWebClient(FakeWebClient(pages={search_url("x"): json.dumps({"results": [{"url": "https://a.example/1", "title": "T", "content": "An excerpt about ports."}]})}), BASE)
    from bookforge.research.hits import extract_hits
    [hit] = extract_hits(c.search("x").links, 5)
    assert hit.snippet == "An excerpt about ports."


# ── place in the ranking, sources in the stop rule, the check's wording ─────

def test_place_terms_expand_a_country_and_keep_other_words():
    assert place_terms("England, 1880s") == ["england", "english", "britain", "british", "london", ".uk"]
    assert place_terms("Port Haven, England, 1883")[:2] == ["port", "haven"] and "english" in place_terms("Port Haven, England, 1883")
    assert place_terms("any time") == [] and place_terms("") == []


def test_an_english_page_outranks_an_american_one_for_an_english_setting():
    hits = [Hit("https://www.archives.gov/ellis-island", "Ellis Island immigration manifests", "Customs officers recorded arrivals in the 1880s."),
            Hit("https://www.nationalarchives.gov.uk/customs", "Customs officers at English ports", "Duties of customs officers in the 1880s.")]
    ranked = rank_hits(hits, "What did customs officers do?", "England, 1880s")
    assert [h.url for h, _ in ranked][0] == "https://www.nationalarchives.gov.uk/customs" and ranked[0][1] > ranked[1][1]
    # without the place in the setting the two score the same on era and words, and the engine's order stands
    neutral = rank_hits(hits, "What did customs officers do?", "any time")
    assert [h.url for h, _ in neutral] == [h.url for h in hits]


def test_enough_facts_from_one_page_is_not_enough_to_stop(project):
    page = "Fogs were thick. They were yellow. They smelled of coal. Ships waited. Bells rang."
    pages = {"https://a.example/p": page, "https://b.example/p": page.replace("Bells rang.", "Lamps were lit."), "https://c.example/p": page}
    web = FakeWebClient(searches={"q": "r"}, pages=pages, links={"q": [{"text": t, "href": u} for t, u in zip("ABC", pages)]})
    project.config.research.facts_per_question = 3
    project.config.research.sources_per_question = 2
    facts = json.dumps({"facts": [{"claim": "Fogs were thick.", "quote": "Fogs were thick. They were yellow"},
                                  {"claim": "They smelled of coal.", "quote": "They smelled of coal. Ships waited"},
                                  {"claim": "Ships waited.", "quote": "Ships waited. Bells rang."}]})
    llm = RuleLLM([("Source page:", facts), ("Which of these facts directly answer", json.dumps({"keep": [1, 2, 3]}))])
    attempt = answer_question(make_ctx(project, llm, web), web, Question("fog", "q", False, ""), "story", set())
    assert len(attempt.pages) == 2 and len({h.url for h, _ in attempt.facts}) == 2  # the first page gave 3 facts; a second source was still read
    project.config.research.sources_per_question = 1
    llm2 = RuleLLM([("Source page:", facts), ("Which of these facts directly answer", json.dumps({"keep": [1, 2, 3]}))])
    again = answer_question(make_ctx(project, llm2, web), web, Question("fog", "q", False, ""), "story", set())
    assert len(again.pages) == 1  # with one source enough, it stops after the first page


def test_the_relevance_check_asks_to_keep_related_roles_and_not_to_drop_facts_for_sounding_old(project):
    from bookforge.prompts import render
    text = render("research_check", project.root, question="q", setting="England, 1880s", story="s", facts="1. x")
    assert "closely related role" in text and "same institution" in text and "Do not drop a fact only because a word in it sounds old" in text
    assert '"drop": [{"n": 2, "why"' in text


# ── the model's pick of which results to read ───────────────────────────────

PICK = "Choose which of these web search results"


def pick_llm(pick_reply):
    base = reader(None)
    return RuleLLM([(PICK, pick_reply)] + base.rules)


def pages_read(attempt):
    return [p.url for p in attempt.pages]


def test_the_models_pick_decides_the_reading_order(project):
    project.config.research.model_pick = True
    web = scripted_web()
    llm = pick_llm(json.dumps({"read": [2, 1]}))  # the model is shown B then A (word match order) and puts A first
    q = Question("What did customs clerks do?", "customs clerk 1880s", False, "England, 1880s")
    attempt = answer_question(make_ctx(project, llm, web), web, q, "story", set())
    order = [h.url for h, _ in attempt.order]
    assert attempt.picked == 2 and order == [URL_A, URL_B]
    assert llm.calls_matching(PICK)
    text = "\n".join(probe_mod.describe(attempt, q, "searxng"))
    assert "chosen by the model" in text


def test_a_failed_pick_falls_back_to_word_matching(project):
    project.config.research.model_pick = True
    from bookforge.errors import BookforgeError

    def boom(messages):
        raise BookforgeError("model offline")

    web = scripted_web()
    q = Question("What did customs clerks do?", "customs clerk 1880s", False, "England, 1880s")
    attempt = answer_question(make_ctx(project, pick_llm(boom), web), web, q, "story", set())
    assert attempt.picked == 0 and pages_read(attempt) == [URL_B, URL_A]


def test_a_nonsense_pick_falls_back_and_invalid_numbers_are_ignored(project):
    project.config.research.model_pick = True
    q = Question("What did customs clerks do?", "customs clerk 1880s", False, "England, 1880s")
    for reply in ("not json at all", json.dumps({"read": [99, 0, -1, "x", True]}), json.dumps({"read": []})):
        web = scripted_web()
        attempt = answer_question(make_ctx(project, pick_llm(reply), web), web, q, "story", set())
        assert attempt.picked == 0 and pages_read(attempt) == [URL_B, URL_A], reply
    web = scripted_web()
    attempt = answer_question(make_ctx(project, pick_llm(json.dumps({"read": [99, 2, 2, 1]})), web), web, q, "story", set())
    assert attempt.picked == 2  # 99 ignored, the repeated 2 counted once


def test_the_pick_can_be_switched_off(project):
    project.config.research.model_pick = False
    web = scripted_web()
    llm = pick_llm(json.dumps({"read": [1]}))
    q = Question("What did customs clerks do?", "customs clerk 1880s", False, "England, 1880s")
    attempt = answer_question(make_ctx(project, llm, web), web, q, "story", set())
    assert not llm.calls_matching(PICK) and attempt.picked == 0
