"""
trading_monitor_stocks — 13.7
Runs every 5 minutes during market hours. Fetches OHLCV from TWS via ib_insync,
calculates momentum indicators, emits raw signals to trading_signals.
"""
import json
import logging
import sqlite3
from datetime import datetime, time
from zoneinfo import ZoneInfo

from db import DB_PATH, get_config
from monitors.momentum import (
    calculate_price_momentum,
    calculate_rsi,
    calculate_volume_ratio,
    extract_closes,
    extract_volumes,
    score_signal,
)
from monitors.universe import get_active_tickers
from tools import ibkr

log = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
_MARKET_OPEN  = time(9, 30)
_MARKET_CLOSE = time(16, 0)


def _is_market_hours() -> bool:
    now = datetime.now(ET)
    if now.weekday() >= 5:
        return False
    return _MARKET_OPEN <= now.time() <= _MARKET_CLOSE


async def run():
    if not _is_market_hours():
        return

    tickers = [row["ticker"] for row in get_active_tickers("stocks")]
    if not tickers:
        log.warning("Stock universe is empty — nothing to monitor")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        mode = get_config(conn, "trading_mode") or "paper"
    finally:
        conn.close()

    if not await ibkr.is_connected(mode):
        log.warning("TWS not connected — stock monitor skipped")
        return

    for ticker in tickers:
        try:
            await _process_ticker(ticker, mode)
        except Exception as exc:
            log.debug("Stock monitor failed for %s: %s", ticker, exc)


async def _process_ticker(ticker: str, mode: str):
    bars = await ibkr.get_history(ticker, mode)
    if len(bars) < 20:
        return

    closes  = extract_closes(bars)
    volumes = extract_volumes(bars)

    rsi       = calculate_rsi(closes)
    vol_ratio = calculate_volume_ratio(volumes)
    mom_5     = calculate_price_momentum(closes, lookback=5)
    mom_20    = calculate_price_momentum(closes, lookback=20)

    direction, strength = score_signal(rsi, vol_ratio, mom_5, mom_20)

    if direction == "NEUTRAL":
        return

    _emit_signal(
        ticker=ticker,
        direction=direction,
        strength=strength,
        indicators={"rsi": rsi, "vol_ratio": vol_ratio, "mom_5": mom_5, "mom_20": mom_20},
    )
    log.info("STOCKS signal: %s %s strength=%.1f rsi=%.1f vol_ratio=%.2f",
             direction, ticker, strength, rsi, vol_ratio)


def _emit_signal(ticker: str, direction: str, strength: float, indicators: dict):
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            """INSERT INTO trading_signals
               (pool, ticker, signal_type, direction, strength, metadata)
               VALUES ('stocks', ?, 'momentum', ?, ?, ?)""",
            (ticker, direction, strength, json.dumps(indicators)),
        )
        conn.commit()
    except Exception as exc:
        log.error("Failed to write signal for %s: %s", ticker, exc)
    finally:
        conn.close()
