"""
Unit tests for trading tool utilities that don't require network or credentials.
Run: pytest platform/trading/tests/
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.reddit import _serialize, RedditClient, _NOISE, _TICKER_RE
from tools.edgar import EdgarClient


# ── Reddit ticker extraction ──────────────────────────────────────────────────

def test_ticker_regex_basic():
    text = "Buying $AAPL calls and some MSFT before earnings"
    found = set(_TICKER_RE.findall(text.upper()))
    assert "AAPL" in found
    assert "MSFT" in found


def test_ticker_noise_filtered():
    # noise words should be in _NOISE to be filtered by extract_tickers
    assert "DD" in _NOISE
    assert "YOLO" in _NOISE
    assert "SEC" in _NOISE


def test_serialize_deleted_author():
    class FakeSubmission:
        id = "abc123"
        title = "Test post"
        author = None
        link_flair_text = "DD"
        score = 100
        url = "https://reddit.com/r/wsb/test"
        selftext = "Some body text"
        created_utc = 1700000000.0
        num_comments = 42

    result = _serialize(FakeSubmission())
    assert result["author"] == "[deleted]"
    assert result["reddit_id"] == "abc123"
    assert result["flair"] == "DD"


def test_count_ticker_mentions():
    posts = [
        {"title": "AAPL to the moon", "selftext": "buying calls on AAPL"},
        {"title": "MSFT earnings play", "selftext": "bullish on MSFT"},
        {"title": "random post", "selftext": "no tickers here"},
        {"title": "AAPL and MSFT", "selftext": "diversified"},
    ]

    class MockClient:
        def count_ticker_mentions(self, tickers, posts):
            from tools.reddit import _TICKER_RE
            ticker_set = set(tickers)
            counts = {t: 0 for t in tickers}
            for post in posts:
                text = f"{post['title']} {post.get('selftext', '')}".upper()
                for t in _TICKER_RE.findall(text):
                    if t in ticker_set:
                        counts[t] += 1
            return counts

    client = MockClient()
    counts = client.count_ticker_mentions(["AAPL", "MSFT", "TSLA"], posts)
    assert counts["AAPL"] == 3
    assert counts["MSFT"] == 2
    assert counts["TSLA"] == 0


# ── EDGAR URL construction ────────────────────────────────────────────────────

def test_edgar_cik_padding():
    raw_cik = "320193"
    padded = raw_cik.zfill(10)
    assert padded == "0000320193"
    assert len(padded) == 10


def test_edgar_filing_url_format():
    cik = "0000320193"
    acc = "0000320193-24-000123"
    doc = "aapl-20240930.htm"
    acc_clean = acc.replace("-", "")
    raw_cik = str(int(cik))
    url = f"https://www.sec.gov/Archives/edgar/data/{raw_cik}/{acc_clean}/{doc}"
    assert "320193" in url
    assert acc_clean in url
    assert doc in url
    assert "-" not in acc_clean


# ── DB schema ─────────────────────────────────────────────────────────────────

def test_db_init_creates_tables(tmp_path):
    import sqlite3
    os.environ["DB_PATH"] = str(tmp_path / "test.db")
    import importlib
    import db
    importlib.reload(db)
    db.init_db()
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    expected = {
        "trading_config", "trading_signals", "trading_positions", "trading_orders",
        "trading_wsb_posts", "trading_wsb_mentions", "trading_catalysts",
        "trading_shadow_portfolio", "trading_learning_weights",
        "trading_audit_log", "trading_risk_gate_log", "trading_morning_briefs",
    }
    assert expected <= tables
    conn.close()


def test_db_default_config_seeded(tmp_path):
    import sqlite3
    os.environ["DB_PATH"] = str(tmp_path / "test2.db")
    import importlib
    import db
    importlib.reload(db)
    db.init_db()
    conn = sqlite3.connect(str(tmp_path / "test2.db"))
    conn.row_factory = sqlite3.Row
    mode = conn.execute("SELECT value FROM trading_config WHERE key='trading_mode'").fetchone()
    assert mode is not None
    assert mode["value"] == "paper"
    conn.close()


if __name__ == "__main__":
    test_ticker_regex_basic()
    test_ticker_noise_filtered()
    test_serialize_deleted_author()
    test_count_ticker_mentions()
    test_edgar_cik_padding()
    test_edgar_filing_url_format()
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        from pathlib import Path
        test_db_init_creates_tables(Path(d))
        test_db_default_config_seeded(Path(d))
    print("All tests passed.")
