"""
Unit tests for auditor/rules.py — pure functions, no I/O.
Run: pytest platform/trading/tests/test_auditor_rules.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timedelta, timezone
from auditor.rules import (
    pool_ceiling_breach,
    position_size_breach,
    daily_loss_breach,
    weekly_drawdown_breach,
    data_is_stale,
    order_is_orphaned,
    pool_loss_pct,
)


# ── pool_ceiling_breach ───────────────────────────────────────────────────────

def test_ceiling_breach_over():
    assert pool_ceiling_breach(5100.0, 5000.0) is True

def test_ceiling_breach_under():
    assert pool_ceiling_breach(4999.0, 5000.0) is False

def test_ceiling_breach_exactly_at():
    assert pool_ceiling_breach(5000.0, 5000.0) is False  # equal is fine


# ── position_size_breach ──────────────────────────────────────────────────────

def test_position_size_over():
    # max = 5000 × 20% = 1000; cost_basis = 1100
    assert position_size_breach(1100.0, 5000.0, 20.0) is True

def test_position_size_under():
    assert position_size_breach(900.0, 5000.0, 20.0) is False

def test_position_size_exactly_at_max():
    assert position_size_breach(1000.0, 5000.0, 20.0) is False


# ── daily_loss_breach ─────────────────────────────────────────────────────────

def test_daily_loss_at_limit():
    assert daily_loss_breach(5.0, 5.0) is True

def test_daily_loss_over_limit():
    assert daily_loss_breach(6.0, 5.0) is True

def test_daily_loss_under_limit():
    assert daily_loss_breach(4.9, 5.0) is False

def test_daily_loss_zero():
    assert daily_loss_breach(0.0, 5.0) is False


# ── weekly_drawdown_breach ────────────────────────────────────────────────────

def test_weekly_drawdown_at_limit():
    assert weekly_drawdown_breach(15.0, 15.0) is True

def test_weekly_drawdown_over():
    assert weekly_drawdown_breach(20.0, 15.0) is True

def test_weekly_drawdown_under():
    assert weekly_drawdown_breach(14.9, 15.0) is False


# ── data_is_stale ─────────────────────────────────────────────────────────────

def _iso_ago(minutes: int) -> str:
    return (datetime.utcnow() - timedelta(minutes=minutes)).isoformat()

def test_data_stale_old():
    assert data_is_stale(_iso_ago(90), max_age_minutes=60) is True

def test_data_fresh():
    assert data_is_stale(_iso_ago(30), max_age_minutes=60) is False

def test_data_stale_none():
    assert data_is_stale(None) is True

def test_data_stale_bad_format():
    assert data_is_stale("not-a-date") is True

def test_data_at_exact_boundary():
    # Exactly 60 minutes old — stale (timedelta > not >=)
    iso = _iso_ago(61)
    assert data_is_stale(iso, max_age_minutes=60) is True


# ── order_is_orphaned ─────────────────────────────────────────────────────────

def test_order_orphaned():
    assert order_is_orphaned(_iso_ago(45), max_age_minutes=30) is True

def test_order_not_orphaned():
    assert order_is_orphaned(_iso_ago(10), max_age_minutes=30) is False

def test_order_none_submitted_at():
    assert order_is_orphaned(None) is False

def test_order_bad_format():
    assert order_is_orphaned("garbage") is False


# ── pool_loss_pct ─────────────────────────────────────────────────────────────

def test_pool_loss_pct_profit():
    # Positive PnL → 0% loss
    assert pool_loss_pct(500.0, 5000.0) == 0.0

def test_pool_loss_pct_loss():
    # -250 on 5000 ceiling → 5%
    assert abs(pool_loss_pct(-250.0, 5000.0) - 5.0) < 0.001

def test_pool_loss_pct_zero_pnl():
    assert pool_loss_pct(0.0, 5000.0) == 0.0

def test_pool_loss_pct_zero_ceiling():
    # Avoid division by zero
    assert pool_loss_pct(-100.0, 0.0) == 0.0


if __name__ == "__main__":
    fns = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
        except Exception as e:
            print(f"  FAIL  {fn.__name__}: {e}")
            failed += 1
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
