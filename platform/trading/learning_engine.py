"""
13.15 — trading_learning_engine
Runs daily at 05:00. Analyses closed positions from the last N days,
computes per-signal-type performance, and nudges weights in
trading_learning_weights toward better-performing signals.

On Mondays: also generates a weekly performance summary via Ollama and
stores it so the morning brief can include it.

What is tuned:   signal weights (momentum, wsb_dd, wsb_mentions, wsb_correlation,
                 pre/post catalyst modifiers)
What is NOT tuned: risk gate rules, pool ceilings, order sizing formula
"""
import json
import logging
import sqlite3
from datetime import datetime

import httpx

from db import DB_PATH, OLLAMA_BASE, get_config

log = logging.getLogger(__name__)

OLLAMA_URL   = f"{OLLAMA_BASE}/api/generate"
OLLAMA_MODEL = "qwen2.5:14b"

# Signal types the learning engine can tune
_TUNABLE_WEIGHTS = {
    "momentum":        "momentum_weight",
    "wsb_dd":          "wsb_dd_weight",
    "wsb_mentions":    "wsb_mentions_weight",
    "wsb_correlation": "wsb_correlation_weight",
}


# ── Pure math (no I/O) ────────────────────────────────────────────────────────

def pnl_pct(realised_pnl: float, cost_basis: float) -> float:
    """Closed trade return as a percentage. 0.0 if cost_basis is zero."""
    if cost_basis <= 0:
        return 0.0
    return realised_pnl / cost_basis * 100


def weight_adjustment(avg_pnl_pct: float, win_rate: float, learning_rate: float) -> float:
    """
    Combine win-rate signal and P&L signal into a single adjustment.

    win_rate_signal: maps [0,1] → [-1,1] (0.5 win rate = neutral)
    pnl_signal: clamps avg_pnl% to [-1,1] using 20% as the saturation point
    Result is scaled by learning_rate.
    """
    win_signal = (win_rate - 0.5) * 2
    pnl_signal = max(-1.0, min(1.0, avg_pnl_pct / 20.0))
    return ((win_signal + pnl_signal) / 2) * learning_rate


def apply_adjustment(current: float, adj: float, max_change: float, lo: float = 0.1, hi: float = 3.0) -> float:
    """Apply adjustment capped at max_change per cycle, clamped to [lo, hi]."""
    capped = max(-max_change, min(max_change, adj))
    return max(lo, min(hi, current + capped))


def aggregate_performance(
    trades: list[dict],  # each: {signal_types: [str], pnl_pct: float}
) -> dict[str, dict]:
    """
    Aggregate per-signal-type performance across a list of trades.
    Returns {signal_type: {count, avg_pnl_pct, win_rate}}.
    Only covers signal types in _TUNABLE_WEIGHTS.
    """
    buckets: dict[str, list[float]] = {}
    for trade in trades:
        pct = trade["pnl_pct"]
        for sig_type in trade.get("signal_types", []):
            if sig_type in _TUNABLE_WEIGHTS:
                buckets.setdefault(sig_type, []).append(pct)

    result: dict[str, dict] = {}
    for sig_type, pnl_list in buckets.items():
        count = len(pnl_list)
        avg = sum(pnl_list) / count
        wins = sum(1 for p in pnl_list if p > 0)
        result[sig_type] = {
            "count": count,
            "avg_pnl_pct": round(avg, 4),
            "win_rate": round(wins / count, 4),
        }
    return result


# ── DB helpers ────────────────────────────────────────────────────────────────

def _load_weights(conn: sqlite3.Connection) -> dict[str, float]:
    rows = conn.execute(
        "SELECT weight_key, weight_value FROM trading_learning_weights"
    ).fetchall()
    return {r["weight_key"]: float(r["weight_value"]) for r in rows}


def _save_weight(conn: sqlite3.Connection, key: str, new_val: float, old_val: float, rationale: str) -> None:
    conn.execute(
        """UPDATE trading_learning_weights
           SET weight_value=?, previous_value=?, updated_at=datetime('now'), rationale=?
           WHERE weight_key=?""",
        (round(new_val, 6), old_val, rationale, key),
    )


def _closed_trades(conn: sqlite3.Connection, lookback_days: int) -> list[dict]:
    """
    Fetch closed positions with linked conviction signal metadata.
    Returns list of {ticker, pnl_pct, signal_types}.
    """
    rows = conn.execute(
        """
        SELECT p.ticker, p.realised_pnl, p.cost_basis, p.signal_id
        FROM trading_positions p
        WHERE p.status = 'closed'
          AND p.realised_pnl IS NOT NULL
          AND p.cost_basis > 0
          AND p.closed_at >= datetime('now', ? || ' days')
        """,
        (f"-{lookback_days}",),
    ).fetchall()

    trades: list[dict] = []
    for row in rows:
        pct = pnl_pct(float(row["realised_pnl"]), float(row["cost_basis"]))
        signal_types: list[str] = []

        if row["signal_id"]:
            sig = conn.execute(
                "SELECT metadata FROM trading_signals WHERE id=? AND signal_type='conviction'",
                (row["signal_id"],),
            ).fetchone()
            if sig:
                try:
                    meta = json.loads(sig["metadata"] or "{}")
                    components = meta.get("components", {})
                    signal_types = list(components.keys())
                except (json.JSONDecodeError, AttributeError):
                    pass

        trades.append({"ticker": row["ticker"], "pnl_pct": pct, "signal_types": signal_types})

    return trades


