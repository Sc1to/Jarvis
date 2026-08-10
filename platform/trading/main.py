"""
Trading service — port 8030.
Single FastAPI service hosting all trading agents as APScheduler jobs.
The compliance auditor is a separate service (built in 13.14).
"""
import logging
import os
import sys
import time
from contextlib import asynccontextmanager

import httpx
from apscheduler import AsyncScheduler
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from db import DB_PATH, get_db, get_config, set_config, init_db

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from health import health_payload

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

START_TIME = time.time()
VERSION = "0.1.0"

_SENSITIVE_KEYS = {"coinbase_api_private_key", "reddit_client_secret"}
_READONLY_KEYS = {"trading_mode"}  # changed only via /mode endpoint


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    log.info("Trading DB initialised")

    from notifications import init_vapid
    init_vapid()

    from monitors.universe import seed_universe
    seed_universe()
    log.info("Universe seeded")

    from scheduler import register_jobs
    scheduler = AsyncScheduler()
    await scheduler.start_in_background()
    await register_jobs(scheduler)
    log.info("Trading scheduler started")

    yield

    await scheduler.stop()
    log.info("Trading scheduler stopped")


app = FastAPI(title="Platform Trading", version=VERSION, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health(db=Depends(get_db)):
    from tools import ibkr as _ibkr
    mode = get_config(db, "trading_mode") or "paper"
    deps = {}

    deps["ibkr_tws"] = "ok" if await _ibkr.is_connected(mode) else "down"

    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get("https://api.coinbase.com/api/v3/brokerage/time")
            deps["coinbase"] = "ok" if r.status_code == 200 else "error"
    except Exception:
        deps["coinbase"] = "down"

    return health_payload(START_TIME, VERSION, trading_mode=mode, dependencies=deps)


# ── Trading mode ──────────────────────────────────────────────────────────────

@app.get("/mode")
def get_mode(db=Depends(get_db)):
    return {"trading_mode": get_config(db, "trading_mode") or "paper"}


@app.post("/mode")
def set_mode(body: dict, db=Depends(get_db)):
    mode = body.get("mode", "")
    if mode not in ("paper", "live"):
        raise HTTPException(400, "mode must be 'paper' or 'live'")
    confirm = body.get("confirm", False)
    if mode == "live" and not confirm:
        raise HTTPException(
            400,
            "Switching to live trading requires confirm=true. "
            "Ensure paper trading validation criteria are met before confirming.",
        )
    set_config(db, "trading_mode", mode)
    log.warning("Trading mode changed to: %s", mode)
    return {"trading_mode": mode}


# ── Config ────────────────────────────────────────────────────────────────────

@app.get("/config")
def list_config(db=Depends(get_db)):
    rows = db.execute("SELECT key, value, updated_at FROM trading_config ORDER BY key").fetchall()
    return [
        {
            "key": r["key"],
            "value": "***" if r["key"] in _SENSITIVE_KEYS else r["value"],
            "updated_at": r["updated_at"],
        }
        for r in rows
    ]


@app.post("/config/{key}")
def update_config(key: str, body: dict, db=Depends(get_db)):
    if key in _READONLY_KEYS:
        raise HTTPException(400, f"Use the /mode endpoint to change '{key}'")
    value = body.get("value")
    if value is None:
        raise HTTPException(400, "body must contain 'value'")
    set_config(db, key, str(value))
    return {"key": key, "updated": True}


# ── Status ────────────────────────────────────────────────────────────────────

@app.get("/status")
def trading_status(db=Depends(get_db)):
    open_positions = db.execute(
        "SELECT COUNT(*) FROM trading_positions WHERE status = 'open'"
    ).fetchone()[0]
    pending_orders = db.execute(
        "SELECT COUNT(*) FROM trading_orders WHERE status = 'pending'"
    ).fetchone()[0]
    signals_today = db.execute(
        "SELECT COUNT(*) FROM trading_signals WHERE date(timestamp) = date('now')"
    ).fetchone()[0]
    last_brief_row = db.execute(
        "SELECT brief_date FROM trading_morning_briefs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return {
        "open_positions": open_positions,
        "pending_orders": pending_orders,
        "signals_today": signals_today,
        "last_morning_brief": last_brief_row["brief_date"] if last_brief_row else None,
        "trading_mode": get_config(db, "trading_mode") or "paper",
    }


# ── Positions ─────────────────────────────────────────────────────────────────

@app.get("/positions")
def list_positions(pool: str | None = None, db=Depends(get_db)):
    query = "SELECT * FROM trading_positions WHERE status = 'open'"
    params: list = []
    if pool:
        query += " AND pool = ?"
        params.append(pool)
    rows = db.execute(query, params).fetchall()
    return [dict(r) for r in rows]


@app.get("/positions/history")
def position_history(limit: int = 50, db=Depends(get_db)):
    rows = db.execute(
        "SELECT * FROM trading_positions WHERE status = 'closed' ORDER BY closed_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


# ── Signals ───────────────────────────────────────────────────────────────────

@app.get("/signals")
def list_signals(limit: int = 50, pool: str | None = None, db=Depends(get_db)):
    query = "SELECT * FROM trading_signals ORDER BY timestamp DESC LIMIT ?"
    params: list = [limit]
    if pool:
        query = "SELECT * FROM trading_signals WHERE pool = ? ORDER BY timestamp DESC LIMIT ?"
        params = [pool, limit]
    rows = db.execute(query, params).fetchall()
    return [dict(r) for r in rows]


@app.get("/learning/weights")
def learning_weights(db=Depends(get_db)):
    """Current signal weights with history of last change."""
    rows = db.execute(
        "SELECT * FROM trading_learning_weights ORDER BY weight_key"
    ).fetchall()
    return [dict(r) for r in rows]


@app.post("/learning/run")
async def trigger_learning():
    """Manually trigger the learning engine (for testing)."""
    from learning_engine import run as _run
    return await _run()


@app.get("/signals/conviction")
def conviction_signals(limit: int = 50, pool: str | None = None, db=Depends(get_db)):
    """Recent conviction signals with action, conviction score, and rationale."""
    if pool:
        rows = db.execute(
            """SELECT * FROM trading_signals WHERE signal_type = 'conviction' AND pool = ?
               ORDER BY timestamp DESC LIMIT ?""",
            (pool, limit),
        ).fetchall()
    else:
        rows = db.execute(
            """SELECT * FROM trading_signals WHERE signal_type = 'conviction'
               ORDER BY timestamp DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


# ── Risk gate log ─────────────────────────────────────────────────────────────

@app.get("/risk-gate-log")
def risk_gate_log(limit: int = 50, db=Depends(get_db)):
    rows = db.execute(
        "SELECT * FROM trading_risk_gate_log ORDER BY evaluated_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


# ── Morning briefs ────────────────────────────────────────────────────────────

@app.get("/briefs")
def list_briefs(limit: int = 10, db=Depends(get_db)):
    rows = db.execute(
        "SELECT id, brief_date, generated_at FROM trading_morning_briefs ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


@app.get("/briefs/latest")
def latest_brief(db=Depends(get_db)):
    row = db.execute(
        "SELECT * FROM trading_morning_briefs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if not row:
        raise HTTPException(404, "No morning brief generated yet")
    return dict(row)


# ── WSB ───────────────────────────────────────────────────────────────────────

@app.get("/wsb/posts")
def wsb_posts(limit: int = 25, db=Depends(get_db)):
    rows = db.execute(
        "SELECT * FROM trading_wsb_posts ORDER BY processed_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


@app.get("/wsb/mentions")
def wsb_mentions(ticker: str | None = None, limit: int = 50, db=Depends(get_db)):
    if ticker:
        rows = db.execute(
            "SELECT * FROM trading_wsb_mentions WHERE ticker = ? ORDER BY recorded_at DESC LIMIT ?",
            (ticker.upper(), limit),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM trading_wsb_mentions ORDER BY recorded_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/wsb/top-mentions")
def wsb_top_mentions(hours: int = 2, limit: int = 20, db=Depends(get_db)):
    """Tickers with the highest spike factor in the last N hours."""
    rows = db.execute(
        """SELECT ticker, MAX(spike_factor) as peak_spike, MAX(mention_count) as peak_count
           FROM trading_wsb_mentions
           WHERE recorded_at >= datetime('now', ? || ' hours')
           GROUP BY ticker
           ORDER BY peak_spike DESC
           LIMIT ?""",
        (f"-{hours}", limit),
    ).fetchall()
    return [dict(r) for r in rows]


@app.get("/wsb/correlation")
def wsb_correlation(limit: int = 20, db=Depends(get_db)):
    """Recent correlation signals (DD + mention spike on same ticker)."""
    rows = db.execute(
        """SELECT * FROM trading_signals
           WHERE signal_type = 'wsb_correlation'
           ORDER BY timestamp DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


# ── Universe ──────────────────────────────────────────────────────────────────

@app.get("/universe")
def list_universe(pool: str | None = None, db=Depends(get_db)):
    query = "SELECT * FROM trading_universe ORDER BY pool, ticker"
    params: list = []
    if pool:
        query = "SELECT * FROM trading_universe WHERE pool = ? ORDER BY ticker"
        params = [pool]
    return [dict(r) for r in db.execute(query, params).fetchall()]


@app.post("/universe/{pool}/{ticker}")
def add_to_universe(pool: str, ticker: str, db=Depends(get_db)):
    if pool not in ("stocks", "crypto"):
        raise HTTPException(400, "pool must be 'stocks' or 'crypto'")
    db.execute(
        "INSERT OR IGNORE INTO trading_universe (pool, ticker) VALUES (?, ?)",
        (pool, ticker.upper()),
    )
    return {"status": "ok", "pool": pool, "ticker": ticker.upper()}


@app.delete("/universe/{pool}/{ticker}")
def remove_from_universe(pool: str, ticker: str, db=Depends(get_db)):
    db.execute(
        "UPDATE trading_universe SET active = 0 WHERE pool = ? AND ticker = ?",
        (pool, ticker.upper()),
    )
    return {"status": "ok"}


# ── Catalysts ─────────────────────────────────────────────────────────────────

@app.get("/catalysts")
def list_catalysts(ticker: str | None = None, db=Depends(get_db)):
    if ticker:
        rows = db.execute(
            "SELECT * FROM trading_catalysts WHERE ticker = ? ORDER BY event_date",
            (ticker.upper(),),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM trading_catalysts WHERE temporal_state = 'upcoming' ORDER BY event_date"
        ).fetchall()
    return [dict(r) for r in rows]


@app.post("/catalysts")
def add_catalyst(body: dict, db=Depends(get_db)):
    required = {"ticker", "catalyst_type", "description", "event_date"}
    if missing := required - body.keys():
        raise HTTPException(400, f"Missing fields: {missing}")
    db.execute(
        """INSERT OR IGNORE INTO trading_catalysts
           (ticker, catalyst_type, description, event_date, source)
           VALUES (?, ?, ?, ?, ?)""",
        (
            body["ticker"].upper(),
            body["catalyst_type"],
            body["description"],
            body["event_date"],
            body.get("source", "manual"),
        ),
    )
    return {"status": "ok"}


@app.get("/catalysts/{ticker}/state")
def catalyst_state(ticker: str):
    """Return the current temporal state for a ticker."""
    from catalysts.temporal_state import get_temporal_state
    return get_temporal_state(ticker.upper())


# ── Validation ────────────────────────────────────────────────────────────────

@app.get("/validation/status")
def validation_status(db=Depends(get_db)):
    """Paper trading readiness check — returns per-criterion pass/fail."""
    from datetime import date as _date

    c: dict = {}

    # Days of operation (first morning brief → today)
    first = db.execute("SELECT MIN(brief_date) FROM trading_morning_briefs").fetchone()[0]
    days = (_date.today() - _date.fromisoformat(first)).days + 1 if first else 0
    c["days_operation"] = {
        "label": "Days of continuous operation",
        "detail": f"{days} days",
        "target": "90 (3 months minimum)",
        "pass": days >= 90,
    }

    # Morning brief generated every day
    brief_count = db.execute("SELECT COUNT(*) FROM trading_morning_briefs").fetchone()[0]
    c["morning_briefs"] = {
        "label": "Morning brief every day without failure",
        "detail": f"{brief_count}/{max(days, 0)} days",
        "target": f"{max(days, 0)} days",
        "pass": brief_count >= days > 0,
    }

    # Risk gate scenarios (distinct rules that fired a BLOCK)
    blocked_rules = db.execute(
        "SELECT COUNT(DISTINCT rule_violated) FROM trading_risk_gate_log WHERE decision='BLOCK'"
    ).fetchone()[0]
    c["risk_gate_scenarios"] = {
        "label": "Risk gate triggered on ≥5 distinct scenarios",
        "detail": f"{blocked_rules} distinct rules triggered",
        "target": "5",
        "pass": blocked_rules >= 5,
    }

    # Compliance auditor triggered with at least one violation
    audit_violations = db.execute(
        "SELECT COUNT(*) FROM trading_audit_log WHERE violations_found > 0"
    ).fetchone()[0]
    c["auditor_triggered"] = {
        "label": "Compliance auditor triggered at least once",
        "detail": f"{audit_violations} audit run(s) with violations",
        "target": "1",
        "pass": audit_violations >= 1,
    }

    # Learning engine days (distinct dates the auditor ran = proxy for service uptime)
    learning_days = db.execute(
        "SELECT COUNT(DISTINCT date(ran_at)) FROM trading_audit_log"
    ).fetchone()[0]
    c["learning_cycles"] = {
        "label": "Learning engine ≥90 daily cycles",
        "detail": f"~{learning_days} days of data",
        "target": "90",
        "pass": learning_days >= 90,
    }

    # Shadow portfolio P&L positive (≥10 simulated trades)
    row = db.execute(
        "SELECT COALESCE(SUM(simulated_pnl),0), COUNT(*) FROM trading_shadow_portfolio WHERE simulated_pnl IS NOT NULL"
    ).fetchone()
    shadow_pnl, shadow_count = float(row[0] or 0), int(row[1] or 0)
    c["shadow_pnl"] = {
        "label": "Shadow portfolio P&L positive",
        "detail": f"${shadow_pnl:+.2f} over {shadow_count} simulated trades",
        "target": "> $0 with ≥10 trades",
        "pass": shadow_pnl > 0 and shadow_count >= 10,
    }

    # No audit failures
    audit_failures = db.execute(
        "SELECT COUNT(*) FROM trading_audit_log WHERE findings LIKE '%audit_failed%'"
    ).fetchone()[0]
    c["clean_operation"] = {
        "label": "No unhandled exceptions in auditor",
        "detail": f"{audit_failures} audit failure(s)",
        "target": "0",
        "pass": audit_failures == 0,
    }

    # Manual confirmations (set via /config/{key})
    for key, label in [
        ("validation_ibkr_reconnect_ok", "IBC/TWS auto-reconnect verified (overnight)"),
        ("validation_logs_reviewed",     "Agent logs reviewed — no unexpected errors"),
        ("validation_outcome_reviewed",  "Paper trading outcome reviewed and understood"),
    ]:
        c[key] = {
            "label": label,
            "detail": "Confirmed" if get_config(db, key) == "true" else "Not yet confirmed",
            "target": "manual",
            "pass": get_config(db, key) == "true",
            "manual": True,
        }

    automatable_pass = all(v["pass"] for v in c.values() if not v.get("manual"))
    return {
        "criteria": c,
        "automatable_pass": automatable_pass,
        "all_pass": all(v["pass"] for v in c.values()),
        "days_since_start": days,
    }


# ── Notifications ─────────────────────────────────────────────────────────────

@app.get("/notifications/vapid-key")
def vapid_public_key():
    from notifications import get_public_key
    key = get_public_key()
    if not key:
        raise HTTPException(503, "VAPID keys not initialised")
    return {"publicKey": key}


@app.post("/notifications/subscribe")
def subscribe(body: dict):
    endpoint = body.get("endpoint")
    keys = body.get("keys", {})
    if not endpoint or not keys.get("p256dh") or not keys.get("auth"):
        raise HTTPException(400, "endpoint and keys.p256dh and keys.auth required")
    from notifications import save_subscription
    save_subscription(endpoint, keys["p256dh"], keys["auth"])
    return {"status": "ok"}


@app.post("/notifications/unsubscribe")
def unsubscribe(body: dict):
    endpoint = body.get("endpoint")
    if not endpoint:
        raise HTTPException(400, "endpoint required")
    from notifications import remove_subscription
    remove_subscription(endpoint)
    return {"status": "ok"}


@app.post("/notifications/send")
async def send_notification(body: dict):
    """Internal endpoint — called by auditor or other services to push alerts."""
    title = body.get("title", "Jarvis Trading")
    notification_body = body.get("body", "")
    url = body.get("url", "/trading/")
    import asyncio
    from notifications import send_push
    asyncio.create_task(asyncio.to_thread(send_push, title, notification_body, url))
    return {"status": "ok"}


@app.post("/catalysts/{catalyst_id}/resolve")
def resolve_catalyst(catalyst_id: int, body: dict, db=Depends(get_db)):
    """
    Mark a catalyst as resolved after the event passes.
    body: {outcome: 'resolved_positive' | 'resolved_negative', notes: str}
    """
    outcome = body.get("outcome", "")
    if outcome not in ("resolved_positive", "resolved_negative"):
        raise HTTPException(400, "outcome must be 'resolved_positive' or 'resolved_negative'")
    row = db.execute(
        "SELECT id FROM trading_catalysts WHERE id = ?", (catalyst_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Catalyst not found")
    db.execute(
        "UPDATE trading_catalysts SET temporal_state = ?, outcome_notes = ? WHERE id = ?",
        (outcome, body.get("notes", ""), catalyst_id),
    )
    return {"status": "ok", "outcome": outcome}
