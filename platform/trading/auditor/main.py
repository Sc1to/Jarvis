"""
13.14 — trading_auditor_compliance
Separate FastAPI service on port 8031. Fully independent of the main trading
service — reads SQLite and broker APIs directly, shares no in-process state.

Runs every 2 hours. Force-exits positions when loss limits are breached.
Logs violations to trading_audit_log. Notifies admin panel.

Why separate? The auditor must survive a crash in the main trading service
and be able to act (force-exit positions) even if the main service is down.
"""
import asyncio
import json
import logging
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager

import os

import httpx
from apscheduler import AsyncScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from auditor.rules import (
    pool_ceiling_breach, position_size_breach,
    daily_loss_breach, weekly_drawdown_breach,
    data_is_stale, order_is_orphaned, pool_loss_pct,
)

import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from health import health_payload

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

DB_PATH = os.environ.get("TRADING_DB_PATH", "/opt/platform/data/platform.db")
ADMIN_EVENT_URL = "http://localhost:8000/internal/event"
TRADING_NOTIFY_URL = "http://localhost:8030/notifications/send"
VERSION = "0.1.0"
START_TIME = time.time()


# ── DB helpers ────────────────────────────────────────────────────────────────

def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def _cfg(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM trading_config WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


# ── Notifications (best-effort, never raise) ──────────────────────────────────

async def _notify_admin(event_type: str, data: dict) -> None:
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            await client.post(ADMIN_EVENT_URL, json={"event_type": event_type, "data": data})
    except Exception:
        pass  # admin panel being down must not affect auditor operation


async def _notify_push(title: str, body: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(TRADING_NOTIFY_URL, json={"title": title, "body": body})
    except Exception:
        pass


# ── Force-exit helpers ────────────────────────────────────────────────────────

async def _force_exit_stocks(conn: sqlite3.Connection, pos: sqlite3.Row, mode: str) -> None:
    from tools import ibkr
    exit_price = float(pos["current_price"] or pos["entry_price"])
    broker_id = None

    if mode == "live":
        try:
            broker_id, _ = await ibkr.place_order(pos["ticker"], "SELL", pos["quantity"], mode)
        except Exception as exc:
            log.error("Force-exit IBKR order failed for %s: %s", pos["ticker"], exc)

    status = "filled" if (mode == "live" and broker_id) else "simulated"
    rpnl = round((exit_price - float(pos["entry_price"])) * float(pos["quantity"]), 6)

    conn.execute(
        """INSERT INTO trading_orders
           (pool, ticker, direction, order_type, quantity, status, broker_order_id,
            fill_price, position_id, filled_at)
           VALUES ('stocks', ?, 'SELL', 'market', ?, ?, ?, ?, ?, datetime('now'))""",
        (pos["ticker"], pos["quantity"], status, broker_id, exit_price, pos["id"]),
    )
    conn.execute(
        """UPDATE trading_positions
           SET status='closed', exit_price=?, realised_pnl=?,
               unrealised_pnl=0, closed_at=datetime('now')
           WHERE id=?""",
        (exit_price, rpnl, pos["id"]),
    )
    log.warning("Force-exited stock position: %s @ %.2f (pnl=%.2f)", pos["ticker"], exit_price, rpnl)


async def _force_exit_crypto(conn: sqlite3.Connection, pos: sqlite3.Row, api_key: str, api_secret: str, mode: str) -> None:
    from tools.coinbase import CoinbaseClient
    exit_price = float(pos["current_price"] or pos["entry_price"])
    broker_id = None

    if mode == "live" and api_key and api_secret:
        ticker = pos["ticker"]
        product_id = ticker if "-" in ticker else f"{ticker}-USD"
        try:
            client = CoinbaseClient(api_key, api_secret)
            resp = await asyncio.to_thread(
                client.place_market_order,
                uuid.uuid4().hex, product_id, "SELL", f"{pos['quantity']:.8f}",
            )
            broker_id = resp.get("order_id") or resp.get("id") or ""
        except Exception as exc:
            log.error("Force-exit Coinbase order failed for %s: %s", pos["ticker"], exc)

    status = "filled" if (mode == "live" and broker_id) else "simulated"
    rpnl = round((exit_price - float(pos["entry_price"])) * float(pos["quantity"]), 6)

    conn.execute(
        """INSERT INTO trading_orders
           (pool, ticker, direction, order_type, quantity, status, broker_order_id,
            fill_price, position_id, filled_at)
           VALUES ('crypto', ?, 'SELL', 'market', ?, ?, ?, ?, ?, datetime('now'))""",
        (pos["ticker"], pos["quantity"], status, broker_id, exit_price, pos["id"]),
    )
    conn.execute(
        """UPDATE trading_positions
           SET status='closed', exit_price=?, realised_pnl=?,
               unrealised_pnl=0, closed_at=datetime('now')
           WHERE id=?""",
        (exit_price, rpnl, pos["id"]),
    )
    log.warning("Force-exited crypto position: %s @ %.4f (pnl=%.2f)", pos["ticker"], exit_price, rpnl)


# ── Core audit logic ──────────────────────────────────────────────────────────

async def run_audit() -> dict:
    conn = _conn()
    findings: dict = {}
    positions_checked = 0
    violations_found = 0
    force_exits_executed = 0

    try:
        mode        = _cfg(conn, "trading_mode", "paper")
        account_id  = _cfg(conn, "ibkr_account_id")
        api_key     = _cfg(conn, "coinbase_api_key_name")
        api_secret  = _cfg(conn, "coinbase_api_private_key")
        ceiling_s   = float(_cfg(conn, "stocks_pool_ceiling", "5000"))
        ceiling_c   = float(_cfg(conn, "crypto_pool_ceiling", "2000"))
        max_pos_pct = float(_cfg(conn, "max_position_pct", "20"))
        daily_limit = float(_cfg(conn, "daily_loss_limit_pct", "5"))
        weekly_limit = float(_cfg(conn, "weekly_drawdown_pct", "15"))

        for pool, ceiling in [("stocks", ceiling_s), ("crypto", ceiling_c)]:
            positions = conn.execute(
                "SELECT * FROM trading_positions WHERE pool=? AND status='open'", (pool,)
            ).fetchall()
            positions_checked += len(positions)

            # Pool-level loss checks
            total_pnl = sum(
                float(p["realised_pnl"] or 0) + float(p["unrealised_pnl"] or 0)
                for p in positions
            ) + sum(
                float(r["realised_pnl"] or 0)
                for r in conn.execute(
                    "SELECT realised_pnl FROM trading_positions WHERE pool=? AND date(closed_at)=date('now')",
                    (pool,),
                ).fetchall()
            )
            daily_pct  = pool_loss_pct(total_pnl, ceiling)
            weekly_pct = pool_loss_pct(_weekly_pnl(conn, pool), ceiling)

            if daily_loss_breach(daily_pct, daily_limit):
                violations_found += 1
                findings.setdefault(pool, {})["daily_loss"] = {
                    "loss_pct": daily_pct, "limit_pct": daily_limit
                }
                log.warning("AUDIT: %s pool daily loss limit breached (%.1f%%)", pool, daily_pct)
                for pos in positions:
                    if pool == "stocks":
                        await _force_exit_stocks(conn, pos, mode)
                    else:
                        await _force_exit_crypto(conn, pos, api_key, api_secret, mode)
                    force_exits_executed += 1
                conn.commit()
                await _notify_admin("trading_audit_force_exit", {
                    "pool": pool, "reason": "daily_loss_limit", "loss_pct": daily_pct,
                })
                await _notify_push(
                    f"Force Exit — {pool.capitalize()}",
                    f"Daily loss limit breached ({daily_pct:.1f}%). {force_exits_executed} position(s) closed.",
                )

            elif weekly_drawdown_breach(weekly_pct, weekly_limit):
                violations_found += 1
                findings.setdefault(pool, {})["weekly_drawdown"] = {
                    "drawdown_pct": weekly_pct, "limit_pct": weekly_limit
                }
                log.warning("AUDIT: %s pool weekly drawdown breached (%.1f%%)", pool, weekly_pct)
                for pos in positions:
                    if pool == "stocks":
                        await _force_exit_stocks(conn, pos, mode)
                    else:
                        await _force_exit_crypto(conn, pos, api_key, api_secret, mode)
                    force_exits_executed += 1
                conn.commit()
                await _notify_admin("trading_audit_force_exit", {
                    "pool": pool, "reason": "weekly_drawdown_limit", "drawdown_pct": weekly_pct,
                })
                await _notify_push(
                    f"Force Exit — {pool.capitalize()}",
                    f"Weekly drawdown limit breached ({weekly_pct:.1f}%). {force_exits_executed} position(s) closed.",
                )

            # Per-position checks (log only — no force-exit)
            total_cost = sum(float(p["cost_basis"] or 0) for p in positions)
            if pool_ceiling_breach(total_cost, ceiling):
                violations_found += 1
                findings.setdefault(pool, {})["pool_ceiling"] = {
                    "deployed": total_cost, "ceiling": ceiling
                }
                log.warning("AUDIT: %s pool ceiling breach — deployed=%.2f ceiling=%.2f", pool, total_cost, ceiling)
                await _notify_admin("trading_audit_violation", {
                    "pool": pool, "rule": "pool_ceiling", "deployed": total_cost, "ceiling": ceiling,
                })

            for pos in positions:
                cb = float(pos["cost_basis"] or 0)
                if position_size_breach(cb, ceiling, max_pos_pct):
                    violations_found += 1
                    findings.setdefault(pool, {}).setdefault("position_size", []).append(pos["ticker"])
                    log.warning("AUDIT: position size breach — %s cost_basis=%.2f", pos["ticker"], cb)

                if data_is_stale(pos["opened_at"]):
                    findings.setdefault(pool, {}).setdefault("stale_data", []).append(pos["ticker"])
                    log.warning("AUDIT: stale price data for %s", pos["ticker"])

        # IBKR session check
        if account_id:
            from tools import ibkr
            if not await ibkr.is_connected(mode):
                findings["ibkr_session"] = "disconnected"
                violations_found += 1
                await _notify_admin("trading_audit_violation", {"rule": "ibkr_session_disconnected"})

        # Orphaned pending orders
        pending_orders = conn.execute(
            "SELECT * FROM trading_orders WHERE status='pending'"
        ).fetchall()
        orphaned = [
            dict(o) for o in pending_orders
            if order_is_orphaned(o["submitted_at"])
        ]
        if orphaned:
            findings["orphaned_orders"] = [o["id"] for o in orphaned]
            violations_found += len(orphaned)
            for o in orphaned:
                conn.execute("UPDATE trading_orders SET status='cancelled' WHERE id=?", (o["id"],))
                log.warning("AUDIT: cancelled orphaned order id=%s ticker=%s", o["id"], o["ticker"])
            conn.commit()

        # Write audit log
        conn.execute(
            """INSERT INTO trading_audit_log
               (audit_type, findings, positions_checked, violations_found, force_exits_executed)
               VALUES ('scheduled', ?, ?, ?, ?)""",
            (json.dumps(findings), positions_checked, violations_found, force_exits_executed),
        )
        conn.commit()

        log.info(
            "Audit complete: positions=%d violations=%d force_exits=%d",
            positions_checked, violations_found, force_exits_executed,
        )
        return {
            "positions_checked": positions_checked,
            "violations_found": violations_found,
            "force_exits_executed": force_exits_executed,
            "findings": findings,
        }

    except Exception:
        conn.rollback()
        log.exception("Audit run failed")
        return {"error": "audit_failed"}
    finally:
        conn.close()


def _weekly_pnl(conn: sqlite3.Connection, pool: str) -> float:
    """Total P&L (realised + unrealised) for the current week."""
    open_pnl = conn.execute(
        """SELECT COALESCE(SUM(realised_pnl),0)+COALESCE(SUM(unrealised_pnl),0)
           FROM trading_positions WHERE pool=? AND status='open'""",
        (pool,),
    ).fetchone()[0]
    closed_pnl = conn.execute(
        """SELECT COALESCE(SUM(realised_pnl),0)
           FROM trading_positions
           WHERE pool=? AND status='closed'
             AND closed_at >= datetime('now','weekday 0','-7 days')""",
        (pool,),
    ).fetchone()[0]
    return float(open_pnl or 0) + float(closed_pnl or 0)


# ── FastAPI app ───────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(_app: FastAPI):
    async with AsyncScheduler() as scheduler:
        await scheduler.add_schedule(run_audit, IntervalTrigger(hours=2), id="audit")
        await scheduler.start_in_background()
        log.info("Compliance auditor started — auditing every 2 hours")
        yield


app = FastAPI(title="Platform Trading Auditor", version=VERSION, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
def health():
    return health_payload(START_TIME, VERSION)


@app.post("/audit/run")
async def trigger_audit():
    """Manually trigger an audit run. Used by the main trading service on position open."""
    return await run_audit()


@app.get("/audit/latest")
def latest_audit():
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT * FROM trading_audit_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not row:
            return {"message": "No audits run yet"}
        return dict(row)
    finally:
        conn.close()


@app.get("/audit/history")
def audit_history(limit: int = 20):
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT * FROM trading_audit_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
