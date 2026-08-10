"""
13.12 — trading_execution_crypto
Runs every 5 minutes. Picks up BUY conviction signals for the crypto pool,
runs them through the risk gate, and places market orders via Coinbase.
In paper mode: simulates fills without touching the broker.
coinbase-advanced-py is synchronous — broker calls are wrapped in asyncio.to_thread.
"""
import asyncio
import json
import logging
import sqlite3
import uuid

from db import DB_PATH, get_config
from risk_gate import run as risk_gate_run
from tools.coinbase import CoinbaseClient

log = logging.getLogger(__name__)

_CRYPTO_PRECISION = 8  # decimal places for base asset quantity


def _pending_signals(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """BUY conviction signals for crypto from the last hour with no corresponding order."""
    return conn.execute(
        """
        SELECT s.*
        FROM trading_signals s
        WHERE s.pool = 'crypto'
          AND s.signal_type = 'conviction'
          AND s.action = 'BUY'
          AND s.timestamp >= datetime('now', '-1 hour')
          AND NOT EXISTS (
              SELECT 1 FROM trading_orders o WHERE o.signal_id = s.id
          )
        ORDER BY s.conviction DESC
        """
    ).fetchall()


def _order_size_dollars(conviction: float, max_position_pct: float, pool_ceiling: float) -> float:
    return (conviction / 100) * (max_position_pct / 100) * pool_ceiling


def _ticker_to_product(ticker: str) -> str:
    """'BTC' → 'BTC-USD'. Already 'BTC-USD' → unchanged."""
    return ticker if "-" in ticker else f"{ticker}-USD"


def _insert_order(
    conn: sqlite3.Connection,
    ticker: str,
    quantity: float,
    signal_id: int,
    broker_order_id: str | None,
    status: str,
) -> int:
    cur = conn.execute(
        """INSERT INTO trading_orders
           (pool, ticker, direction, order_type, quantity, status, broker_order_id, signal_id)
           VALUES ('crypto', ?, 'BUY', 'market', ?, ?, ?, ?)""",
        (ticker, quantity, status, broker_order_id, signal_id),
    )
    return cur.lastrowid


def _insert_position(
    conn: sqlite3.Connection,
    ticker: str,
    quantity: float,
    entry_price: float,
    signal_id: int,
) -> None:
    cost_basis = quantity * entry_price
    conn.execute(
        """INSERT INTO trading_positions
           (pool, ticker, direction, status, quantity, entry_price, cost_basis, signal_id)
           VALUES ('crypto', ?, 'LONG', 'open', ?, ?, ?, ?)""",
        (ticker, quantity, entry_price, cost_basis, signal_id),
    )


def _get_price_sync(client: CoinbaseClient, product_id: str) -> float | None:
    try:
        pricebooks = client.get_best_bid_ask([product_id])
        pb = pricebooks.get(product_id, {})
        asks = pb.get("asks", [])
        if asks:
            return float(asks[0].get("price", 0))
        bids = pb.get("bids", [])
        if bids:
            return float(bids[0].get("price", 0))
    except Exception as exc:
        log.warning("Coinbase price fetch failed for %s: %s", product_id, exc)
    return None


async def _execute_paper(
    conn: sqlite3.Connection,
    ticker: str,
    conviction: float,
    signal_id: int,
    max_position_pct: float,
    pool_ceiling: float,
    current_price: float | None,
) -> None:
    """Simulate fill in paper mode — no broker call."""
    if current_price is None or current_price <= 0:
        log.warning("Paper crypto: no price for %s — skipping", ticker)
        return
    size = _order_size_dollars(conviction, max_position_pct, pool_ceiling)
    quantity = round(size / current_price, _CRYPTO_PRECISION)
    if quantity <= 0:
        log.info("Paper crypto: size too small for %s (%.2f) — skipping", ticker, size)
        return
    order_id = _insert_order(conn, ticker, quantity, signal_id, None, "simulated")
    _insert_position(conn, ticker, quantity, current_price, signal_id)
    conn.commit()
    log.info(
        "PAPER crypto order: %s qty=%.8f @ %.4f (conviction=%.1f)",
        ticker, quantity, current_price, conviction,
    )


def _place_coinbase_order(client: CoinbaseClient, product_id: str, quantity: float) -> dict:
    base_size = f"{quantity:.{_CRYPTO_PRECISION}f}"
    return client.place_market_order(
        client_order_id=uuid.uuid4().hex,
        product_id=product_id,
        side="BUY",
        base_size=base_size,
    )


def _get_coinbase_order(client: CoinbaseClient, order_id: str) -> dict:
    return client.get_order(order_id)


async def _execute_live(
    conn: sqlite3.Connection,
    ticker: str,
    conviction: float,
    signal_id: int,
    api_key_name: str,
    api_private_key: str,
    max_position_pct: float,
    pool_ceiling: float,
    current_price: float,
) -> None:
    """Place a real market order via Coinbase."""
    product_id = _ticker_to_product(ticker)
    size = _order_size_dollars(conviction, max_position_pct, pool_ceiling)
    quantity = round(size / current_price, _CRYPTO_PRECISION)
    if quantity <= 0:
        log.info("Live crypto: size too small for %s — skipping", ticker)
        return

    client = CoinbaseClient(api_key_name, api_private_key)

    response = await asyncio.to_thread(_place_coinbase_order, client, product_id, quantity)

    if "error" in response:
        log.error("Coinbase order failed for %s: %s", ticker, response["error"])
        return

    broker_order_id = response.get("order_id") or response.get("id") or ""
    order_id = _insert_order(conn, ticker, quantity, signal_id, broker_order_id, "pending")
    conn.commit()

    # Poll for fill
    fill_price = current_price
    if broker_order_id:
        await asyncio.sleep(3)
        try:
            order_data = await asyncio.to_thread(_get_coinbase_order, client, broker_order_id)
            if order_data.get("status") == "FILLED":
                avg = order_data.get("average_filled_price")
                fill_price = float(avg) if avg else current_price
                conn.execute(
                    "UPDATE trading_orders SET status='filled', fill_price=?, filled_at=datetime('now') WHERE id=?",
                    (fill_price, order_id),
                )
        except Exception as exc:
            log.warning("Coinbase order status poll failed for %s: %s", ticker, exc)

    _insert_position(conn, ticker, quantity, fill_price, signal_id)
    conn.commit()
    log.info(
        "LIVE crypto order: %s qty=%.8f @ %.4f broker_id=%s",
        ticker, quantity, fill_price, broker_order_id,
    )


async def run() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        mode = get_config(conn, "trading_mode") or "paper"
        api_key_name     = get_config(conn, "coinbase_api_key_name") or ""
        api_private_key  = get_config(conn, "coinbase_api_private_key") or ""
        max_pct          = float(get_config(conn, "max_position_pct") or 20)
        pool_ceiling     = float(get_config(conn, "crypto_pool_ceiling") or 2000)

        if mode == "live" and (not api_key_name or not api_private_key):
            log.error("Crypto execution: live mode requires coinbase credentials in config")
            return

        pending = _pending_signals(conn)
        if not pending:
            return

        log.info("Crypto execution: %d pending BUY signals", len(pending))

        for sig in pending:
            ticker = sig["ticker"]
            conviction = float(sig["conviction"] or 0)
            signal_id = sig["id"]
            product_id = _ticker_to_product(ticker)
            size = _order_size_dollars(conviction, max_pct, pool_ceiling)

            # Get current price (needed for risk gate and order sizing)
            current_price: float | None = None
            if api_key_name and api_private_key:
                client = CoinbaseClient(api_key_name, api_private_key)
                current_price = await asyncio.to_thread(_get_price_sync, client, product_id)
            elif mode == "paper":
                # Paper mode without credentials: skip price fetch, will be caught below
                pass

            decision, rule = await risk_gate_run(
                pool="crypto",
                ticker=ticker,
                signal_id=signal_id,
                conviction=conviction,
                position_size_proposed=size,
                current_price=current_price,
            )

            if decision != "PASS":
                log.info("Crypto execution: %s blocked by risk gate (%s)", ticker, rule)
                conn.execute(
                    """INSERT INTO trading_shadow_portfolio
                       (pool, ticker, reason_not_taken, rule_violated, signal_id, simulated_entry_price)
                       VALUES ('crypto', ?, ?, ?, ?, ?)""",
                    (ticker, rule or "risk_gate", rule, signal_id, current_price),
                )
                conn.commit()
                continue

            try:
                if mode == "paper":
                    await _execute_paper(
                        conn, ticker, conviction, signal_id, max_pct, pool_ceiling, current_price
                    )
                else:
                    if current_price is None or current_price <= 0:
                        log.error("Live crypto: no price for %s — skipping", ticker)
                        continue
                    await _execute_live(
                        conn, ticker, conviction, signal_id,
                        api_key_name, api_private_key,
                        max_pct, pool_ceiling, current_price,
                    )
            except Exception:
                conn.rollback()
                log.exception("Crypto execution failed for %s", ticker)

    except Exception:
        log.exception("Crypto execution run failed")
    finally:
        conn.close()
