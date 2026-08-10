"""
Catalyst calendar fetcher — 13.9
Runs daily at 06:00 via APScheduler.

Sources:
  1. Alpha Vantage bulk earnings calendar (one request, all tickers, free tier).
  2. Expiry sweep: marks past 'upcoming' catalysts as 'resolved_unknown'
     so they don't keep triggering pre_catalyst state indefinitely.

Product launches and macro events (FOMC, CPI) are entered manually
via the POST /catalysts endpoint. FDA events are TBD.

Alpha Vantage key stored in trading_config: alphavantage_api_key.
Free tier: 25 req/day — this job uses exactly 1.
"""
import csv
import io
import logging
import sqlite3
from datetime import date

import httpx

from db import DB_PATH
from monitors.universe import get_active_tickers

log = logging.getLogger(__name__)

_AV_URL = "https://www.alphavantage.co/query"
_AV_HORIZON = "3month"


async def run():
    """Entry point called by scheduler daily at 06:00."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        api_key = conn.execute(
            "SELECT value FROM trading_config WHERE key = 'alphavantage_api_key'"
        ).fetchone()
    finally:
        conn.close()

    key = (api_key["value"] if api_key else "") or ""

    if key:
        await _fetch_earnings(key)
    else:
        log.warning("alphavantage_api_key not configured — earnings calendar skipped")

    _expire_past_catalysts()
    log.info("Catalyst calendar refresh complete")


async def _fetch_earnings(api_key: str):
    """Fetch bulk earnings calendar from Alpha Vantage and upsert into trading_catalysts."""
    universe_tickers = {r["ticker"] for r in get_active_tickers("stocks")}

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                _AV_URL,
                params={
                    "function": "EARNINGS_CALENDAR",
                    "horizon": _AV_HORIZON,
                    "apikey": api_key,
                },
            )
            r.raise_for_status()
            raw_csv = r.text
    except Exception as e:
        log.error("Alpha Vantage fetch failed: %s", e)
        return

    # Alpha Vantage returns CSV with header row
    reader = csv.DictReader(io.StringIO(raw_csv))
    inserted = 0
    conn = sqlite3.connect(DB_PATH)
    try:
        for row in reader:
            ticker = (row.get("symbol") or "").upper()
            report_date = row.get("reportDate", "").strip()

            if not ticker or not report_date or ticker not in universe_tickers:
                continue

            try:
                date.fromisoformat(report_date)  # validate format
            except ValueError:
                continue

            try:
                conn.execute(
                    """INSERT OR IGNORE INTO trading_catalysts
                       (ticker, catalyst_type, description, event_date, source)
                       VALUES (?, 'earnings', ?, ?, 'alphavantage')""",
                    (
                        ticker,
                        f"Q{_fiscal_quarter(row.get('fiscalDateEnding', ''))} earnings",
                        report_date,
                    ),
                )
                inserted += conn.execute("SELECT changes()").fetchone()[0]
            except Exception as e:
                log.debug("Insert failed for %s %s: %s", ticker, report_date, e)

        conn.commit()
    finally:
        conn.close()

    log.info("Earnings calendar: %d new entries inserted", inserted)


def _expire_past_catalysts():
    """
    Any catalyst with event_date < today and temporal_state = 'upcoming'
    is auto-expired to 'resolved_unknown'. The user should set it to
    resolved_positive or resolved_negative via the API once they know the outcome.
    """
    today = date.today().isoformat()
    conn = sqlite3.connect(DB_PATH)
    try:
        result = conn.execute(
            """UPDATE trading_catalysts
               SET temporal_state = 'resolved_unknown',
                   outcome_notes = 'Auto-expired: event date passed without manual resolution'
               WHERE temporal_state = 'upcoming'
               AND event_date < ?""",
            (today,),
        )
        if result.rowcount:
            log.info("Expired %d past catalysts → resolved_unknown", result.rowcount)
        conn.commit()
    finally:
        conn.close()


def _fiscal_quarter(fiscal_end: str) -> str:
    """Best-effort quarter label from fiscal period ending date."""
    if not fiscal_end:
        return "?"
    try:
        month = int(fiscal_end[5:7])
        return str(((month - 1) // 3) + 1)
    except (ValueError, IndexError):
        return "?"
