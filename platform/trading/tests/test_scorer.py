"""
Unit tests for validator/scorer.py — pure conviction math.
No DB, no network required.
Run: pytest platform/trading/tests/test_scorer.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from validator.scorer import (
    calculate_conviction,
    apply_temporal_modifier,
    determine_action,
    score,
    _DEFAULTS,
)

W = dict(_DEFAULTS)  # default weights for all tests


# ── calculate_conviction ──────────────────────────────────────────────────────

def test_single_signal_momentum():
    result = calculate_conviction({"momentum": 80.0}, W)
    # w=1.0, numerator=80, denominator=1.0 → 80.0
    assert result == 80.0


def test_single_signal_wsb_dd():
    result = calculate_conviction({"wsb_dd": 60.0}, W)
    # w=0.8, numerator=48, denominator=0.8 → 60.0
    assert result == 60.0


def test_two_signals_weighted_average():
    # momentum(1.0)×80 + wsb_dd(0.8)×60 = 80+48=128, denom=1.8 → ~71.11
    result = calculate_conviction({"momentum": 80.0, "wsb_dd": 60.0}, W)
    assert abs(result - 71.11) < 0.1


def test_all_four_signals():
    strengths = {
        "momentum": 80.0,
        "wsb_dd": 70.0,
        "wsb_mentions": 50.0,
        "wsb_correlation": 75.0,
    }
    # 1.0×80 + 0.8×70 + 0.4×50 + 1.1×75 = 80+56+20+82.5 = 238.5
    # denom = 1.0+0.8+0.4+1.1 = 3.3 → 72.27
    result = calculate_conviction(strengths, W)
    assert abs(result - 72.27) < 0.1


def test_empty_signals_returns_zero():
    assert calculate_conviction({}, W) == 0.0


def test_unknown_signal_type_ignored():
    # unknown types don't blow up and don't contribute
    result = calculate_conviction({"momentum": 80.0, "alien_signal": 100.0}, W)
    assert result == 80.0


def test_conviction_capped_at_100():
    result = calculate_conviction({"momentum": 100.0, "wsb_dd": 100.0}, W)
    assert result <= 100.0


def test_absent_signal_not_penalised():
    # Only momentum fired. wsb_dd being absent should NOT drag conviction to 0.
    result_just_momentum = calculate_conviction({"momentum": 80.0}, W)
    assert result_just_momentum == 80.0  # not (80×1.0 + 0×0.8) / 1.8 = ~44


# ── apply_temporal_modifier ───────────────────────────────────────────────────

def test_pre_catalyst_halves_conviction():
    conv, override = apply_temporal_modifier(80.0, "pre_catalyst", W)
    assert conv == 40.0
    assert override == "WATCH"


def test_post_catalyst_positive_boosts():
    conv, override = apply_temporal_modifier(80.0, "post_catalyst_positive", W)
    assert conv == 100.0  # 80 × 1.3 = 104, capped at 100
    assert override is None


def test_post_catalyst_positive_no_cap():
    conv, override = apply_temporal_modifier(50.0, "post_catalyst_positive", W)
    assert conv == 65.0  # 50 × 1.3
    assert override is None


def test_post_catalyst_negative_skips():
    conv, override = apply_temporal_modifier(95.0, "post_catalyst_negative", W)
    assert conv == 0.0
    assert override == "SKIP"


def test_neutral_no_change():
    conv, override = apply_temporal_modifier(72.5, "neutral", W)
    assert conv == 72.5
    assert override is None


# ── determine_action ──────────────────────────────────────────────────────────

def test_action_buy_at_threshold():
    assert determine_action(70.0, 70.0) == "BUY"


def test_action_buy_above_threshold():
    assert determine_action(85.0, 70.0) == "BUY"


def test_action_watch_at_lower_band():
    # 70 × 0.7 = 49.0
    assert determine_action(49.0, 70.0) == "WATCH"


def test_action_watch_just_below_buy():
    assert determine_action(69.9, 70.0) == "WATCH"


def test_action_skip_below_watch():
    assert determine_action(48.9, 70.0) == "SKIP"


def test_action_skip_zero():
    assert determine_action(0.0, 70.0) == "SKIP"


# ── score (full pipeline) ─────────────────────────────────────────────────────

def test_score_buy_neutral():
    conviction, action = score({"momentum": 90.0}, "neutral", W)
    assert action == "BUY"
    assert conviction == 90.0


def test_score_pre_catalyst_forces_watch():
    # conviction 90 → after pre_catalyst mod ×0.5 = 45, above 49 band? 45 < 49 → SKIP
    # BUT pre_catalyst override forces WATCH regardless of bands
    conviction, action = score({"momentum": 90.0}, "pre_catalyst", W)
    assert action == "WATCH"


def test_score_post_catalyst_negative_forces_skip():
    conviction, action = score({"momentum": 90.0, "wsb_dd": 80.0}, "post_catalyst_negative", W)
    assert action == "SKIP"
    assert conviction == 0.0


def test_score_returns_float_and_string():
    conviction, action = score({"momentum": 50.0}, "neutral", W)
    assert isinstance(conviction, float)
    assert isinstance(action, str)


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
