"""
Universe management — the tickers each pool watches.
Seeds trading_universe on first init; maintained via DB after that.
"""
import sqlite3

from db import DB_PATH

# Top ~100 S&P 500 + NASDAQ 100 names by market cap.
# Excludes tickers that are hard to resolve cleanly in IBKR (e.g. BRK.B).
STOCK_TICKERS: list[str] = [
    # Mega-cap tech
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "GOOG", "META", "TSLA", "AVGO",
    # Financials
    "JPM", "V", "MA", "BAC", "GS", "MS", "AXP", "BLK", "WFC",
    # Healthcare
    "LLY", "UNH", "JNJ", "ABBV", "MRK", "BMY", "AMGN", "GILD", "REGN", "ISRG",
    # Consumer
    "PG", "KO", "PEP", "MCD", "COST", "WMT", "HD", "TGT", "NKE", "SBUX",
    # Energy
    "XOM", "CVX", "COP", "SLB", "EOG",
    # Industrials
    "CAT", "GE", "UNP", "HON", "RTX", "BA", "DE", "LMT",
    # Semiconductors
    "AMD", "QCOM", "TXN", "INTC", "AMAT", "LRCX", "KLAC", "MRVL", "MCHP", "NXPI",
    # Software / Cloud
    "ORCL", "CRM", "ADBE", "INTU", "NOW", "PANW", "SNPS", "CDNS", "FTNT", "ABNB",
    # Other NASDAQ 100
    "NFLX", "CSCO", "ACN", "TMO", "DHR", "PDD", "MELI", "DXCM", "IDXX", "CTAS",
    # Diversified
    "LIN", "EQIX", "PLD", "AMT", "DIS", "CMCSA", "T", "VZ",
]

# Top-20 crypto by market cap available on Coinbase (product_id format = SYMBOL-USD).
CRYPTO_PRODUCTS: list[str] = [
    "BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "DOGE-USD",
    "ADA-USD", "AVAX-USD", "LINK-USD", "DOT-USD", "MATIC-USD",
    "UNI-USD", "LTC-USD", "BCH-USD", "ATOM-USD", "FIL-USD",
    "ALGO-USD", "NEAR-USD", "APT-USD", "ARB-USD", "OP-USD",
]


def seed_universe():
    """Insert default tickers if the universe table is empty. Safe to call on every start."""
    conn = sqlite3.connect(DB_PATH)
    try:
        existing = conn.execute(
            "SELECT COUNT(*) FROM trading_universe"
        ).fetchone()[0]
        if existing > 0:
            return  # already seeded

        conn.executemany(
            "INSERT OR IGNORE INTO trading_universe (pool, ticker) VALUES (?, ?)",
            [("stocks", t) for t in STOCK_TICKERS],
        )
        conn.executemany(
            "INSERT OR IGNORE INTO trading_universe (pool, ticker) VALUES (?, ?)",
            [("crypto", t) for t in CRYPTO_PRODUCTS],
        )
        conn.commit()
    finally:
        conn.close()


def get_active_tickers(pool: str) -> list[dict]:
    """Return [{"ticker": ...}] for active tickers in the given pool."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT ticker FROM trading_universe WHERE pool = ? AND active = 1",
            (pool,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
