"""
Unit tests for position_manager pure functions — no DB, no network.
Run: pytest platform/trading/tests/test_position_manager.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from position_manager import compute_stop, raise_stop, should_exit, unrealised_pnl, realised_pnl


# ── compute_stop ──────────────────────────────────────────────────────────────

def test_compute_stop_5pct():
    assert abs(compute_stop(100.0, 5.0) - 95.0) < 0.0001


def test_compute_stop_10pct():
    assert abs(compute_stop(200.0, 10.0) - 180.0) < 0.0001


def test_compute_stop_zero_pct():
    assert compute_stop(100.0, 0.0) == 100.0


# ── raise_stop ────────────────────────────────────────────────────────────────

def test_raise_stop_initialises_from_none():
    # No prior stop → initialise from current price
    result = raise_stop(None, 100.0, 5.0)
    assert abs(result - 95.0) < 0.0001


def test_raise_stop_moves_up_when_price_rises():
    # Prior stop at 95, price now 110 → new stop = 110 × 0.95 = 104.5
    result = raise_stop(95.0, 110.0, 5.0)
    assert abs(result - 104.5) < 0.0001


def test_raise_stop_does_not_lower():
    # Prior stop at 95, price dropped to 98 → candidate=93.1, keep 95
    result = raise_stop(95.0, 98.0, 5.0)
    assert result == 95.0


def test_raise_stop_same_price_unchanged():
    result = raise_stop(95.0, 100.0, 5.0)
    # candidate = 95.0, prior = 95.0 → max = 95.0
    assert abs(result - 95.0) < 0.0001


def test_raise_stop_monotonically_increases():
    stop = None
    prices = [100, 105, 110, 108, 115, 112, 120]
    for price in prices:
        stop = raise_stop(stop, price, 5.0)
    # Should be at least 120 × 0.95 = 114
    assert stop is not None and stop >= 120 * 0.95 - 0.001


def test_raise_stop_never_exceeds_price():
    stop = raise_stop(None, 100.0, 5.0)
    assert stop < 100.0


# ── should_exit ───────────────────────────────────────────────────────────────

def test_should_exit_when_at_stop():
    assert should_exit(95.0, 95.0) is True


def test_should_exit_when_below_stop():
    assert should_exit(90.0, 95.0) is True


def test_should_not_exit_above_stop():
    assert should_exit(100.0, 95.0) is False


def test_should_not_exit_when_no_stop():
    assert should_exit(50.0, None) is False


def test_should_exit_just_at_boundary():
    assert should_exit(95.0001, 95.0) is False
    assert should_exit(94.9999, 95.0) is True


# ── unrealised_pnl ────────────────────────────────────────────────────────────

def test_unrealised_pnl_profit():
    result = unrealised_pnl(100.0, 120.0, 10)
    assert result == 200.0


def test_unrealised_pnl_loss():
    result = unrealised_pnl(100.0, 90.0, 10)
    assert result == -100.0


def test_unrealised_pnl_breakeven():
    assert unrealised_pnl(100.0, 100.0, 10) == 0.0


# ── realised_pnl ──────────────────────────────────────────────────────────────

def test_realised_pnl_profit():
    result = realised_pnl(100.0, 130.0, 5)
    assert result == 150.0


def test_realised_pnl_loss():
    result = realised_pnl(100.0, 85.0, 5)
    assert result == -75.0


# ── Scenario: price rises then falls through stop ─────────────────────────────

def test_full_trailing_stop_scenario():
    stop = None
    pct = 5.0
    prices = [100, 110, 120, 115, 110, 105]  # rises to 120, then falls

    exited = False
    for price in prices:
        stop = raise_stop(stop, price, pct)
        if should_exit(price, stop):
            exited = True
            break

    # Stop was set at 120 × 0.95 = 114 and never lowered.
    # Price 115 > 114 → no exit.
    # Price 110 < 114 → exit triggered.
    assert exited is True


def test_no_exit_if_price_only_rises():
    stop = None
    for price in [100, 105, 110, 115, 120]:
        stop = raise_stop(stop, price, 5.0)
        assert not should_exit(price, stop)


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
