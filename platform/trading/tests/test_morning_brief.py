"""
Unit tests for morning_brief pure functions — no DB, no network.
Run: pytest platform/trading/tests/test_morning_brief.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from morning_brief import (
    pool_overnight_pnl,
    summarise_position,
    summarise_order,
    summarise_block,
    build_pool_section,
    _template_narrative,
)


def _pos(**kw) -> dict:
    base = {
        "ticker": "AAPL", "quantity": 10, "entry_price": 100.0,
        "current_price": 110.0, "unrealised_pnl": 100.0,
        "realised_pnl": None, "trailing_stop": 104.5, "opened_at": "2026-08-07T09:30:00",
    }
    base.update(kw)
    return base


def _order(**kw) -> dict:
    base = {
        "ticker": "BTC", "direction": "BUY", "quantity": 0.1,
        "fill_price": 60000.0, "status": "simulated", "filled_at": "2026-08-08T02:00:00",
    }
    base.update(kw)
    return base


def _block(**kw) -> dict:
    base = {"ticker": "GME", "rule_violated": "DAILY_LOSS_LIMIT", "evaluated_at": "2026-08-08T03:00:00"}
    base.update(kw)
    return base


# ── pool_overnight_pnl ────────────────────────────────────────────────────────

def test_pnl_open_positions_only():
    open_pos = [_pos(unrealised_pnl=100.0), _pos(unrealised_pnl=50.0)]
    result = pool_overnight_pnl(open_pos, [])
    assert result == 150.0


def test_pnl_closed_today_only():
    closed = [_pos(realised_pnl=200.0, unrealised_pnl=0), _pos(realised_pnl=-30.0, unrealised_pnl=0)]
    result = pool_overnight_pnl([], closed)
    assert abs(result - 170.0) < 0.01


def test_pnl_combined():
    open_pos = [_pos(unrealised_pnl=50.0)]
    closed = [_pos(realised_pnl=100.0, unrealised_pnl=0)]
    result = pool_overnight_pnl(open_pos, closed)
    assert abs(result - 150.0) < 0.01


def test_pnl_none_values_treated_as_zero():
    open_pos = [_pos(unrealised_pnl=None)]
    closed = [_pos(realised_pnl=None, unrealised_pnl=0)]
    result = pool_overnight_pnl(open_pos, closed)
    assert result == 0.0


def test_pnl_negative():
    open_pos = [_pos(unrealised_pnl=-200.0)]
    result = pool_overnight_pnl(open_pos, [])
    assert result == -200.0


def test_pnl_empty():
    assert pool_overnight_pnl([], []) == 0.0


# ── summarise_position ────────────────────────────────────────────────────────

def test_summarise_position_keys():
    result = summarise_position(_pos())
    assert "ticker" in result
    assert "unrealised_pnl" in result
    assert "trailing_stop" in result
    assert "entry_price" in result
    # Should NOT include DB-internal fields like id, status, pool
    assert "status" not in result
    assert "pool" not in result


def test_summarise_position_values():
    result = summarise_position(_pos(ticker="TSLA", quantity=5))
    assert result["ticker"] == "TSLA"
    assert result["quantity"] == 5


# ── summarise_order ───────────────────────────────────────────────────────────

def test_summarise_order_keys():
    result = summarise_order(_order())
    assert "ticker" in result
    assert "fill_price" in result
    assert "direction" in result


# ── summarise_block ───────────────────────────────────────────────────────────

def test_summarise_block_keys():
    result = summarise_block(_block())
    assert "ticker" in result
    assert "rule_violated" in result
    assert "evaluated_at" in result


# ── build_pool_section ────────────────────────────────────────────────────────

def test_build_pool_section_structure():
    section = build_pool_section(
        open_positions=[_pos()],
        closed_today=[_pos(realised_pnl=50.0, unrealised_pnl=0)],
        overnight_orders=[_order()],
        blocked_signals=[_block()],
    )
    assert "open_positions" in section
    assert "overnight_pnl" in section
    assert "orders_overnight" in section
    assert "blocked_signals" in section
    assert "closed_today" in section


def test_build_pool_section_counts():
    section = build_pool_section(
        open_positions=[_pos(), _pos()],
        closed_today=[_pos(realised_pnl=10.0, unrealised_pnl=0)],
        overnight_orders=[_order(), _order()],
        blocked_signals=[_block()],
    )
    assert len(section["open_positions"]) == 2
    assert section["closed_today"] == 1
    assert len(section["orders_overnight"]) == 2
    assert len(section["blocked_signals"]) == 1


def test_build_pool_section_empty():
    section = build_pool_section([], [], [], [])
    assert section["open_positions"] == []
    assert section["overnight_pnl"] == 0.0
    assert section["orders_overnight"] == []
    assert section["blocked_signals"] == []


# ── _template_narrative ───────────────────────────────────────────────────────

def _empty_pool():
    return {"open_positions": [], "overnight_pnl": 0.0, "orders_overnight": [], "blocked_signals": []}


def test_template_narrative_returns_string():
    result = _template_narrative(_empty_pool(), _empty_pool(), "authenticated")
    assert isinstance(result, str)
    assert len(result) > 0


def test_template_narrative_contains_ibkr_status():
    result = _template_narrative(_empty_pool(), _empty_pool(), "unauthenticated")
    assert "unauthenticated" in result


def test_template_narrative_shows_positive_direction():
    stocks = {**_empty_pool(), "overnight_pnl": 100.0, "blocked_signals": []}
    result = _template_narrative(stocks, _empty_pool(), "authenticated")
    assert "up" in result


def test_template_narrative_shows_negative_direction():
    stocks = {**_empty_pool(), "overnight_pnl": -50.0, "blocked_signals": []}
    result = _template_narrative(stocks, _empty_pool(), "authenticated")
    assert "down" in result


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
