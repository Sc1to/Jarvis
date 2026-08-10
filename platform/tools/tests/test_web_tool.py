from tools.web_tool import WebTool, _is_blocked


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
