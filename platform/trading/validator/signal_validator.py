"""
13.10 — trading_validator_signal
Runs every 10 minutes. Finds tickers with new raw signals (last 2h) that
have NOT yet received a conviction signal (last 1h), scores them, calls
Ollama for a human-readable rationale, and writes a 'conviction' signal row.
"""
import json
import logging
import sqlite3

import httpx

from db import DB_PATH, OLLAMA_BASE, get_config
from validator.scorer import score

log = logging.getLogger(__name__)

OLLAMA_URL = f"{OLLAMA_BASE}/api/generate"
OLLAMA_MODEL = "qwen2.5:14b"

_RAW_TYPES = ("momentum", "wsb_dd", "wsb_mentions", "wsb_correlation")


def _load_weights(conn: sqlite3.Connection) -> dict[str, float]:
    rows = conn.execute(
        "SELECT weight_key, weight_value FROM trading_learning_weights"
    ).fetchall()
    return {r["weight_key"]: r["weight_value"] for r in rows}


def _pending_tickers(conn: sqlite3.Connection) -> list[dict]:
    """
    Return tickers that have at least one raw signal in the last 2h
    and no conviction signal in the last 1h.
    """
    rows = conn.execute(
        """
        SELECT DISTINCT pool, ticker
        FROM trading_signals
        WHERE signal_type IN ('momentum','wsb_dd','wsb_mentions','wsb_correlation')
          AND timestamp >= datetime('now', '-2 hours')
          AND (pool, ticker) NOT IN (
              SELECT pool, ticker
              FROM trading_signals
              WHERE signal_type = 'conviction'
                AND timestamp >= datetime('now', '-1 hour')
          )
        """
    ).fetchall()
    return [{"pool": r["pool"], "ticker": r["ticker"]} for r in rows]


def _best_signals(conn: sqlite3.Connection, pool: str, ticker: str) -> dict[str, float]:
    """
    For each raw signal type, take the maximum strength seen in the last 2h.
    Only signal types that actually fired are returned (missing = absent, not 0).
    """
    rows = conn.execute(
        """
        SELECT signal_type, MAX(strength) as max_strength
        FROM trading_signals
        WHERE pool = ? AND ticker = ?
          AND signal_type IN ('momentum','wsb_dd','wsb_mentions','wsb_correlation')
          AND timestamp >= datetime('now', '-2 hours')
        GROUP BY signal_type
        """,
        (pool, ticker),
    ).fetchall()
    return {r["signal_type"]: (r["max_strength"] or 0.0) for r in rows}


def _build_rationale_prompt(
    ticker: str,
    pool: str,
    signal_strengths: dict[str, float],
    temporal_state: str,
    conviction: float,
    action: str,
) -> str:
    signals_text = "\n".join(
        f"  - {sig_type}: strength {strength:.1f}/100"
        for sig_type, strength in signal_strengths.items()
    )
    return (
        f"You are a trading analyst writing a brief rationale for a signal decision.\n\n"
        f"Ticker: {ticker} ({pool} pool)\n"
        f"Signals fired:\n{signals_text}\n"
        f"Temporal state: {temporal_state}\n"
        f"Conviction score: {conviction:.1f}/100\n"
        f"Decision: {action}\n\n"
        f"Write one or two sentences explaining this decision. "
        f"Be specific about what drove the conviction score. "
        f"Respond with plain text only, no JSON, no bullet points."
    )


def _template_rationale(
    ticker: str,
    signal_strengths: dict[str, float],
    conviction: float,
    action: str,
) -> str:
    drivers = ", ".join(signal_strengths.keys())
    return (
        f"{action} signal for {ticker}: conviction {conviction:.1f}/100 "
        f"based on {drivers} signals. (Ollama offline — template rationale)"
    )


async def _get_rationale(prompt: str, fallback: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                OLLAMA_URL,
                json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            )
            resp.raise_for_status()
            return resp.json().get("response", fallback).strip()
    except Exception as exc:
        log.warning("Ollama unavailable for rationale: %s", exc)
        return fallback


def _emit_conviction(
    conn: sqlite3.Connection,
    pool: str,
    ticker: str,
    conviction: float,
    action: str,
    rationale: str,
    signal_strengths: dict[str, float],
) -> None:
    conn.execute(
        """
        INSERT INTO trading_signals
            (pool, ticker, signal_type, direction, strength, metadata, conviction, action, rationale)
        VALUES (?, ?, 'conviction', ?, ?, ?, ?, ?, ?)
        """,
        (
            pool,
            ticker,
            action,
            conviction,
            json.dumps({"components": signal_strengths}),
            conviction,
            action,
            rationale,
        ),
    )


async def run() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    try:
        weights = _load_weights(conn)
        threshold = float(get_config(conn, "conviction_threshold") or 70)
        pending = _pending_tickers(conn)

        if not pending:
            log.debug("Signal validator: no pending tickers")
            return

        log.info("Signal validator: scoring %d tickers", len(pending))

        for item in pending:
            pool, ticker = item["pool"], item["ticker"]
            signal_strengths = _best_signals(conn, pool, ticker)

            if not signal_strengths:
                continue

            # Temporal state (no DB needed — reads catalysts table inline)
            from catalysts.temporal_state import get_temporal_state
            state_info = get_temporal_state(ticker)
            temporal_state = state_info["state"]

            conviction, action = score(signal_strengths, temporal_state, weights, threshold)

            prompt = _build_rationale_prompt(
                ticker, pool, signal_strengths, temporal_state, conviction, action
            )
            fallback = _template_rationale(ticker, signal_strengths, conviction, action)
            rationale = await _get_rationale(prompt, fallback)

            _emit_conviction(conn, pool, ticker, conviction, action, rationale, signal_strengths)
            conn.commit()

            log.info(
                "Conviction signal: %s %s — action=%s conviction=%.1f state=%s",
                pool, ticker, action, conviction, temporal_state,
            )

    except Exception:
        conn.rollback()
        log.exception("Signal validator failed")
        raise
    finally:
        conn.close()
