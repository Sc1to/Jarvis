"""
Unit tests for risk_gate.evaluate() — pure function, no I/O.
All 12 rules covered.
Run: pytest platform/trading/tests/test_risk_gate.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from risk_gate import evaluate


def _ctx(**overrides) -> dict:
    """Return a baseline context that PASSES all rules, with selected overrides."""
    base = {
        "pool": "stocks",
        "ticker": "AAPL",
        "conviction": 75.0,
        "position_size_proposed": 500.0,
        "current_price": 150.0,
        "pool_ceiling": 5000.0,
        "pool_value": 2000.0,
        "max_position_pct": 20.0,     # max single pos = 1000
        "max_sector_pct": 40.0,
        "sector_pct_current": 10.0,
        "daily_loss_pct": 1.0,
        "daily_loss_limit_pct": 5.0,
        "weekly_drawdown_pct_current": 3.0,
        "weekly_drawdown_pct": 15.0,
        "broker_authenticated": True,
        "ibkr_available": True,
        "market_open": True,
        "conviction_threshold": 70.0,
        "has_open_position": False,
        "has_pending_order": False,
    }
    base.update(overrides)
    return base


# ── Baseline passes ───────────────────────────────────────────────────────────

def test_baseline_passes():
    decision, rule, _ = evaluate(_ctx())
    assert decision == "PASS"
    assert rule is None


# ── Rule 1: POOL_CEILING ──────────────────────────────────────────────────────

def test_pool_ceiling_blocked():
    # pool_value=4800 + proposed=500 = 5300 > ceiling=5000
    decision, rule, _ = evaluate(_ctx(pool_value=4800.0, position_size_proposed=500.0))
    assert decision == "BLOCK"
    assert rule == "POOL_CEILING"


def test_pool_ceiling_exactly_at_limit_passes():
    # pool_value=4500 + proposed=500 = 5000 == ceiling → PASS (not strictly greater)
    decision, rule, _ = evaluate(_ctx(pool_value=4500.0, position_size_proposed=500.0))
    assert decision == "PASS"


# ── Rule 2: POSITION_SIZE_MAX ─────────────────────────────────────────────────

def test_position_size_max_blocked():
    # max_size = 5000 × 20% = 1000; proposed = 1100 → BLOCK
    decision, rule, _ = evaluate(_ctx(position_size_proposed=1100.0))
    assert decision == "BLOCK"
    assert rule == "POSITION_SIZE_MAX"


def test_position_size_exactly_at_max_passes():
    decision, rule, _ = evaluate(_ctx(position_size_proposed=1000.0))
    assert decision == "PASS"


# ── Rule 3: PORTFOLIO_CONCENTRATION ──────────────────────────────────────────

def test_sector_concentration_blocked():
    decision, rule, _ = evaluate(_ctx(sector_pct_current=45.0))
    assert decision == "BLOCK"
    assert rule == "PORTFOLIO_CONCENTRATION"


def test_sector_concentration_crypto_skipped():
    # Crypto pool — sector rule doesn't apply
    decision, rule, _ = evaluate(_ctx(pool="crypto", sector_pct_current=99.0))
    assert decision == "PASS"


def test_sector_concentration_exactly_at_limit_passes():
    decision, rule, _ = evaluate(_ctx(sector_pct_current=40.0))
    assert decision == "PASS"


# ── Rule 4: DAILY_LOSS_LIMIT ──────────────────────────────────────────────────

def test_daily_loss_limit_blocked():
    decision, rule, _ = evaluate(_ctx(daily_loss_pct=5.0))
    assert decision == "BLOCK"
    assert rule == "DAILY_LOSS_LIMIT"


def test_daily_loss_just_under_passes():
    decision, rule, _ = evaluate(_ctx(daily_loss_pct=4.99))
    assert decision == "PASS"


# ── Rule 5: WEEKLY_DRAWDOWN_LIMIT ────────────────────────────────────────────

def test_weekly_drawdown_blocked():
    decision, rule, _ = evaluate(_ctx(weekly_drawdown_pct_current=15.0))
    assert decision == "BLOCK"
    assert rule == "WEEKLY_DRAWDOWN_LIMIT"


def test_weekly_drawdown_just_under_passes():
    decision, rule, _ = evaluate(_ctx(weekly_drawdown_pct_current=14.99))
    assert decision == "PASS"


# ── Rule 6: BROKER_AUTH_REQUIRED ─────────────────────────────────────────────

def test_broker_not_authenticated_blocked():
    decision, rule, _ = evaluate(_ctx(broker_authenticated=False))
    assert decision == "BLOCK"
    assert rule == "BROKER_AUTH_REQUIRED"


# ── Rule 7: IBKR_SESSION_CHECK ───────────────────────────────────────────────

def test_ibkr_unavailable_blocks_stocks():
    decision, rule, _ = evaluate(_ctx(ibkr_available=False))
    assert decision == "BLOCK"
    assert rule == "IBKR_SESSION_CHECK"


def test_ibkr_unavailable_doesnt_block_crypto():
    decision, rule, _ = evaluate(_ctx(pool="crypto", ibkr_available=False))
    assert decision == "PASS"


# ── Rule 8: MARKET_HOURS_CHECK ────────────────────────────────────────────────

def test_market_closed_blocks_stocks():
    decision, rule, _ = evaluate(_ctx(market_open=False))
    assert decision == "BLOCK"
    assert rule == "MARKET_HOURS_CHECK"


def test_market_closed_doesnt_block_crypto():
    decision, rule, _ = evaluate(_ctx(pool="crypto", market_open=False))
    assert decision == "PASS"


# ── Rule 9: PENNY_STOCK_BLOCK ────────────────────────────────────────────────

def test_penny_stock_blocked():
    decision, rule, _ = evaluate(_ctx(current_price=4.99))
    assert decision == "BLOCK"
    assert rule == "PENNY_STOCK_BLOCK"


def test_exactly_five_dollars_passes():
    decision, rule, _ = evaluate(_ctx(current_price=5.0))
    assert decision == "PASS"


def test_no_price_data_passes():
    # If price unavailable, don't block (safer than blocking good signals)
    decision, rule, _ = evaluate(_ctx(current_price=None))
    assert decision == "PASS"


def test_penny_stock_crypto_not_checked():
    # Crypto prices can be fractions of a dollar (e.g. DOGE)
    decision, rule, _ = evaluate(_ctx(pool="crypto", current_price=0.08))
    assert decision == "PASS"


# ── Rule 10: CONVICTION_MINIMUM ──────────────────────────────────────────────

def test_conviction_below_threshold_blocked():
    decision, rule, _ = evaluate(_ctx(conviction=65.0, conviction_threshold=70.0))
    assert decision == "BLOCK"
    assert rule == "CONVICTION_MINIMUM"


def test_conviction_exactly_at_threshold_passes():
    decision, rule, _ = evaluate(_ctx(conviction=70.0, conviction_threshold=70.0))
    assert decision == "PASS"


# ── Rule 11: DUPLICATE_POSITION ──────────────────────────────────────────────

def test_duplicate_position_blocked():
    decision, rule, _ = evaluate(_ctx(has_open_position=True))
    assert decision == "BLOCK"
    assert rule == "DUPLICATE_POSITION"


# ── Rule 12: EXISTING_ORDER ──────────────────────────────────────────────────

def test_existing_order_blocked():
    decision, rule, _ = evaluate(_ctx(has_pending_order=True))
    assert decision == "BLOCK"
    assert rule == "EXISTING_ORDER"


# ── Rule ordering (earlier rules block before later ones) ────────────────────

def test_pool_ceiling_blocks_before_conviction():
    # Both pool ceiling and conviction are violated — ceiling is rule 1, conviction is 10
    ctx = _ctx(
        pool_value=4800.0,
        position_size_proposed=500.0,
        conviction=50.0,
    )
    decision, rule, _ = evaluate(ctx)
    assert rule == "POOL_CEILING"


def test_daily_loss_blocks_before_duplicate():
    ctx = _ctx(daily_loss_pct=5.0, has_open_position=True)
    decision, rule, _ = evaluate(ctx)
    assert rule == "DAILY_LOSS_LIMIT"


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
