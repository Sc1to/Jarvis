"""
trading_wsb_mentions — 13.8
Tracks ticker mention velocity across all WSB posts (not just DD).
Velocity spikes (3× baseline) emit mention signals to trading_signals.
"""
import json
import logging
import sqlite3
from datetime import datetime, timezone

from db import DB_PATH
from monitors.universe import get_active_tickers
from tools.reddit import RedditClient

log = logging.getLogger(__name__)

SPIKE_THRESHOLD = 3.0        # spike_factor >= this triggers a signal
BASELINE_WINDOWS = 14        # number of past windows to average for baseline
_POSTS_HOT = 100
_POSTS_NEW = 200


def run():
    """Entry point called by scheduler every 30 minutes."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        client_id = _cfg(conn, "reddit_client_id")
        client_secret = _cfg(conn, "reddit_client_secret")
        user_agent = _cfg(conn, "reddit_user_agent") or "platform-trading/1.0"
    finally:
        conn.close()

    if not client_id or not client_secret:
        log.warning("Reddit credentials not configured — mention tracker skipped")
        return

    reddit = RedditClient(client_id, client_secret, user_agent)

    try:
        posts = reddit.get_hot_posts(_POSTS_HOT) + reddit.get_new_posts(_POSTS_NEW)
    except Exception as e:
        log.error("Reddit fetch failed: %s", e)
        return

    # Build a de-duplicated universe of all ticker symbols
    stock_rows = get_active_tickers("stocks")
    crypto_rows = get_active_tickers("crypto")
    # Crypto stored as 'BTC-USD' — strip to just the symbol for text matching
    crypto_symbols = [r["ticker"].replace("-USD", "") for r in crypto_rows]
    tickers = [r["ticker"] for r in stock_rows] + crypto_symbols

    counts = reddit.count_ticker_mentions(tickers, posts)
    now_iso = datetime.now(timezone.utc).isoformat()

    signals_emitted = 0
    for ticker, count in counts.items():
        baseline = _get_baseline(ticker)
        velocity = calculate_velocity(count, baseline)
        spike_factor = calculate_spike_factor(count, baseline)

        _record_mention(ticker, count, velocity, baseline, spike_factor, now_iso)

        if spike_factor >= SPIKE_THRESHOLD and count > 0:
            _emit_signal(ticker, count, velocity, baseline, spike_factor)
            signals_emitted += 1
            log.info("MENTIONS spike: %s count=%d spike_factor=%.1f", ticker, count, spike_factor)

    log.debug("Mention tracker: %d tickers scanned, %d spikes", len(tickers), signals_emitted)


# ── Pure math (testable without DB) ──────────────────────────────────────────

def calculate_velocity(current_count: int, baseline: float) -> float:
    """Percent change vs baseline. Returns 0 if baseline is zero."""
    if baseline <= 0:
        return 0.0
    return round((current_count - baseline) / baseline * 100.0, 2)


def calculate_spike_factor(current_count: int, baseline: float) -> float:
    """Ratio of current to baseline. Returns 1.0 if baseline is zero."""
    if baseline <= 0:
        return 1.0
    return round(current_count / baseline, 3)


# ── DB operations ─────────────────────────────────────────────────────────────

def _get_baseline(ticker: str) -> float:
    """Average mention_count per window over the last BASELINE_WINDOWS windows."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """SELECT mention_count FROM trading_wsb_mentions
               WHERE ticker = ?
               ORDER BY id DESC LIMIT ?""",
            (ticker, BASELINE_WINDOWS),
        ).fetchall()
        if not rows:
            return 0.0
        return sum(r["mention_count"] for r in rows) / len(rows)
    finally:
        conn.close()


def _record_mention(
    ticker: str,
    count: int,
    velocity: float,
    baseline: float,
    spike_factor: float,
    window_end: str,
):
    conn = sqlite3.connect(DB_PATH)
    try:
        # window_start is 30 minutes before window_end (approximate)
        conn.execute(
            """INSERT INTO trading_wsb_mentions
               (ticker, mention_count, velocity, baseline, spike_factor, window_start, window_end)
               VALUES (?, ?, ?, ?, ?, datetime(?), datetime(?))""",
            (ticker, count, velocity, round(baseline, 2), spike_factor,
             window_end, window_end),
        )
        conn.commit()
    finally:
        conn.close()


def _emit_signal(ticker: str, count: int, velocity: float, baseline: float, spike_factor: float):
    # Map crypto symbols back to their pool (they were stored without -USD)
    pool = "crypto" if ticker in _CRYPTO_SYMBOLS else "stocks"
    meta = {
        "mention_count": count,
        "velocity": velocity,
        "baseline": round(baseline, 2),
        "spike_factor": spike_factor,
    }
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            """INSERT INTO trading_signals
               (pool, ticker, signal_type, direction, strength, metadata)
               VALUES (?, ?, 'wsb_mentions', 'BUY', ?, ?)""",
            (pool, ticker, min(spike_factor * 10, 100.0), json.dumps(meta)),
        )
        conn.commit()
    finally:
        conn.close()


def _cfg(conn, key: str) -> str:
    row = conn.execute("SELECT value FROM trading_config WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else ""


# Crypto symbols we track (without -USD suffix)
_CRYPTO_SYMBOLS = {
    "BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT", "MATIC",
    "UNI", "LTC", "BCH", "ATOM", "FIL", "ALGO", "NEAR", "APT", "ARB", "OP",
}
