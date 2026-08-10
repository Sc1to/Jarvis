"""
Unit tests for learning_engine pure functions — no DB, no network.
Run: pytest platform/trading/tests/test_learning_engine.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from learning_engine import (
    pnl_pct,
    weight_adjustment,
    apply_adjustment,
    aggregate_performance,
)


# ── pnl_pct ───────────────────────────────────────────────────────────────────

def test_pnl_pct_profit():
    assert abs(pnl_pct(50.0, 1000.0) - 5.0) < 0.001

def test_pnl_pct_loss():
    assert abs(pnl_pct(-100.0, 1000.0) - (-10.0)) < 0.001

def test_pnl_pct_breakeven():
    assert pnl_pct(0.0, 1000.0) == 0.0

def test_pnl_pct_zero_cost_basis():
    assert pnl_pct(100.0, 0.0) == 0.0


# ── weight_adjustment ─────────────────────────────────────────────────────────

def test_adjustment_good_signal():
    # 80% win rate + 10% avg P&L → positive adjustment
    adj = weight_adjustment(avg_pnl_pct=10.0, win_rate=0.8, learning_rate=0.05)
    assert adj > 0

def test_adjustment_bad_signal():
    # 20% win rate + -10% avg P&L → negative adjustment
    adj = weight_adjustment(avg_pnl_pct=-10.0, win_rate=0.2, learning_rate=0.05)
    assert adj < 0

def test_adjustment_neutral_signal():
    # 50% win rate + 0% avg P&L → near-zero adjustment
    adj = weight_adjustment(avg_pnl_pct=0.0, win_rate=0.5, learning_rate=0.05)
    assert abs(adj) < 0.001

def test_adjustment_bounded_by_learning_rate():
    # Maximum possible adjustment = learning_rate (both signals at max)
    adj = weight_adjustment(avg_pnl_pct=100.0, win_rate=1.0, learning_rate=0.05)
    assert abs(adj) <= 0.05 + 1e-9

def test_adjustment_win_rate_dominates_with_zero_pnl():
    # 100% win rate, 0% avg P&L → positive (win signal wins)
    adj = weight_adjustment(avg_pnl_pct=0.0, win_rate=1.0, learning_rate=0.05)
    assert adj > 0

def test_adjustment_pnl_saturates_at_20pct():
    # 20% and 40% avg_pnl should give the same result (saturation)
    adj_20 = weight_adjustment(20.0, 0.5, 0.05)
    adj_40 = weight_adjustment(40.0, 0.5, 0.05)
    assert abs(adj_20 - adj_40) < 0.001


# ── apply_adjustment ──────────────────────────────────────────────────────────

def test_apply_positive_adjustment():
    result = apply_adjustment(1.0, 0.05, max_change=0.1)
    assert abs(result - 1.05) < 0.001

def test_apply_negative_adjustment():
    result = apply_adjustment(1.0, -0.05, max_change=0.1)
    assert abs(result - 0.95) < 0.001

def test_apply_caps_at_max_change():
    # adj=0.5 but max_change=0.1 → actual change is 0.1
    result = apply_adjustment(1.0, 0.5, max_change=0.1)
    assert abs(result - 1.1) < 0.001

def test_apply_clamps_at_floor():
    result = apply_adjustment(0.15, -0.5, max_change=0.1)
    assert result >= 0.1

def test_apply_clamps_at_ceiling():
    result = apply_adjustment(2.95, 0.5, max_change=0.1)
    assert result <= 3.0

def test_apply_no_change_on_zero_adj():
    assert apply_adjustment(1.2, 0.0, max_change=0.1) == 1.2


# ── aggregate_performance ─────────────────────────────────────────────────────

def _trade(signal_types, pnl):
    return {"signal_types": signal_types, "pnl_pct": pnl}

def test_aggregate_single_signal_winner():
    trades = [_trade(["momentum"], 5.0), _trade(["momentum"], 10.0)]
    perf = aggregate_performance(trades)
    assert "momentum" in perf
    assert perf["momentum"]["count"] == 2
    assert perf["momentum"]["win_rate"] == 1.0
    assert abs(perf["momentum"]["avg_pnl_pct"] - 7.5) < 0.001

def test_aggregate_mixed_outcomes():
    trades = [_trade(["wsb_dd"], 10.0), _trade(["wsb_dd"], -5.0)]
    perf = aggregate_performance(trades)
    assert perf["wsb_dd"]["win_rate"] == 0.5
    assert abs(perf["wsb_dd"]["avg_pnl_pct"] - 2.5) < 0.001

def test_aggregate_unknown_signal_ignored():
    trades = [_trade(["momentum", "alien_signal"], 5.0)]
    perf = aggregate_performance(trades)
    assert "momentum" in perf
    assert "alien_signal" not in perf

def test_aggregate_multiple_signals_per_trade():
    trades = [_trade(["momentum", "wsb_dd"], 8.0)]
    perf = aggregate_performance(trades)
    assert "momentum" in perf
    assert "wsb_dd" in perf
    assert perf["momentum"]["count"] == 1
    assert perf["wsb_dd"]["count"] == 1

def test_aggregate_empty_returns_empty():
    assert aggregate_performance([]) == {}

def test_aggregate_trade_with_no_signals():
    trades = [_trade([], 5.0)]
    assert aggregate_performance(trades) == {}

def test_aggregate_all_losses():
    trades = [_trade(["momentum"], -3.0), _trade(["momentum"], -7.0)]
    perf = aggregate_performance(trades)
    assert perf["momentum"]["win_rate"] == 0.0
    assert perf["momentum"]["avg_pnl_pct"] < 0


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
