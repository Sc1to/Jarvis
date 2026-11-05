from tools.web_tool import MAX_LINKS, WebTool, _clean_links, _is_blocked


# ── Blocking logic (pure Python, no Playwright needed) ────────────────────────

def test_blocks_post_requests():
    assert _is_blocked("POST", "https://example.com") is True


def test_blocks_put_requests():
    assert _is_blocked("PUT", "https://example.com") is True


def test_allows_get():
    assert _is_blocked("GET", "https://example.com") is False


def test_blocks_tracking_domain():
    assert _is_blocked("GET", "https://google-analytics.com/collect") is True
    assert _is_blocked("GET", "https://doubleclick.net/ad") is True


def test_allows_clean_domain():
    assert _is_blocked("GET", "https://python.org/docs") is False


# ── Tool interface ─────────────────────────────────────────────────────────────

def test_name_and_description():
    t = WebTool()
    assert t.name == "web"
    assert "playwright" in t.description.lower()


def test_unknown_op():
    t = WebTool()
    r = t.execute({"op": "teleport"})
    assert not r.success
    assert "Unknown op" in r.error


def test_playwright_not_installed_graceful(monkeypatch):
    import tools.web_tool as wt
    monkeypatch.setattr(wt, "_PLAYWRIGHT", False)
    t = WebTool()
    r = t.execute({"op": "fetch_page", "url": "https://example.com"})
    assert not r.success
    assert "playwright not installed" in r.error


# ── Link extraction ────────────────────────────────────────────────────────────

def test_clean_links_keeps_well_formed_pairs():
    raw = [{"text": "Docs", "href": "https://python.org/docs"}, {"href": "https://a.example"}]
    assert _clean_links(raw) == [
        {"text": "Docs", "href": "https://python.org/docs"},
        {"text": "", "href": "https://a.example"},
    ]


def test_clean_links_drops_malformed_entries():
    raw = ["x", None, {"text": "no href"}, {"href": ""}, {"href": 5}, {"text": 3, "href": "https://ok.example"}]
    assert _clean_links(raw) == [{"text": "", "href": "https://ok.example"}]
    assert _clean_links(None) == []
    assert _clean_links("not a list") == []


def test_clean_links_caps_count_and_size():
    raw = [{"text": "t" * 500, "href": f"https://x.example/{i}"} for i in range(MAX_LINKS + 50)]
    out = _clean_links(raw)
    assert len(out) == MAX_LINKS and len(out[0]["text"]) == 200
    assert len(_clean_links([{"href": "h" * 5000}])[0]["href"]) == 2000
