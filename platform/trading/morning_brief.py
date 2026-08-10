"""
13.16 — Morning brief generation
Runs daily at 07:00. Assembles a structured snapshot of overnight activity
for both pools and stores it in trading_morning_briefs as JSON.

Content:
  - Open positions with current price and unrealised P&L
  - Overnight P&L (realised + unrealised change)
  - Orders executed since last market close
  - Signals blocked by the risk gate in the last 12 hours
  - IBKR authentication status
  - Last compliance audit result
  - Ollama narrative summary (with template fallback)
"""
import json
import logging
import sqlite3
from datetime import date

import httpx  # used for Ollama narrative call

from db import DB_PATH, OLLAMA_BASE, get_config
from tools import ibkr

log = logging.getLogger(__name__)

OLLAMA_URL   = f"{OLLAMA_BASE}/api/generate"
OLLAMA_MODEL = "qwen2.5:14b"


# ── Section builders (pure — take rows, return dicts) ─────────────────────────

def pool_overnight_pnl(
    open_positions: list[dict],
    closed_today: list[dict],
) -> float:
    """
    Today's P&L = realised from positions closed today
                + current unrealised on open positions.
    """
    realised  = sum(float(p.get("realised_pnl") or 0) for p in closed_today)
    unrealised = sum(float(p.get("unrealised_pnl") or 0) for p in open_positions)
    return round(realised + unrealised, 2)


def summarise_position(pos: dict) -> dict:
    """Compact position summary for the brief."""
    return {
        "ticker":        pos.get("ticker"),
        "quantity":      pos.get("quantity"),
        "entry_price":   pos.get("entry_price"),
        "current_price": pos.get("current_price"),
        "unrealised_pnl": pos.get("unrealised_pnl"),
        "trailing_stop": pos.get("trailing_stop"),
        "opened_at":     pos.get("opened_at"),
    }


def summarise_order(order: dict) -> dict:
    return {
        "ticker":     order.get("ticker"),
        "direction":  order.get("direction"),
        "quantity":   order.get("quantity"),
        "fill_price": order.get("fill_price"),
        "status":     order.get("status"),
        "filled_at":  order.get("filled_at"),
    }


def summarise_block(log_row: dict) -> dict:
    return {
        "ticker":       log_row.get("ticker"),
        "rule_violated": log_row.get("rule_violated"),
        "evaluated_at": log_row.get("evaluated_at"),
    }


def build_pool_section(
    open_positions: list[dict],
    closed_today: list[dict],
    overnight_orders: list[dict],
    blocked_signals: list[dict],
) -> dict:
    return {
        "open_positions":   [summarise_position(p) for p in open_positions],
        "closed_today":     len(closed_today),
        "overnight_pnl":    pool_overnight_pnl(open_positions, closed_today),
        "orders_overnight": [summarise_order(o) for o in overnight_orders],
        "blocked_signals":  [summarise_block(b) for b in blocked_signals],
    }


# ── IBKR status (async I/O) ───────────────────────────────────────────────────

async def _ibkr_status(mode: str) -> str:
    connected = await ibkr.is_connected(mode)
    return "connected" if connected else "disconnected"


# ── Ollama narrative (best-effort) ────────────────────────────────────────────

def _template_narrative(stocks: dict, crypto: dict, ibkr: str) -> str:
    total_pnl = stocks["overnight_pnl"] + crypto["overnight_pnl"]
    direction = "up" if total_pnl >= 0 else "down"
    return (
        f"Overnight summary: combined P&L ${total_pnl:+.2f} ({direction}). "
        f"Stocks: {len(stocks['open_positions'])} open positions, "
        f"${stocks['overnight_pnl']:+.2f} unrealised. "
        f"Crypto: {len(crypto['open_positions'])} open positions, "
        f"${crypto['overnight_pnl']:+.2f} unrealised. "
        f"IBKR: {ibkr}. "
        f"Blocked signals: {len(stocks['blocked_signals']) + len(crypto['blocked_signals'])}. "
        f"(Ollama offline — template narrative)"
    )


