import pytest

from bookforge.research.hits import extract_hits, search_hits
from bookforge.research.search import FakeWebClient, WebError


def ddg(target):
    from urllib.parse import quote
    return {"text": "result", "href": f"https://duckduckgo.com/l/?uddg={quote(target, safe='')}&rut=abc"}


def test_duckduckgo_redirects_are_unwrapped():
    hits = extract_hits([ddg("https://en.wikipedia.org/wiki/Clavicle_fracture")], 5)
    assert [h.url for h in hits] == ["https://en.wikipedia.org/wiki/Clavicle_fracture"]


def test_search_engine_own_links_are_ignored():
    links = [
        {"text": "home", "href": "https://duckduckgo.com/"},
        {"text": "next", "href": "https://html.duckduckgo.com/html/?q=x&s=30"},
        {"text": "help", "href": "https://duckduckgo.com/l/?uddg=https%3A%2F%2Fduckduckgo.com%2Fabout"},
        {"text": "no target", "href": "https://duckduckgo.com/l/"},
    ]
    assert extract_hits(links, 5) == []


def test_direct_links_are_kept_and_junk_is_dropped():
    links = [
        {"text": "A page", "href": "https://example.org/a"},
        {"text": "mail", "href": "mailto:x@example.org"},
        {"text": "js", "href": "javascript:void(0)"},
        {"text": "ftp", "href": "ftp://example.org/file"},
        {"text": "paper", "href": "https://example.org/paper.PDF"},
        {"text": "bad", "href": ""},
        {"text": "no href key"},
    ]
    assert [h.url for h in extract_hits(links, 5)] == ["https://example.org/a"]


def test_duplicates_fragments_and_limit():
    links = [ddg("https://a.example/x#top"), {"text": "again", "href": "https://a.example/x"},
             {"href": "https://b.example/"}, {"href": "https://c.example/"}]
    hits = extract_hits(links, 2)
    assert [h.url for h in hits] == ["https://a.example/x", "https://b.example/"]


def test_titles_are_tidied():
    assert extract_hits([{"text": "  Two\n  lines ", "href": "https://a.example/"}], 5)[0].title == "Two lines"


def test_a_block_page_is_reported_not_treated_as_an_answer():
    web = FakeWebClient(
        searches={"q": "If this persists, please email us.\nOur support email address includes an anonymized error code"},
        links={"q": [{"text": "email us", "href": "mailto:error-lite@duckduckgo.com"}]},
    )
    with pytest.raises(WebError, match="blocked or empty.*If this persists"):
        search_hits(web, "q", 5)


def test_search_hits_returns_usable_hits():
    web = FakeWebClient(searches={"q": "results"}, links={"q": [ddg("https://a.example/")]})
    assert [h.url for h in search_hits(web, "q", 5)] == ["https://a.example/"]