def _shadow_summary(conn: sqlite3.Connection, lookback_days: int) -> dict:
    """Count shadow positions and estimate how many would have been profitable."""
    rows = conn.execute(
        """
        SELECT sp.ticker, sp.simulated_entry_price, sp.rule_violated,
               p.realised_pnl, p.cost_basis
        FROM trading_shadow_portfolio sp
        LEFT JOIN trading_positions p
            ON p.ticker = sp.ticker
           AND p.opened_at >= sp.opened_at
           AND p.opened_at <= datetime(sp.opened_at, '+1 hour')
           AND p.status = 'closed'
        WHERE sp.opened_at >= datetime('now', ? || ' days')
        """,
        (f"-{lookback_days}",),
    ).fetchall()

    total = len(rows)
    estimated_profitable = sum(
        1 for r in rows
        if r["realised_pnl"] is not None and float(r["realised_pnl"]) > 0
    )
    total_missed_pnl = sum(
        float(r["realised_pnl"])
        for r in rows
        if r["realised_pnl"] is not None
    )
    by_rule: dict[str, int] = {}
    for r in rows:
        rule = r["rule_violated"] or "unknown"
        by_rule[rule] = by_rule.get(rule, 0) + 1

    return {
        "total_blocked": total,
        "estimated_profitable": estimated_profitable,
        "total_missed_pnl": round(total_missed_pnl, 2),
        "by_rule": by_rule,
    }


# ── LLM summary (best-effort) ─────────────────────────────────────────────────

async def _generate_summary(
    perf: dict[str, dict],
    weight_changes: dict[str, tuple[float, float]],
    shadow: dict,
    total_trades: int,
) -> str:
    prompt = (
        "You are a trading system analyst writing a weekly performance summary.\n\n"
        f"Closed trades analysed: {total_trades}\n"
        f"Signal performance:\n"
        + "\n".join(
            f"  {sig}: count={s['count']} avg_pnl={s['avg_pnl_pct']:.2f}% win_rate={s['win_rate']:.0%}"
            for sig, s in perf.items()
        )
        + f"\n\nWeight changes this cycle:\n"
        + "\n".join(
            f"  {k}: {old:.3f} → {new:.3f}"
            for k, (old, new) in weight_changes.items()
        )
        + f"\n\nShadow portfolio (blocked trades): {shadow['total_blocked']} total, "
        f"{shadow['estimated_profitable']} estimated profitable, "
        f"${shadow['total_missed_pnl']:.2f} estimated missed P&L\n"
        + f"Top block reasons: {shadow['by_rule']}\n\n"
        "Write a 3-5 sentence summary of performance and what the weight adjustments mean. "
        "Be specific and analytical. Plain text only."
    )
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                OLLAMA_URL,
                json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            )
            resp.raise_for_status()
            return resp.json().get("response", "").strip()
    except Exception as exc:
        log.warning("Ollama unavailable for weekly summary: %s", exc)
        return (
            f"Weekly summary (Ollama offline): {total_trades} trades analysed. "
            f"Weight changes: {weight_changes}. Shadow: {shadow}."
        )


# ── Entry point ───────────────────────────────────────────────────────────────

async def run() -> dict:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    result: dict = {}

    try:
        learning_rate = float(get_config(conn, "learning_rate") or 0.05)
        min_samples   = int(get_config(conn, "learning_min_samples") or 3)
        lookback_days = int(get_config(conn, "learning_lookback_days") or 30)
        max_change    = float(get_config(conn, "learning_max_change") or 0.1)

        trades = _closed_trades(conn, lookback_days)
        log.info("Learning engine: %d closed trades in last %d days", len(trades), lookback_days)

        if len(trades) < min_samples:
            log.info("Learning engine: insufficient data (%d < %d) — skipping weight update", len(trades), min_samples)
            return {"skipped": True, "reason": "insufficient_data", "trades": len(trades)}

        perf = aggregate_performance(trades)
        weights = _load_weights(conn)
        weight_changes: dict[str, tuple[float, float]] = {}

        for sig_type, weight_key in _TUNABLE_WEIGHTS.items():
            stats = perf.get(sig_type)
            if stats is None or stats["count"] < min_samples:
                continue
            old_w = weights.get(weight_key, 1.0)
            adj = weight_adjustment(stats["avg_pnl_pct"], stats["win_rate"], learning_rate)
            new_w = apply_adjustment(old_w, adj, max_change)
            if abs(new_w - old_w) > 1e-6:
                rationale = (
                    f"count={stats['count']} avg_pnl={stats['avg_pnl_pct']:.2f}% "
                    f"win_rate={stats['win_rate']:.0%} adj={adj:.4f}"
                )
                _save_weight(conn, weight_key, new_w, old_w, rationale)
                weight_changes[weight_key] = (old_w, new_w)
                log.info("Weight update: %s %.4f → %.4f (%s)", weight_key, old_w, new_w, rationale)

        shadow = _shadow_summary(conn, lookback_days)
        conn.commit()

        result = {
            "trades_analysed": len(trades),
            "signal_performance": perf,
            "weight_changes": {k: {"from": v[0], "to": v[1]} for k, v in weight_changes.items()},
            "shadow_summary": shadow,
        }

        # Weekly summary on Mondays
        is_monday = datetime.utcnow().weekday() == 0
        if is_monday and trades:
            summary = await _generate_summary(perf, weight_changes, shadow, len(trades))
            conn.execute(
                """INSERT OR IGNORE INTO trading_morning_briefs (brief_date, content)
                   VALUES (date('now'), ?)""",
                (f"[WEEKLY SUMMARY]\n{summary}",),
            )
            conn.commit()
            log.info("Weekly performance summary generated")

    except Exception:
        conn.rollback()
        log.exception("Learning engine failed")
        result["error"] = "learning_engine_failed"
    finally:
        conn.close()

    return result