async def _generate_narrative(stocks: dict, crypto: dict, ibkr: str, audit: dict) -> str:
    stocks_open = len(stocks["open_positions"])
    crypto_open = len(crypto["open_positions"])
    total_pnl = stocks["overnight_pnl"] + crypto["overnight_pnl"]
    blocks = len(stocks["blocked_signals"]) + len(crypto["blocked_signals"])

    prompt = (
        "You are a trading system analyst writing a morning brief for an autonomous trading platform.\n\n"
        f"Date: {date.today().isoformat()}\n"
        f"Stocks pool: {stocks_open} open positions, overnight P&L ${stocks['overnight_pnl']:+.2f}, "
        f"{len(stocks['orders_overnight'])} orders executed, {len(stocks['blocked_signals'])} blocked signals\n"
        f"Crypto pool: {crypto_open} open positions, overnight P&L ${crypto['overnight_pnl']:+.2f}, "
        f"{len(crypto['orders_overnight'])} orders executed, {len(crypto['blocked_signals'])} blocked signals\n"
        f"Combined overnight P&L: ${total_pnl:+.2f}\n"
        f"IBKR status: {ibkr}\n"
        f"Last compliance audit: {audit.get('violations_found', 0)} violations, "
        f"{audit.get('force_exits_executed', 0)} force exits\n"
        f"Total blocked signals: {blocks}\n\n"
        "Write a concise 3-4 sentence morning brief. Highlight anything unusual or requiring attention. "
        "Plain text only, no bullet points."
    )
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                OLLAMA_URL,
                json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            )
            resp.raise_for_status()
            return resp.json().get("response", "").strip()
    except Exception as exc:
        log.warning("Ollama unavailable for morning brief: %s", exc)
        return _template_narrative(stocks, crypto, ibkr)


# ── Entry point ───────────────────────────────────────────────────────────────

async def run() -> dict:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    try:
        mode  = get_config(conn, "trading_mode") or "paper"
        today = date.today().isoformat()

        # Gather data for both pools
        sections: dict[str, dict] = {}
        for pool in ("stocks", "crypto"):
            open_pos = [dict(r) for r in conn.execute(
                "SELECT * FROM trading_positions WHERE pool=? AND status='open'", (pool,)
            ).fetchall()]

            closed_today = [dict(r) for r in conn.execute(
                "SELECT * FROM trading_positions WHERE pool=? AND status='closed' AND date(closed_at)=date('now')",
                (pool,),
            ).fetchall()]

            overnight_orders = [dict(r) for r in conn.execute(
                """SELECT * FROM trading_orders
                   WHERE pool=? AND status IN ('filled','simulated')
                     AND filled_at >= datetime('now','-12 hours')
                   ORDER BY filled_at DESC""",
                (pool,),
            ).fetchall()]

            blocked = [dict(r) for r in conn.execute(
                """SELECT * FROM trading_risk_gate_log
                   WHERE pool=? AND decision='BLOCK'
                     AND evaluated_at >= datetime('now','-12 hours')
                   ORDER BY evaluated_at DESC""",
                (pool,),
            ).fetchall()]

            sections[pool] = build_pool_section(open_pos, closed_today, overnight_orders, blocked)

        # IBKR status
        ibkr_status = await _ibkr_status(mode)

        # Last compliance audit
        audit_row = conn.execute(
            "SELECT * FROM trading_audit_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        audit = dict(audit_row) if audit_row else {}

        # Narrative
        narrative = await _generate_narrative(sections["stocks"], sections["crypto"], ibkr_status, audit)

        brief = {
            "date":        today,
            "stocks":      sections["stocks"],
            "crypto":      sections["crypto"],
            "ibkr_status": ibkr_status,
            "last_audit":  {
                "ran_at":               audit.get("ran_at"),
                "violations_found":     audit.get("violations_found", 0),
                "force_exits_executed": audit.get("force_exits_executed", 0),
            },
            "narrative": narrative,
        }

        conn.execute(
            "INSERT OR REPLACE INTO trading_morning_briefs (brief_date, content) VALUES (?, ?)",
            (today, json.dumps(brief)),
        )
        conn.commit()
        log.info("Morning brief generated for %s", today)
        return brief

    except Exception:
        conn.rollback()
        log.exception("Morning brief generation failed")
        return {"error": "brief_generation_failed"}
    finally:
        conn.close()
