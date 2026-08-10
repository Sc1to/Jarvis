"""
13.13 — trading_position_manager
Runs every 15 minutes. For every open position:
  - fetches current market price from the appropriate broker
  - updates unrealised_pnl, current_price, trailing_stop
  - if trailing stop hit: closes the position and places an exit order

Exit orders bypass the conviction pipeline and the risk gate — they are
protective actions, not entry decisions.

Paper mode: prices are fetched from the broker (for accuracy) but exit orders
are simulated without actually calling the broker's order API.
"""
import asyncio
import logging
import sqlite3
import uuid
from typing import Optional

from db import DB_PATH, get_config
from tools import ibkr
from tools.coinbase import CoinbaseClient

log = logging.getLogger(__name__)


# ── Pure trailing-stop logic (no I/O) ────────────────────────────────────────

def compute_stop(price: float, trailing_pct: float) -> float:
    """Stop level for a given price and trailing percentage."""
    return round(price * (1 - trailing_pct / 100), 6)


def raise_stop(current_stop: Optional[float], price: float, trailing_pct: float) -> float:
    """
    Returns the new stop level. Stops only move up — never down.
    If no prior stop exists, initialises from current price.
    """
    candidate = compute_stop(price, trailing_pct)
    if current_stop is None:
        return candidate
    return max(current_stop, candidate)


def should_exit(current_price: float, trailing_stop: Optional[float]) -> bool:
    """True when price has fallen to or below the trailing stop."""
    if trailing_stop is None:
        return False
    return current_price <= trailing_stop


def unrealised_pnl(entry_price: float, current_price: float, quantity: float) -> float:
    return round((current_price - entry_price) * quantity, 6)


def realised_pnl(entry_price: float, exit_price: float, quantity: float) -> float:
    return round((exit_price - entry_price) * quantity, 6)


# ── DB helpers ────────────────────────────────────────────────────────────────

def _open_positions(conn: sqlite3.Connection, pool: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM trading_positions WHERE pool = ? AND status = 'open'",
        (pool,),
    ).fetchall()


def _update_position_price(
    conn: sqlite3.Connection,
    pos_id: int,
    current_price: float,
    new_stop: float,
    upnl: float,
) -> None:
    conn.execute(
        """UPDATE trading_positions
           SET current_price = ?, trailing_stop = ?, unrealised_pnl = ?
           WHERE id = ?""",
        (current_price, new_stop, upnl, pos_id),
    )


def _close_position(
    conn: sqlite3.Connection,
    pos_id: int,
    exit_price: float,
    rpnl: float,
) -> None:
    conn.execute(
        """UPDATE trading_positions
           SET status = 'closed', exit_price = ?, realised_pnl = ?,
               unrealised_pnl = 0, closed_at = datetime('now')
           WHERE id = ?""",
        (exit_price, rpnl, pos_id),
    )


def _log_exit_order(
    conn: sqlite3.Connection,
    pool: str,
    ticker: str,
    quantity: float,
    fill_price: float,
    broker_order_id: Optional[str],
    status: str,
    position_id: int,
) -> None:
    conn.execute(
        """INSERT INTO trading_orders
           (pool, ticker, direction, order_type, quantity, status,
            broker_order_id, fill_price, position_id, filled_at)
           VALUES (?, ?, 'SELL', 'market', ?, ?, ?, ?, ?, datetime('now'))""",
        (pool, ticker, quantity, status, broker_order_id, fill_price, position_id),
    )


# ── Stock positions ───────────────────────────────────────────────────────────

async def _prices_stocks(
    positions: list[sqlite3.Row],
    mode: str,
) -> dict[str, float]:
    """Batch price fetch via TWS. Returns {ticker: price}."""
    tickers = [pos["ticker"] for pos in positions]
    try:
        return await ibkr.get_prices(tickers, mode)
    except Exception as exc:
        log.warning("IBKR price fetch failed: %s", exc)
        return {}


async def _exit_stocks_live(
    conn: sqlite3.Connection,
    pos: sqlite3.Row,
    exit_price: float,
    mode: str,
) -> None:
    broker_id = None
    try:
        broker_id, _ = await ibkr.place_order(pos["ticker"], "SELL", pos["quantity"], mode)
    except Exception as exc:
        log.error("IBKR exit order failed for %s: %s", pos["ticker"], exc)
    _log_exit_order(conn, "stocks", pos["ticker"], pos["quantity"], exit_price, broker_id, "filled", pos["id"])
    _close_position(conn, pos["id"], exit_price, realised_pnl(pos["entry_price"], exit_price, pos["quantity"]))


