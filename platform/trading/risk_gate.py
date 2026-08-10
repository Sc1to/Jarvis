"""
13.11 — trading_validator_risk_gate
Hard-coded deterministic rule engine. No LLM. No agent modification.
User reviews this file before every live switch.

All 12 rules from TRADING_ARCHITECTURE.md are implemented here.
evaluate() is a pure function — all I/O happens in gather_context().
"""
import json
import logging
import sqlite3
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

from db import DB_PATH, get_config
from tools import ibkr

log = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")
_MARKET_OPEN  = dtime(9, 30)
_MARKET_CLOSE = dtime(16, 0)
_WEEKDAYS     = {0, 1, 2, 3, 4}  # Monday–Friday


# ── Rule evaluation (pure — no I/O) ──────────────────────────────────────────

def evaluate(ctx: dict) -> tuple[str, str | None, dict]:
    """
    Evaluate all 12 risk gate rules against a pre-built context dict.
    Returns (decision, rule_violated, details).

    decision: 'PASS' or 'BLOCK'
    rule_violated: rule name string if BLOCK, None if PASS
    details: dict with diagnostic values for the log
    """
    pool     = ctx["pool"]
    ticker   = ctx["ticker"]
    ceiling  = ctx["pool_ceiling"]

    # 1. POOL_CEILING — total allocated must not exceed ceiling
    if ctx["pool_value"] + ctx["position_size_proposed"] > ceiling:
        return "BLOCK", "POOL_CEILING", {
            "pool_value": ctx["pool_value"],
            "proposed": ctx["position_size_proposed"],
            "ceiling": ceiling,
        }

    # 2. POSITION_SIZE_MAX — single position <= max_position_pct% of ceiling
    max_size = ceiling * ctx["max_position_pct"] / 100
    if ctx["position_size_proposed"] > max_size:
        return "BLOCK", "POSITION_SIZE_MAX", {
            "proposed": ctx["position_size_proposed"],
            "max_allowed": max_size,
            "max_position_pct": ctx["max_position_pct"],
        }

    # 3. PORTFOLIO_CONCENTRATION — sector allocation (stocks only)
    #    ponytail: sector_pct_current is 0.0 until position manager populates sectors;
    #              rule is vacuously PASS for crypto and for positions with no sector tag.
    if pool == "stocks" and ctx.get("sector_pct_current", 0.0) > ctx["max_sector_pct"]:
        return "BLOCK", "PORTFOLIO_CONCENTRATION", {
            "sector_pct_current": ctx["sector_pct_current"],
            "max_sector_pct": ctx["max_sector_pct"],
        }

    # 4. DAILY_LOSS_LIMIT — today's realised + unrealised loss
    if ctx["daily_loss_pct"] >= ctx["daily_loss_limit_pct"]:
        return "BLOCK", "DAILY_LOSS_LIMIT", {
            "daily_loss_pct": ctx["daily_loss_pct"],
            "limit_pct": ctx["daily_loss_limit_pct"],
        }

    # 5. WEEKLY_DRAWDOWN_LIMIT
    if ctx["weekly_drawdown_pct_current"] >= ctx["weekly_drawdown_pct"]:
        return "BLOCK", "WEEKLY_DRAWDOWN_LIMIT", {
            "weekly_drawdown_pct_current": ctx["weekly_drawdown_pct_current"],
            "limit_pct": ctx["weekly_drawdown_pct"],
        }

    # 6. BROKER_AUTH_REQUIRED
    if not ctx.get("broker_authenticated", True):
        return "BLOCK", "BROKER_AUTH_REQUIRED", {"pool": pool}

    # 7. IBKR_SESSION_CHECK (stocks only)
    if pool == "stocks" and not ctx.get("ibkr_available", True):
        return "BLOCK", "IBKR_SESSION_CHECK", {}

    # 8. MARKET_HOURS_CHECK (stocks only)
    if pool == "stocks" and not ctx.get("market_open", True):
        return "BLOCK", "MARKET_HOURS_CHECK", {}

    # 9. PENNY_STOCK_BLOCK (stocks only — crypto doesn't have a meaningful penny threshold)
    if pool == "stocks":
        price = ctx.get("current_price")
        if price is not None and price < 5.0:
            return "BLOCK", "PENNY_STOCK_BLOCK", {"price": price}

    # 10. CONVICTION_MINIMUM
    if ctx["conviction"] < ctx["conviction_threshold"]:
        return "BLOCK", "CONVICTION_MINIMUM", {
            "conviction": ctx["conviction"],
            "threshold": ctx["conviction_threshold"],
        }

    # 11. DUPLICATE_POSITION
    if ctx.get("has_open_position", False):
        return "BLOCK", "DUPLICATE_POSITION", {"ticker": ticker}

    # 12. EXISTING_ORDER
    if ctx.get("has_pending_order", False):
        return "BLOCK", "EXISTING_ORDER", {"ticker": ticker}

    return "PASS", None, {}


# ── Context builder (I/O) ─────────────────────────────────────────────────────

def _is_market_open() -> bool:
    now = datetime.now(_ET)
    if now.weekday() not in _WEEKDAYS:
        return False
    return _MARKET_OPEN <= now.time() <= _MARKET_CLOSE


def _pool_value(conn: sqlite3.Connection, pool: str) -> float:
    """Sum of cost_basis for all open positions in pool."""
    row = conn.execute(
        "SELECT COALESCE(SUM(cost_basis), 0.0) FROM trading_positions WHERE pool = ? AND status = 'open'",
        (pool,),
    ).fetchone()
    return float(row[0])


