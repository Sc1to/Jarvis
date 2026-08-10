"""
Unit tests for execution order sizing and ticker helpers.
No DB, no network required.
Run: pytest platform/trading/tests/test_execution.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from execution.stocks import _order_size_dollars as stocks_size
from execution.crypto import (
    _order_size_dollars as crypto_size,
    _ticker_to_product,
)


# ── Order size formula ────────────────────────────────────────────────────────

def test_stocks_full_conviction_full_pct():
    # 100% conviction, 20% of 5000 ceiling → $1000
    assert stocks_size(100.0, 20.0, 5000.0) == 1000.0


def test_stocks_half_conviction():
    # 50% conviction, 20% of 5000 → $500
    assert stocks_size(50.0, 20.0, 5000.0) == 500.0


def test_stocks_zero_conviction():
    assert stocks_size(0.0, 20.0, 5000.0) == 0.0


def test_crypto_full_conviction():
    # 100% conviction, 20% of 2000 → $400
    assert crypto_size(100.0, 20.0, 2000.0) == 400.0


def test_crypto_70_conviction():
    # 70% conviction, 20% of 2000 = 0.7 × 0.2 × 2000 = 280
    assert abs(crypto_size(70.0, 20.0, 2000.0) - 280.0) < 0.01


def test_size_scales_linearly_with_conviction():
    a = stocks_size(60.0, 20.0, 5000.0)
    b = stocks_size(80.0, 20.0, 5000.0)
    # 80/60 = 4/3, so b/a should be ~1.333
    assert abs(b / a - 80 / 60) < 0.001


def test_size_scales_linearly_with_ceiling():
    a = stocks_size(75.0, 20.0, 5000.0)
    b = stocks_size(75.0, 20.0, 10000.0)
    assert abs(b / a - 2.0) < 0.001


# ── Ticker → product_id (crypto) ─────────────────────────────────────────────

def test_ticker_to_product_bare():
    assert _ticker_to_product("BTC") == "BTC-USD"


def test_ticker_to_product_already_full():
    assert _ticker_to_product("BTC-USD") == "BTC-USD"


def test_ticker_to_product_eth():
    assert _ticker_to_product("ETH") == "ETH-USD"


def test_ticker_to_product_doge():
    assert _ticker_to_product("DOGE") == "DOGE-USD"


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
