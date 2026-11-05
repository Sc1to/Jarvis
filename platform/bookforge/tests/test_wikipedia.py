import json
from urllib.parse import quote_plus

import httpx
import pytest

from bookforge.config import Research, Config, ModelEndpoint
from bookforge.doctor import check_models_endpoint, check_web
from bookforge.errors import ConfigError
from bookforge.layers.runner import StepContext
from bookforge.research.hits import search_hits
from bookforge.research.notes import stores_for
from bookforge.research.search import FakeWebClient, WebError
from bookforge.research.step import run_research
from bookforge.research.wikipedia import WikipediaWebClient, api_url, article_text, page_url, wiki_title
from bookforge.config import load_config
from conftest import RuleLLM

SEARCH = "https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={q}&srlimit={n}&format=json&formatversion=2"
EXTRACT = ("https://{lang}.wikipedia.org/w/api.php?action=query&prop=extracts&explaintext=1&exsectionformat=plain&redirects=1"
           "&format=json&formatversion=2&titles={t}")


def search_json(*titles):
    return json.dumps({"batchcomplete": True, "query": {"search": [{"ns": 0, "title": t, "pageid": i} for i, t in enumerate(titles, 1)]}})


def extract_json(title, text):
    return json.dumps({"batchcomplete": True, "query": {"pages": [{"pageid": 1, "ns": 0, "title": title, "extract": text}]}})


def client(pages, lang="en", results=5):
    inner = FakeWebClient(pages=pages)
    return WikipediaWebClient(inner, lang, results), inner


# ── addresses ───────────────────────────────────────────────────────────────

def test_article_addresses_are_readable_and_reversible():
    assert page_url("en", "Clerk (office)") == "https://en.wikipedia.org/wiki/Clerk_(office)"
    assert page_url("de", "Schreiber (Beruf)") == "https://de.wikipedia.org/wiki/Schreiber_(Beruf)"
    assert page_url("en", "Zürich & Co?") == "https://en.wikipedia.org/wiki/Z%C3%BCrich_%26_Co%3F"
    assert wiki_title("https://en.wikipedia.org/wiki/Z%C3%BCrich_%26_Co%3F") == ("en", "Zürich & Co?")
    assert wiki_title("https://FR.wikipedia.org/wiki/Paris") == ("fr", "Paris")
    assert api_url("de") == "https://de.wikipedia.org/w/api.php"


@pytest.mark.parametrize("url", ["https://example.com/wiki/Paris", "https://en.wikipedia.org/", "https://en.wikipedia.org/wiki/",
                                 "https://en.wikipedia.org/w/index.php?title=Paris", "https://wikipedia.org/wiki/Paris",
                                 "https://evil.example/en.wikipedia.org/wiki/Paris", "https://en.wikipedia.org.evil.example/wiki/Paris"])
def test_other_addresses_are_not_articles(url):
    assert wiki_title(url) is None


# ── search ──────────────────────────────────────────────────────────────────

def test_search_asks_the_api_and_returns_article_links():
    url = SEARCH.format(q=quote_plus("clerical practices"), n=5)
    c, inner = client({url: search_json("Clerk", "Scrivener", "Copperplate (script)")})
    r = c.search("  clerical   practices ")
    assert inner.calls == [("fetch", url)]
    assert [l["href"] for l in r.links] == ["https://en.wikipedia.org/wiki/Clerk", "https://en.wikipedia.org/wiki/Scrivener",
                                          "https://en.wikipedia.org/wiki/Copperplate_(script)"]
    assert r.kind == "search" and r.target == "clerical practices" and [l["text"] for l in r.links][0] == "Clerk"


def test_the_language_and_result_count_come_from_the_config():
    url = "https://de.wikipedia.org/w/api.php?action=query&list=search&srsearch=schreiber&srlimit=3&format=json&formatversion=2"
    c, inner = client({url: search_json("Schreiber")}, lang="de", results=3)
    assert c.search("schreiber").links[0]["href"] == "https://de.wikipedia.org/wiki/Schreiber"
    assert inner.calls[0][1] == url


