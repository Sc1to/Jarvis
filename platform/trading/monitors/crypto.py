"""
trading_monitor_crypto — 13.7
Runs within the trading service via APScheduler (every 5 minutes, all hours).
Crypto markets never close, so no market-hours gate.
Fetches OHLCV candles from Coinbase, calculates momentum, emits raw signals.
"""
import asyncio
import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

from db import DB_PATH
from monitors.momentum import (
    calculate_price_momentum,
    calculate_rsi,
    calculate_volume_ratio,
    score_signal,
)
from monitors.universe import get_active_tickers
from tools.coinbase import CoinbaseClient

log = logging.getLogger(__name__)

# Coinbase candle fields differ slightly — map to standard keys
_GRANULARITY = "FIVE_MINUTE"
_LOOKBACK_HOURS = 4  # fetch last 4 hours of 5-min candles = 48 bars


def _candle_to_bar(c: dict) -> dict:
    """Normalise a Coinbase candle dict to the same shape used by momentum functions."""
    return {
        "t": c.get("start"),
        "o": float(c.get("open", 0)),
        "h": float(c.get("high", 0)),
        "l": float(c.get("low", 0)),
        "c": float(c.get("close", 0)),
        "v": float(c.get("volume", 0)),
    }


def run():
    """Entry point called by scheduler every 5 minutes (sync wrapper)."""
    products = get_active_tickers("crypto")
    if not products:
        log.warning("Crypto universe is empty — nothing to monitor")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        key_row = conn.execute(
            "SELECT value FROM trading_config WHERE key = 'coinbase_api_key_name'"
        ).fetchone()
        secret_row = conn.execute(
            "SELECT value FROM trading_config WHERE key = 'coinbase_api_private_key'"
        ).fetchone()
    finally:
        conn.close()

    api_key = key_row["value"] if key_row else ""
    api_secret = secret_row["value"] if secret_row else ""

    if not api_key or not api_secret:
        log.warning("Coinbase credentials not configured — crypto monitor skipped")
        return

    client = CoinbaseClient(api_key, api_secret)
    if not client.check_auth():
        log.warning("Coinbase auth failed — crypto monitor skipped")
        return

    now = datetime.now(timezone.utc)
    start_ts = str(int((now - timedelta(hours=_LOOKBACK_HOURS)).timestamp()))
    end_ts = str(int(now.timestamp()))

    for row in products:
        product_id = row["ticker"]  # stored as 'BTC-USD' etc.
        try:
            _process_product(client, product_id, start_ts, end_ts)
        except Exception as e:
            log.error("Crypto monitor error for %s: %s", product_id, e)


def _process_product(client: CoinbaseClient, product_id: str, start_ts: str, end_ts: str):
    candles = client.get_candles(product_id, _GRANULARITY, start_ts, end_ts)
    bars = [_candle_to_bar(c) for c in candles]

    if len(bars) < 20:
        return

    closes = [b["c"] for b in bars]
    volumes = [b["v"] for b in bars]

    rsi = calculate_rsi(closes)
    vol_ratio = calculate_volume_ratio(volumes)
    mom_5 = calculate_price_momentum(closes, lookback=5)
    mom_20 = calculate_price_momentum(closes, lookback=20)

    direction, strength = score_signal(rsi, vol_ratio, mom_5, mom_20)

    if direction == "NEUTRAL":
        return

    # Ticker stored as 'BTC-USD'; we strip '-USD' for signal clarity
    ticker = product_id.replace("-USD", "")
    _emit_signal(
        ticker=ticker,
        product_id=product_id,
        direction=direction,
        strength=strength,
        indicators={"rsi": rsi, "vol_ratio": vol_ratio, "mom_5": mom_5, "mom_20": mom_20},
    )
    log.info("CRYPTO signal: %s %s strength=%.1f rsi=%.1f vol_ratio=%.2f",
             direction, product_id, strength, rsi, vol_ratio)


def _emit_signal(ticker: str, product_id: str, direction: str, strength: float, indicators: dict):
    meta = {**indicators, "product_id": product_id}
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            """INSERT INTO trading_signals
               (pool, ticker, signal_type, direction, strength, metadata)
               VALUES ('crypto', ?, 'momentum', ?, ?, ?)""",
            (ticker, direction, strength, json.dumps(meta)),
        )
        conn.commit()
    except Exception as e:
        log.error("Failed to write signal for %s: %s", ticker, e)
    finally:
        conn.close()