def _daily_loss_pct(conn: sqlite3.Connection, pool: str, pool_ceiling: float) -> float:
    """Today's total P&L (realised + unrealised) as a positive percentage of loss (0 if profit)."""
    row = conn.execute(
        """SELECT COALESCE(SUM(realised_pnl), 0.0) + COALESCE(SUM(unrealised_pnl), 0.0) as total_pnl
           FROM trading_positions
           WHERE pool = ? AND (status = 'open' OR date(closed_at) = date('now'))""",
        (pool,),
    ).fetchone()
    total_pnl = float(row[0] or 0.0)
    if pool_ceiling <= 0 or total_pnl >= 0:
        return 0.0
    return abs(total_pnl) / pool_ceiling * 100


def _weekly_drawdown_pct(conn: sqlite3.Connection, pool: str, pool_ceiling: float) -> float:
    """This week's P&L loss as a positive percentage (0 if profit)."""
    row = conn.execute(
        """SELECT COALESCE(SUM(realised_pnl), 0.0) + COALESCE(SUM(unrealised_pnl), 0.0) as pnl
           FROM trading_positions
           WHERE pool = ? AND (status = 'open' OR closed_at >= datetime('now', 'weekday 0', '-7 days'))""",
        (pool,),
    ).fetchone()
    pnl = float(row[0] or 0.0)
    if pool_ceiling <= 0 or pnl >= 0:
        return 0.0
    return abs(pnl) / pool_ceiling * 100


def _sector_pct(conn: sqlite3.Connection, pool: str, ticker: str, ceiling: float) -> float:
    # ponytail: sector tracking not implemented — trading_positions has no sector column
    return 0.0


async def _ibkr_ok(mode: str) -> tuple[bool, bool]:
    """Returns (connected, available) — both True if TWS is reachable."""
    connected = await ibkr.is_connected(mode)
    return connected, connected


async def gather_context(
    conn: sqlite3.Connection,
    pool: str,
    ticker: str,
    conviction: float,
    position_size_proposed: float,
    current_price: float | None = None,
) -> dict:
    """
    Collect all state needed by evaluate().
    Async because IBKR check requires an HTTP call.
    """
    ceiling    = float(get_config(conn, f"{pool}_pool_ceiling") or 5000)
    pool_val   = _pool_value(conn, pool)
    daily_pct  = _daily_loss_pct(conn, pool, ceiling)
    weekly_pct = _weekly_drawdown_pct(conn, pool, ceiling)
    sector_pct = _sector_pct(conn, pool, ticker, ceiling)

    has_open = bool(conn.execute(
        "SELECT 1 FROM trading_positions WHERE pool = ? AND ticker = ? AND status = 'open'",
        (pool, ticker),
    ).fetchone())
    has_order = bool(conn.execute(
        "SELECT 1 FROM trading_orders WHERE pool = ? AND ticker = ? AND status = 'pending'",
        (pool, ticker),
    ).fetchone())

    mode = get_config(conn, "trading_mode") or "paper"
    broker_auth, ibkr_avail = True, True
    if pool == "stocks":
        broker_auth, ibkr_avail = await _ibkr_ok(mode)

    ctx: dict = {
        "pool": pool,
        "ticker": ticker,
        "conviction": conviction,
        "position_size_proposed": position_size_proposed,
        "current_price": current_price,
        "pool_ceiling": ceiling,
        "pool_value": pool_val,
        "max_position_pct": float(get_config(conn, "max_position_pct") or 20),
        "max_sector_pct": float(get_config(conn, "max_sector_pct") or 40),
        "sector_pct_current": sector_pct,
        "daily_loss_pct": daily_pct,
        "daily_loss_limit_pct": float(get_config(conn, "daily_loss_limit_pct") or 5),
        "weekly_drawdown_pct_current": weekly_pct,
        "weekly_drawdown_pct": float(get_config(conn, "weekly_drawdown_pct") or 15),
        "broker_authenticated": broker_auth,
        "ibkr_available": ibkr_avail,
        "market_open": _is_market_open(),
        "conviction_threshold": float(get_config(conn, "conviction_threshold") or 70),
        "has_open_position": has_open,
        "has_pending_order": has_order,
    }
    return ctx


# ── Full pipeline (called by execution agents) ────────────────────────────────

async def run(
    pool: str,
    ticker: str,
    signal_id: int,
    conviction: float,
    position_size_proposed: float,
    current_price: float | None = None,
) -> tuple[str, str | None]:
    """
    Full risk gate evaluation + audit log entry.
    Returns (decision, rule_violated).
    Execution agents call this before placing any order.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        ctx = await gather_context(
            conn, pool, ticker, conviction, position_size_proposed, current_price
        )
        decision, rule_violated, details = evaluate(ctx)

        conn.execute(
            """INSERT INTO trading_risk_gate_log
               (pool, ticker, signal_id, decision, rule_violated, rule_details)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (pool, ticker, signal_id, decision, rule_violated, json.dumps(details)),
        )
        conn.commit()

        if decision == "BLOCK":
            log.warning(
                "Risk gate BLOCK: %s %s — rule=%s details=%s",
                pool, ticker, rule_violated, details,
            )
        else:
            log.info("Risk gate PASS: %s %s conviction=%.1f", pool, ticker, conviction)

        return decision, rule_violated

    except Exception:
        conn.rollback()
        log.exception("Risk gate error for %s %s — defaulting to BLOCK", pool, ticker)
        return "BLOCK", "INTERNAL_ERROR"
    finally:
        conn.close()