def test_no_results_means_no_links_so_the_research_step_reports_it():
    url = SEARCH.format(q="xyzzy", n=5)
    c, _ = client({url: search_json()})
    with pytest.raises(WebError, match="no result links"):
        search_hits(c, "xyzzy", 5)


def test_a_rate_limit_message_is_reported_plainly():
    url = SEARCH.format(q="history", n=5)
    c, _ = client({url: "You are making too many requests to the API. Please follow the best practices."})
    with pytest.raises(WebError, match="rate limited or blocked.*too many requests"):
        c.search("history")


def test_an_api_error_is_reported():
    url = SEARCH.format(q="history", n=5)
    c, _ = client({url: json.dumps({"error": {"code": "badvalue", "info": "Unrecognized value"}})})
    with pytest.raises(WebError, match="search failed: Unrecognized value"):
        c.search("history")


def test_an_empty_query_never_reaches_the_web():
    c, inner = client({})
    with pytest.raises(WebError, match="empty search query"):
        c.search("   ")
    assert inner.calls == []


# ── articles ────────────────────────────────────────────────────────────────

def test_an_article_comes_back_as_plain_text_with_its_normal_address():
    api = EXTRACT.format(lang="en", t=quote_plus("Clerk (office)"))
    c, inner = client({api: extract_json("Clerk (office)", "A clerk keeps records.\n\nClerks wrote by hand.")})
    r = c.fetch("https://en.wikipedia.org/wiki/Clerk_(office)")
    assert inner.calls == [("fetch", api)]
    assert r.kind == "fetch" and r.target == "https://en.wikipedia.org/wiki/Clerk_(office)" and r.text == "A clerk keeps records.\n\nClerks wrote by hand."


def test_the_article_language_comes_from_the_address():
    api = EXTRACT.format(lang="fr", t="Paris")
    c, inner = client({api: extract_json("Paris", "Paris est la capitale.")}, lang="en")
    assert c.fetch("https://fr.wikipedia.org/wiki/Paris").text == "Paris est la capitale."


def test_a_missing_article_is_an_error():
    api = EXTRACT.format(lang="en", t="Nope")
    c, _ = client({api: json.dumps({"query": {"pages": [{"title": "Nope", "missing": True}]}})})
    with pytest.raises(WebError, match="no article called 'Nope'"):
        c.fetch("https://en.wikipedia.org/wiki/Nope")
    empty, _ = client({api: extract_json("Nope", "  ")})
    with pytest.raises(WebError, match="no text"):
        empty.fetch("https://en.wikipedia.org/wiki/Nope")


def test_other_addresses_go_to_the_web_tool_unchanged():
    c, inner = client({"https://example.com/page": "plain page"})
    assert c.fetch("https://example.com/page").text == "plain page"
    assert inner.calls == [("fetch", "https://example.com/page")]


@pytest.mark.parametrize("cut", [
    r'unterminated text with a \"quote\" and café and more \u00',
    "text that ends in a backslash \\",
    r'text with escaped newline\nsecond line',
])
def test_json_cut_off_by_the_web_tool_still_yields_the_text_so_far(cut):
    raw = '{"batchcomplete":true,"query":{"pages":[{"pageid":1,"ns":0,"title":"T","extract":"' + cut
    text = article_text(raw, "T")
    assert text.startswith(("unterminated text", "text that ends", "text with escaped")) and "\\u00" not in text.replace("é", "")


def test_a_complete_reply_wins_over_the_cut_off_fallback():
    assert article_text(extract_json("T", 'He said "stop" and left'), "T") == 'He said "stop" and left'


# ── research end to end ─────────────────────────────────────────────────────

