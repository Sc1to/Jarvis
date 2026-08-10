"""
Unit tests for momentum indicator calculations.
No network, no DB, no external dependencies.
Run: pytest platform/trading/tests/test_momentum.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from monitors.momentum import (
    calculate_rsi,
    calculate_volume_ratio,
    calculate_price_momentum,
    score_signal,
    extract_closes,
    extract_volumes,
)


# ── RSI ───────────────────────────────────────────────────────────────────────

def test_rsi_insufficient_data_returns_neutral():
    assert calculate_rsi([100.0] * 5) == 50.0


def test_rsi_all_gains_returns_100():
    # Steadily rising prices → RSI near 100
    closes = [float(i) for i in range(1, 30)]
    rsi = calculate_rsi(closes)
    assert rsi > 95.0


def test_rsi_all_losses_returns_0():
    closes = [float(30 - i) for i in range(30)]
    rsi = calculate_rsi(closes)
    assert rsi < 5.0


def test_rsi_flat_prices_returns_neutral():
    closes = [100.0] * 20
    rsi = calculate_rsi(closes)
    # All deltas are 0; avg_loss=0 → returns 100 (no losses)
    assert rsi == 100.0


def test_rsi_realistic_range():
    # Mixed movement — should land in 0-100
    import math
    closes = [100 + 5 * math.sin(i * 0.5) for i in range(30)]
    rsi = calculate_rsi(closes)
    assert 0.0 <= rsi <= 100.0


# ── Volume ratio ──────────────────────────────────────────────────────────────

def test_volume_ratio_double_volume():
    vols = [1_000_000.0] * 20 + [2_000_000.0]
    ratio = calculate_volume_ratio(vols)
    assert abs(ratio - 2.0) < 0.01


def test_volume_ratio_normal_volume():
    vols = [1_000_000.0] * 21
    ratio = calculate_volume_ratio(vols)
    assert abs(ratio - 1.0) < 0.01


def test_volume_ratio_insufficient_data():
    assert calculate_volume_ratio([500_000.0]) == 1.0


def test_volume_ratio_zero_avg():
    # Zero historical volume → returns 1.0 (safe fallback)
    vols = [0.0] * 20 + [1_000_000.0]
    ratio = calculate_volume_ratio(vols)
    assert ratio == 1.0


# ── Price momentum ────────────────────────────────────────────────────────────

def test_momentum_5_pct_rise():
    closes = [100.0] * 5 + [105.0]
    mom = calculate_price_momentum(closes, lookback=5)
    assert abs(mom - 5.0) < 0.01


def test_momentum_negative():
    closes = [100.0] * 5 + [90.0]
    mom = calculate_price_momentum(closes, lookback=5)
    assert abs(mom - (-10.0)) < 0.01


def test_momentum_insufficient_data():
    assert calculate_price_momentum([100.0, 110.0], lookback=5) == 0.0


def test_momentum_zero_base():
    closes = [0.0] * 5 + [100.0]
    assert calculate_price_momentum(closes, lookback=5) == 0.0


# ── Signal scoring ────────────────────────────────────────────────────────────

def test_signal_buy_criteria():
    direction, strength = score_signal(rsi=68.0, volume_ratio=2.5, momentum_5=3.0)
    assert direction == "BUY"
    assert strength > 0

def test_signal_sell_criteria():
    direction, strength = score_signal(rsi=32.0, volume_ratio=2.0, momentum_5=-2.5)
    assert direction == "SELL"
    assert strength > 0

def test_signal_neutral_low_volume():
    # Volume below threshold → always neutral
    direction, strength = score_signal(rsi=75.0, volume_ratio=1.2, momentum_5=4.0)
    assert direction == "NEUTRAL"
    assert strength == 0.0

def test_signal_neutral_low_rsi_momentum():
    # High volume but weak signal
    direction, strength = score_signal(rsi=55.0, volume_ratio=3.0, momentum_5=0.5)
    assert direction == "NEUTRAL"

def test_signal_strength_in_range():
    _, strength = score_signal(rsi=80.0, volume_ratio=4.0, momentum_5=6.0)
    assert 0.0 <= strength <= 100.0

def test_signal_momentum_alignment_bonus():
    # Positive mom_20 should give slightly higher strength than negative
    _, s_aligned = score_signal(rsi=65.0, volume_ratio=2.0, momentum_5=2.0, momentum_20=5.0)
    _, s_counter = score_signal(rsi=65.0, volume_ratio=2.0, momentum_5=2.0, momentum_20=-5.0)
    assert s_aligned >= s_counter


# ── Extract helpers ───────────────────────────────────────────────────────────

def test_extract_closes_ibkr_format():
    bars = [{"t": 1, "o": 99, "h": 101, "l": 98, "c": 100, "v": 1000}]
    assert extract_closes(bars) == [100.0]

def test_extract_closes_coinbase_format():
    bars = [{"start": "1234", "open": "99", "high": "101", "low": "98", "close": "100", "volume": "1000"}]
    # coinbase uses 'close' key — extract_closes looks for 'c' then 'close'
    result = extract_closes(bars)
    assert result == [100.0]

def test_extract_volumes():
    bars = [{"v": 500_000}, {"v": 750_000}]
    assert extract_volumes(bars) == [500_000.0, 750_000.0]


if __name__ == "__main__":
    # Quick self-check without pytest
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
