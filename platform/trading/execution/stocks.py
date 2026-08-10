"""
13.12 — trading_execution_stocks
Runs every 5 minutes. Picks up BUY conviction signals not yet acted on,
runs them through the risk gate, and places market orders via IBKR TWS.
Paper mode uses TWS port 7497 (real paper trading); falls back to local
simulation if TWS is not reachable.
"""
import logging
import math
import sqlite3

from db import DB_PATH, get_config
from risk_gate import run as risk_gate_run
from tools import ibkr

log = logging.getLogger(__name__)


def _pending_signals(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """BUY conviction signals from the last hour with no corresponding order."""
    return conn.execute(
        """
        SELECT s.*
        FROM trading_signals s
        WHERE s.pool = 'stocks'
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
           VALUES ('stocks', ?, 'BUY', 'market', ?, ?, ?, ?)""",
        (ticker, quantity, status, broker_order_id, signal_id),
    )
    return cur.lastrowid


def _insert_position(
    conn: sqlite3.Connection,
    ticker: str,
    quantity: float,
    entry_price: float,
    signal_id: int,
    order_id: int,
) -> None:
    conn.execute(
        """INSERT INTO trading_positions
           (pool, ticker, direction, status, quantity, entry_price, cost_basis, signal_id)
           VALUES ('stocks', ?, 'LONG', 'open', ?, ?, ?, ?)""",
        (ticker, quantity, entry_price, quantity * entry_price, signal_id),
    )


async def run() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        mode        = get_config(conn, "trading_mode") or "paper"
        max_pct     = float(get_config(conn, "max_position_pct") or 20)
        pool_ceiling = float(get_config(conn, "stocks_pool_ceiling") or 5000)

        pending = _pending_signals(conn)
        if not pending:
            return

        log.info("Stocks execution: %d pending BUY signals", len(pending))

        for sig in pending:
            ticker     = sig["ticker"]
            conviction = float(sig["conviction"] or 0)
            signal_id  = sig["id"]
            size       = _order_size_dollars(conviction, max_pct, pool_ceiling)

            current_price = await ibkr.get_price(ticker, mode)
            if not current_price:
                log.warning("Stocks execution: no price for %s — skipping", ticker)
                continue

            decision, rule = await risk_gate_run(
                pool="stocks",
                ticker=ticker,
                signal_id=signal_id,
                conviction=conviction,
                position_size_proposed=size,
                current_price=current_price,
            )

            if decision != "PASS":
                log.info("Stocks execution: %s blocked (%s)", ticker, rule)
                conn.execute(
                    """INSERT INTO trading_shadow_portfolio
                       (pool, ticker, reason_not_taken, rule_violated, signal_id, simulated_entry_price)
                       VALUES ('stocks', ?, ?, ?, ?, ?)""",
                    (ticker, rule or "risk_gate", rule, signal_id, current_price),
                )
                conn.commit()
                continue

            quantity = math.floor(size / current_price)
            if quantity < 1:
                log.info("Stocks execution: order too small for %s — skipping", ticker)
                continue

            try:
                if mode == "paper":
                    try:
                        broker_id, fill_price = await ibkr.place_order(ticker, "BUY", quantity, "paper")
                        status = "filled"
                    except Exception:
                        # TWS not reachable — simulate locally
                        broker_id, fill_price, status = None, current_price, "simulated"
                else:
                    broker_id, fill_price = await ibkr.place_order(ticker, "BUY", quantity, "live")
                    status = "filled" if fill_price else "pending"

                order_id = _insert_order(conn, ticker, quantity, signal_id, broker_id, status)
                _insert_position(conn, ticker, quantity, fill_price or current_price, signal_id, order_id)
                conn.commit()
                log.info(
                    "Stocks order: %s mode=%s qty=%d @ %.2f broker_id=%s",
                    ticker, mode, quantity, fill_price or current_price, broker_id,
                )
            except Exception:
                conn.rollback()
                log.exception("Stocks execution failed for %s", ticker)

    except Exception:
        log.exception("Stocks execution run failed")
    finally:
        conn.close()
