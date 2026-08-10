"""
Temporal state engine — 13.9
Determines whether a ticker is in pre_catalyst, post_catalyst, or neutral state.
Called by trading_validator_signal (13.10) before scoring conviction.

This module is pure logic against the DB — no network calls, no LLM.
"""
import sqlite3
from datetime import date, timedelta

from db import DB_PATH

# Sentinel values used when no catalyst is present
_NO_STATE = {
    "state": "neutral",
    "catalyst": None,
    "days_to_event": None,
    "days_since_event": None,
}


def get_temporal_state(ticker: str) -> dict:
    """
    Returns:
      state:             'pre_catalyst' | 'post_catalyst_positive' |
                         'post_catalyst_negative' | 'neutral'
      catalyst:          catalyst row dict, or None
      days_to_event:     int if pre_catalyst, else None
      days_since_event:  int if post_catalyst, else None
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        pre_days = int(_cfg(conn, "pre_catalyst_days") or 5)
        post_days = int(_cfg(conn, "post_catalyst_days") or 3)
        today = date.today()

        # --- Pre-catalyst: upcoming event within window ------------------
        upcoming = conn.execute(
            """SELECT * FROM trading_catalysts
               WHERE ticker = ?
               AND temporal_state = 'upcoming'
               AND event_date >= ?
               AND event_date <= ?
               ORDER BY event_date ASC LIMIT 1""",
            (ticker, today.isoformat(), (today + timedelta(days=pre_days)).isoformat()),
        ).fetchone()

        if upcoming:
            event_date = date.fromisoformat(upcoming["event_date"])
            return {
                "state": "pre_catalyst",
                "catalyst": dict(upcoming),
                "days_to_event": days_until(event_date),
                "days_since_event": None,
            }

        # --- Post-catalyst: resolved event within window -----------------
        recent = conn.execute(
            """SELECT * FROM trading_catalysts
               WHERE ticker = ?
               AND temporal_state IN ('resolved_positive', 'resolved_negative')
               AND event_date >= ?
               AND event_date < ?
               ORDER BY event_date DESC LIMIT 1""",
            (
                ticker,
                (today - timedelta(days=post_days)).isoformat(),
                today.isoformat(),
            ),
        ).fetchone()

        if recent:
            event_date = date.fromisoformat(recent["event_date"])
            outcome = recent["temporal_state"]  # 'resolved_positive' or 'resolved_negative'
            state = (
                "post_catalyst_positive"
                if outcome == "resolved_positive"
                else "post_catalyst_negative"
            )
            return {
                "state": state,
                "catalyst": dict(recent),
                "days_to_event": None,
                "days_since_event": days_since(event_date),
            }

        return dict(_NO_STATE)

    finally:
        conn.close()


def get_batch_states(tickers: list[str]) -> dict[str, dict]:
    """Efficient bulk lookup — one DB connection for multiple tickers."""
    return {t: get_temporal_state(t) for t in tickers}


def mark_resolved(catalyst_id: int, outcome: str, notes: str = ""):
    """
    Mark a catalyst as resolved after the event date passes.
    outcome: 'resolved_positive' | 'resolved_negative'
    Called by the user via API or by the expiry handler for auto-expiry.
    """
    if outcome not in ("resolved_positive", "resolved_negative"):
        raise ValueError(f"Invalid outcome: {outcome}")
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            """UPDATE trading_catalysts
               SET temporal_state = ?, outcome_notes = ?
               WHERE id = ?""",
            (outcome, notes, catalyst_id),
        )
        conn.commit()
    finally:
        conn.close()


# ── Pure date math (testable without DB) ──────────────────────────────────────

def days_until(event: date) -> int:
    """Calendar days from today to event_date. Negative if in the past."""
    return (event - date.today()).days


def days_since(event: date) -> int:
    """Calendar days from event_date to today. Negative if in the future."""
    return (date.today() - event).days


def is_pre_catalyst(event_date: date, window_days: int) -> bool:
    d = days_until(event_date)
    return 0 <= d <= window_days


def is_post_catalyst(event_date: date, window_days: int) -> bool:
    d = days_since(event_date)
    return 0 <= d <= window_days


def _cfg(conn, key: str) -> str:
    row = conn.execute("SELECT value FROM trading_config WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else ""
