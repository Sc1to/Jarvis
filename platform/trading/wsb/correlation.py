"""
WSB correlation engine — 13.8
Checks whether the same ticker has both a recent DD signal and a mention spike.
If both are present within their respective windows, emits a combined signal
with higher weight than either source alone.

Called at the end of each monitor_wsb scheduler tick.
"""
import json
import logging
import sqlite3

from db import DB_PATH

log = logging.getLogger(__name__)

DD_WINDOW_HOURS = 24      # look for DD signals within this window
MENTION_WINDOW_HOURS = 2  # look for mention spikes within this window
COMBINED_STRENGTH_BONUS = 15.0  # added to the higher individual signal strength


def run():
    """Find tickers with both a DD signal and a mention spike in their respective windows."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        dd_tickers = _recent_dd_tickers(conn)
        mention_tickers = _recent_mention_tickers(conn)

        correlated = dd_tickers & mention_tickers
        if not correlated:
            return

        for ticker in correlated:
            if _already_emitted(conn, ticker):
                continue
            _emit_correlation_signal(conn, ticker)
            log.info("CORRELATION signal: %s (DD + mention spike)", ticker)

        conn.commit()
    finally:
        conn.close()


def _recent_dd_tickers(conn) -> set[str]:
    """Tickers with a wsb_dd signal in the last DD_WINDOW_HOURS hours."""
    rows = conn.execute(
        """SELECT DISTINCT ticker FROM trading_signals
           WHERE signal_type = 'wsb_dd'
           AND timestamp >= datetime('now', ? || ' hours')""",
        (f"-{DD_WINDOW_HOURS}",),
    ).fetchall()
    return {r["ticker"] for r in rows}


def _recent_mention_tickers(conn) -> set[str]:
    """Tickers with a wsb_mentions signal in the last MENTION_WINDOW_HOURS hours."""
    rows = conn.execute(
        """SELECT DISTINCT ticker FROM trading_signals
           WHERE signal_type = 'wsb_mentions'
           AND timestamp >= datetime('now', ? || ' hours')""",
        (f"-{MENTION_WINDOW_HOURS}",),
    ).fetchall()
    return {r["ticker"] for r in rows}


def _already_emitted(conn, ticker: str) -> bool:
    """Avoid duplicate correlation signals within the same window."""
    row = conn.execute(
        """SELECT id FROM trading_signals
           WHERE ticker = ? AND signal_type = 'wsb_correlation'
           AND timestamp >= datetime('now', '-2 hours')""",
        (ticker,),
    ).fetchone()
    return row is not None


def _emit_correlation_signal(conn, ticker: str):
    # Get the strongest individual signal for this ticker in their windows
    best = conn.execute(
        """SELECT MAX(strength) as max_strength, pool FROM trading_signals
           WHERE ticker = ?
           AND signal_type IN ('wsb_dd', 'wsb_mentions')
           AND timestamp >= datetime('now', ? || ' hours')
           GROUP BY pool
           ORDER BY max_strength DESC LIMIT 1""",
        (ticker, f"-{DD_WINDOW_HOURS}"),
    ).fetchone()

    if not best:
        return

    pool = best["pool"]
    combined_strength = min((best["max_strength"] or 0) + COMBINED_STRENGTH_BONUS, 100.0)

    conn.execute(
        """INSERT INTO trading_signals
           (pool, ticker, signal_type, direction, strength, metadata)
           VALUES (?, ?, 'wsb_correlation', 'BUY', ?, ?)""",
        (
            pool,
            ticker,
            combined_strength,
            json.dumps({"sources": ["wsb_dd", "wsb_mentions"], "bonus": COMBINED_STRENGTH_BONUS}),
        ),
    )
