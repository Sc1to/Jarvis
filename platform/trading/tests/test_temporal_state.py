"""
Unit tests for temporal state date math.
No DB, no network required.
Run: pytest platform/trading/tests/test_temporal_state.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import date, timedelta
from catalysts.temporal_state import (
    days_until,
    days_since,
    is_pre_catalyst,
    is_post_catalyst,
)


# ── days_until ────────────────────────────────────────────────────────────────

def test_days_until_tomorrow():
    tomorrow = date.today() + timedelta(days=1)
    assert days_until(tomorrow) == 1

def test_days_until_today():
    assert days_until(date.today()) == 0

def test_days_until_yesterday():
    yesterday = date.today() - timedelta(days=1)
    assert days_until(yesterday) == -1

def test_days_until_next_week():
    future = date.today() + timedelta(days=7)
    assert days_until(future) == 7


# ── days_since ────────────────────────────────────────────────────────────────

def test_days_since_yesterday():
    yesterday = date.today() - timedelta(days=1)
    assert days_since(yesterday) == 1

def test_days_since_today():
    assert days_since(date.today()) == 0

def test_days_since_tomorrow():
    tomorrow = date.today() + timedelta(days=1)
    assert days_since(tomorrow) == -1

def test_days_since_last_week():
    past = date.today() - timedelta(days=7)
    assert days_since(past) == 7


# ── is_pre_catalyst ───────────────────────────────────────────────────────────

def test_pre_catalyst_within_window():
    event = date.today() + timedelta(days=3)
    assert is_pre_catalyst(event, window_days=5) is True

def test_pre_catalyst_on_day_zero():
    # Event is today — count as pre-catalyst (0 days until = still the day of)
    assert is_pre_catalyst(date.today(), window_days=5) is True

def test_pre_catalyst_outside_window():
    event = date.today() + timedelta(days=10)
    assert is_pre_catalyst(event, window_days=5) is False

def test_pre_catalyst_in_past():
    event = date.today() - timedelta(days=1)
    assert is_pre_catalyst(event, window_days=5) is False

def test_pre_catalyst_exactly_at_boundary():
    event = date.today() + timedelta(days=5)
    assert is_pre_catalyst(event, window_days=5) is True

def test_pre_catalyst_one_beyond_boundary():
    event = date.today() + timedelta(days=6)
    assert is_pre_catalyst(event, window_days=5) is False


# ── is_post_catalyst ──────────────────────────────────────────────────────────

def test_post_catalyst_yesterday():
    event = date.today() - timedelta(days=1)
    assert is_post_catalyst(event, window_days=3) is True

def test_post_catalyst_today():
    assert is_post_catalyst(date.today(), window_days=3) is True

def test_post_catalyst_future():
    event = date.today() + timedelta(days=1)
    assert is_post_catalyst(event, window_days=3) is False

def test_post_catalyst_outside_window():
    event = date.today() - timedelta(days=5)
    assert is_post_catalyst(event, window_days=3) is False

def test_post_catalyst_exactly_at_boundary():
    event = date.today() - timedelta(days=3)
    assert is_post_catalyst(event, window_days=3) is True

def test_post_catalyst_one_beyond_boundary():
    event = date.today() - timedelta(days=4)
    assert is_post_catalyst(event, window_days=3) is False


# ── State relationship invariants ─────────────────────────────────────────────

def test_pre_and_post_never_both_true():
    """A single event date cannot be both pre- and post-catalyst."""
    for offset in range(-10, 11):
        event = date.today() + timedelta(days=offset)
        pre = is_pre_catalyst(event, window_days=5)
        post = is_post_catalyst(event, window_days=5)
        assert not (pre and post), f"Both true at offset {offset}"

def test_calendar_fiscal_quarter():
    from catalysts.calendar import _fiscal_quarter
    assert _fiscal_quarter("2024-03-31") == "1"
    assert _fiscal_quarter("2024-06-30") == "2"
    assert _fiscal_quarter("2024-09-30") == "3"
    assert _fiscal_quarter("2024-12-31") == "4"
    assert _fiscal_quarter("") == "?"
    assert _fiscal_quarter("bad") == "?"


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
