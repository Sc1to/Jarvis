"""
Unit tests for WSB mention velocity math and DD signal logic.
No network, no Reddit, no DB, no LLM required.
Run: pytest platform/trading/tests/test_wsb.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from wsb.mention_tracker import calculate_velocity, calculate_spike_factor, SPIKE_THRESHOLD
from wsb.dd_monitor import _parse_json


# ── Velocity math ─────────────────────────────────────────────────────────────

def test_velocity_zero_baseline():
    assert calculate_velocity(10, 0.0) == 0.0

def test_velocity_double():
    assert calculate_velocity(20, 10.0) == 100.0

def test_velocity_flat():
    assert calculate_velocity(10, 10.0) == 0.0

def test_velocity_decline():
    assert calculate_velocity(5, 10.0) == -50.0

def test_velocity_small_baseline():
    v = calculate_velocity(30, 10.0)
    assert v == 200.0


# ── Spike factor ──────────────────────────────────────────────────────────────

def test_spike_factor_zero_baseline():
    assert calculate_spike_factor(10, 0.0) == 1.0

def test_spike_factor_three_x():
    assert abs(calculate_spike_factor(30, 10.0) - 3.0) < 0.01

def test_spike_factor_at_threshold():
    sf = calculate_spike_factor(int(SPIKE_THRESHOLD * 10), 10.0)
    assert sf >= SPIKE_THRESHOLD

def test_spike_factor_normal():
    assert calculate_spike_factor(10, 10.0) == 1.0


# ── JSON parsing from LLM output ──────────────────────────────────────────────

def test_parse_json_clean():
    raw = '{"ticker": "AAPL", "quality_score": 75}'
    result = _parse_json(raw)
    assert result["ticker"] == "AAPL"
    assert result["quality_score"] == 75

def test_parse_json_wrapped_in_code_block():
    raw = '```json\n{"ticker": "MSFT", "quality_score": 60}\n```'
    result = _parse_json(raw)
    assert result is not None
    assert result["ticker"] == "MSFT"

def test_parse_json_invalid_returns_none():
    result = _parse_json("This is not JSON at all.")
    assert result is None

def test_parse_json_partial_json_extracted():
    raw = 'Here is the result: {"ticker": "NVDA", "quality_score": 80} end.'
    result = _parse_json(raw)
    assert result is not None
    assert result["ticker"] == "NVDA"

def test_parse_json_null_ticker():
    raw = '{"ticker": null, "thesis_summary": "unclear", "quality_score": 10}'
    result = _parse_json(raw)
    assert result["ticker"] is None
    assert result["quality_score"] == 10


# ── Quality threshold ─────────────────────────────────────────────────────────

def test_quality_threshold_boundary():
    from wsb.dd_monitor import QUALITY_THRESHOLD
    assert QUALITY_THRESHOLD == 40  # minimum to emit a signal

def test_spike_threshold_boundary():
    assert SPIKE_THRESHOLD == 3.0  # 3× baseline to trigger


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