def test_a_research_step_over_wikipedia_stores_facts_with_the_article_address(project):
    article = "Clerks of the period copied documents by hand. Records were kept in bound ledgers and checked each quarter."
    web = WikipediaWebClient(FakeWebClient(pages={
        SEARCH.format(q=quote_plus("clerks ledgers"), n=5): search_json("Ledger"),
        EXTRACT.format(lang="en", t="Ledger"): extract_json("Ledger", article),
    }), "en", 5)
    questions = '{"questions": [{"question": "How were records kept?", "query": "clerks ledgers", "sensitive": false}]}'
    facts = ('{"facts": [{"claim": "Records were kept in bound ledgers.", "quote": "Records were kept in bound ledgers and checked each quarter"},'
             ' {"claim": "Invented.", "quote": "this sentence is not in the article text at all"}]}')
    llm = RuleLLM([("Decide what the author needs", questions), ("Source page: https://en.wikipedia.org/wiki/Ledger", facts),
                   ("Which of these facts directly answer", '{"keep": [1, 2, 3]}')])
    outcome = run_research(StepContext(project, "series_north_star", llm, web), "series", "Background.", "# The Ledger\nA story.")
    assert (outcome.asked, outcome.answered, outcome.facts) == (1, 1, 1)
    [fact] = stores_for(project)["series"].facts()
    assert fact.url == "https://en.wikipedia.org/wiki/Ledger" and fact.claim == "Records were kept in bound ledgers."
    assert fact.quote in article


# ── configuration and the doctor ────────────────────────────────────────────

def test_auto_is_the_default_source_and_the_language_is_validated(tmp_path):
    cfg = Config()
    assert cfg.research.source == "auto" and cfg.research.wikipedia_language == "en"
    host = tmp_path / "host.yaml"
    for bad in ("EN", "e/vil", "en.evil.example", ""):
        host.write_text(f'research:\n  wikipedia_language: "{bad}"\n')
        with pytest.raises(ConfigError):
            load_config(host_path=host)
    host.write_text("research:\n  source: duckduckgo\n  wikipedia_language: de\n")
    assert load_config(host_path=host).research.source == "duckduckgo"
    host.write_text("research:\n  source: bing\n")
    with pytest.raises(ConfigError):
        load_config(host_path=host)


def test_the_doctor_probes_search_and_says_which_source_failed():
    good = FakeWebClient(pages={"https://example.com": "Example"}, searches={"history": "r"},
                         links={"history": [{"text": "History", "href": "https://en.wikipedia.org/wiki/History"}]})
    wiki = Research(source="wikipedia")
    checks = {c.name: c for c in check_web(good, research=wiki)}
    assert checks["web_search"].level == "pass" and "1 result(s) for 'history' from wikipedia" in checks["web_search"].detail
    blocked = FakeWebClient(pages={"https://example.com": "Example"}, searches={"history": "If this persists, please email us."})
    c = {x.name: x for x in check_web(blocked, research=wiki)}["web_search"]
    assert c.level == "fail" and "research source 'wikipedia' returned no usable results" in c.detail and "blocked or empty" in c.detail


def test_the_doctor_search_probe_can_be_skipped():
    assert "web_search" not in {c.name for c in check_web(FakeWebClient(), fetch=False)}


def test_a_model_name_without_latest_is_accepted_for_ollama():
    models = httpx.Response(200, json={"data": [{"id": "llama3.3-bookforge:latest"}, {"id": "other:7b"}]})
    t = httpx.MockTransport(lambda r: models)
    ok = check_models_endpoint("writer", ModelEndpoint(base_url="http://x/v1", model="llama3.3-bookforge"), t)
    assert ok.level == "pass"
    exact = check_models_endpoint("writer", ModelEndpoint(base_url="http://x/v1", model="llama3.3-bookforge:latest"), t)
    assert exact.level == "pass"
    missing = check_models_endpoint("writer", ModelEndpoint(base_url="http://x/v1", model="other"), t)
    assert missing.level == "fail"  # 'other' has no ':latest' entry, only 'other:7b'
