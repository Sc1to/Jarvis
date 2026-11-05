import asyncio

from tools.web_tool import MAX_LINKS, MIN_TEXT_CHARS, POLL_MS, POLL_STEP_MS, WebTool, _clean_links, _is_blocked, _page_text


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


# ── Pages that build themselves with scripts ──────────────────────────────────

class FakePage:
    """A page whose text is whatever `texts` gives on each read (the last one repeats). Records the waits."""

    def __init__(self, texts, idle_raises=False):
        self.texts, self.idle_raises = list(texts), idle_raises
        self.reads = 0
        self.idle_waits = 0
        self.sleeps = []

    async def evaluate(self, js):
        text = self.texts[min(self.reads, len(self.texts) - 1)]
        self.reads += 1
        return text

    async def wait_for_load_state(self, state, timeout):
        assert state == "networkidle"
        self.idle_waits += 1
        if self.idle_raises:
            raise TimeoutError("never went idle")

    async def wait_for_timeout(self, ms):
        self.sleeps.append(ms)


FULL = "Customs clerks recorded cargo. " * 10


def test_a_normal_page_is_read_at_once_without_any_waiting():
    page = FakePage([FULL])
    assert asyncio.run(_page_text(page)) == FULL
    assert page.reads == 1 and page.idle_waits == 0 and page.sleeps == []
    assert len(FULL) >= MIN_TEXT_CHARS


def test_a_nearly_empty_page_is_given_time_to_fill_in():
    page = FakePage(["", FULL])  # empty when its HTML has loaded, full once the scripts have run
    assert asyncio.run(_page_text(page)) == FULL
    assert page.idle_waits == 1 and page.sleeps == []  # it was full after the network settled: no extra polling


def test_text_that_appears_after_the_network_is_quiet_is_caught_by_polling():
    page = FakePage(["", "", "", FULL])
    assert asyncio.run(_page_text(page)) == FULL
    assert page.sleeps == [POLL_STEP_MS, POLL_STEP_MS]


def test_a_page_that_never_fills_in_is_returned_as_it_is_after_a_bounded_wait():
    page = FakePage(["tiny"])
    assert asyncio.run(_page_text(page)) == "tiny"
    assert page.idle_waits == 1 and sum(page.sleeps) == POLL_MS and len(page.sleeps) == POLL_MS // POLL_STEP_MS


def test_a_page_that_never_goes_quiet_does_not_stop_the_read():
    page = FakePage(["", FULL], idle_raises=True)
    assert asyncio.run(_page_text(page)) == FULL and page.idle_waits == 1


def test_whitespace_alone_does_not_count_as_text():
    page = FakePage(["   \n\n  ", FULL])
    assert asyncio.run(_page_text(page)) == FULL and page.idle_waits == 1