async def _process_stocks(
    conn: sqlite3.Connection,
    mode: str,
    trailing_pct: float,
) -> None:
    positions = _open_positions(conn, "stocks")
    if not positions:
        return

    prices = await _prices_stocks(positions, mode)

    for pos in positions:
        ticker = pos["ticker"]
        current_price = prices.get(ticker)

        if current_price is None:
            log.debug("No price for stocks position %s — skipping", ticker)
            continue

        new_stop = raise_stop(pos["trailing_stop"], current_price, trailing_pct)
        upnl = unrealised_pnl(pos["entry_price"], current_price, pos["quantity"])
        _update_position_price(conn, pos["id"], current_price, new_stop, upnl)

        if should_exit(current_price, new_stop):
            log.info("Trailing stop hit: %s @ %.2f (stop=%.2f)", ticker, current_price, new_stop)
            rpnl = realised_pnl(pos["entry_price"], current_price, pos["quantity"])
            if mode == "paper":
                _log_exit_order(conn, "stocks", ticker, pos["quantity"], current_price, None, "simulated", pos["id"])
                _close_position(conn, pos["id"], current_price, rpnl)
            else:
                await _exit_stocks_live(conn, pos, current_price, mode)

    conn.commit()


# ── Crypto positions ──────────────────────────────────────────────────────────

def _prices_crypto_sync(
    client: CoinbaseClient,
    product_ids: list[str],
) -> dict[str, float]:
    """Batch price fetch via Coinbase. Returns {product_id: price}."""
    try:
        pricebooks = client.get_best_bid_ask(product_ids)
        prices: dict[str, float] = {}
        for pid, pb in pricebooks.items():
            asks = pb.get("asks", [])
            bids = pb.get("bids", [])
            raw = (asks[0].get("price") if asks else None) or (bids[0].get("price") if bids else None)
            if raw:
                try:
                    prices[pid] = float(raw)
                except (TypeError, ValueError):
                    pass
        return prices
    except Exception as exc:
        log.warning("Coinbase price fetch failed: %s", exc)
        return {}


def _exit_crypto_live_sync(client: CoinbaseClient, pos: sqlite3.Row, exit_price: float) -> str:
    ticker = pos["ticker"]
    product_id = ticker if "-" in ticker else f"{ticker}-USD"
    base_size = f"{pos['quantity']:.8f}"
    resp = client.place_market_order(uuid.uuid4().hex, product_id, "SELL", base_size)
    return resp.get("order_id") or resp.get("id") or ""


async def _process_crypto(
    conn: sqlite3.Connection,
    mode: str,
    api_key_name: str,
    api_private_key: str,
    trailing_pct: float,
) -> None:
    positions = _open_positions(conn, "crypto")
    if not positions:
        return

    product_ids = [
        (p["ticker"] if "-" in p["ticker"] else f"{p['ticker']}-USD")
        for p in positions
    ]
    # map product_id → pos for price lookup
    pid_map = {
        (p["ticker"] if "-" in p["ticker"] else f"{p['ticker']}-USD"): p
        for p in positions
    }

    prices: dict[str, float] = {}
    if api_key_name and api_private_key:
        client = CoinbaseClient(api_key_name, api_private_key)
        prices = await asyncio.to_thread(_prices_crypto_sync, client, product_ids)

    for product_id, pos in pid_map.items():
        ticker = pos["ticker"]
        current_price = prices.get(product_id)

        if current_price is None:
            log.debug("No price for crypto position %s — skipping", ticker)
            continue

        new_stop = raise_stop(pos["trailing_stop"], current_price, trailing_pct)
        upnl = unrealised_pnl(pos["entry_price"], current_price, pos["quantity"])
        _update_position_price(conn, pos["id"], current_price, new_stop, upnl)

        if should_exit(current_price, new_stop):
            log.info("Trailing stop hit: %s @ %.4f (stop=%.4f)", ticker, current_price, new_stop)
            rpnl = realised_pnl(pos["entry_price"], current_price, pos["quantity"])
            if mode == "paper" or not (api_key_name and api_private_key):
                _log_exit_order(conn, "crypto", ticker, pos["quantity"], current_price, None, "simulated", pos["id"])
                _close_position(conn, pos["id"], current_price, rpnl)
            else:
                client = CoinbaseClient(api_key_name, api_private_key)
                broker_id = await asyncio.to_thread(_exit_crypto_live_sync, client, pos, current_price)
                _log_exit_order(conn, "crypto", ticker, pos["quantity"], current_price, broker_id or None, "filled", pos["id"])
                _close_position(conn, pos["id"], current_price, rpnl)

    conn.commit()


# ── Entry point ───────────────────────────────────────────────────────────────

async def run() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        mode            = get_config(conn, "trading_mode") or "paper"
        api_key_name    = get_config(conn, "coinbase_api_key_name") or ""
        api_private_key = get_config(conn, "coinbase_api_private_key") or ""
        trailing_pct    = float(get_config(conn, "trailing_stop_pct") or 5)

        await _process_stocks(conn, mode, trailing_pct)
        await _process_crypto(conn, mode, api_key_name, api_private_key, trailing_pct)

    except Exception:
        conn.rollback()
        log.exception("Position manager run failed")
    finally:
        conn.close()
