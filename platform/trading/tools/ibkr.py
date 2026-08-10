"""
IBKR TWS wrapper via ib_insync.
TWS runs locally, managed by IBC + Xvfb for headless operation.
Paper trading: port 7497   Live trading: port 7496

Connection is a module-level singleton — connect once, reuse across all calls.
util.patchAsyncio() lets ib_insync run inside FastAPI's already-running event loop.
"""
import asyncio
import logging
import os

from ib_insync import IB, Stock, MarketOrder, util

log = logging.getLogger(__name__)

util.patchAsyncio()

_HOST        = os.environ.get("IBKR_TWS_HOST", "127.0.0.1")
_PAPER_PORT  = int(os.environ.get("IBKR_TWS_PORT_PAPER", "7497"))
_LIVE_PORT   = int(os.environ.get("IBKR_TWS_PORT_LIVE",  "7496"))
_CLIENT_ID   = int(os.environ.get("IBKR_CLIENT_ID", "1"))

_ib: IB | None = None
_connected_port: int = 0


def _port(mode: str) -> int:
    return _LIVE_PORT if mode == "live" else _PAPER_PORT


async def _get_ib(mode: str) -> IB:
    global _ib, _connected_port
    port = _port(mode)
    if _ib is not None and _ib.isConnected() and _connected_port == port:
        return _ib
    if _ib is not None:
        _ib.disconnect()
    ib = IB()
    await ib.connectAsync(_HOST, port, clientId=_CLIENT_ID)
    _ib = ib
    _connected_port = port
    log.info("Connected to TWS %s:%d clientId=%d", _HOST, port, _CLIENT_ID)
    return _ib


async def is_connected(mode: str = "paper") -> bool:
    try:
        ib = await _get_ib(mode)
        return ib.isConnected()
    except Exception:
        return False


async def get_price(ticker: str, mode: str) -> float | None:
    ib = await _get_ib(mode)
    contract = Stock(ticker, "SMART", "USD")
    qualified = await ib.qualifyContractsAsync(contract)
    if not qualified:
        log.warning("Cannot qualify contract for %s", ticker)
        return None
    (data,) = await ib.reqTickersAsync(qualified[0])
    price = data.last or data.ask or data.bid
    return float(price) if price and price > 0 else None


async def get_prices(tickers: list[str], mode: str) -> dict[str, float]:
    """Batch price fetch — one TWS round-trip for all tickers."""
    if not tickers:
        return {}
    ib = await _get_ib(mode)
    contracts = [Stock(t, "SMART", "USD") for t in tickers]
    qualified = await ib.qualifyContractsAsync(*contracts)
    if not qualified:
        return {}
    ticker_data = await ib.reqTickersAsync(*qualified)
    prices: dict[str, float] = {}
    for td in ticker_data:
        sym = td.contract.symbol
        price = td.last or td.ask or td.bid
        if price and price > 0:
            prices[sym] = float(price)
    return prices


async def place_order(
    ticker: str, side: str, quantity: float, mode: str
) -> tuple[str, float | None]:
    """
    Place a market order through TWS.
    Returns (broker_order_id, fill_price).
    fill_price is None if the fill confirmation doesn't arrive within 30s.
    """
    ib = await _get_ib(mode)
    contract = Stock(ticker, "SMART", "USD")
    qualified = await ib.qualifyContractsAsync(contract)
    if not qualified:
        raise ValueError(f"Cannot qualify contract for {ticker}")
    order = MarketOrder(side, quantity)
    trade = ib.placeOrder(qualified[0], order)
    try:
        await asyncio.wait_for(trade.doneAsync(), timeout=30)
    except asyncio.TimeoutError:
        log.warning("Fill timeout for %s %s %s — order may still fill", side, quantity, ticker)
    broker_id = str(trade.order.orderId)
    fill_price = float(trade.fills[-1].execution.avgPrice) if trade.fills else None
    return broker_id, fill_price


async def get_history(
    ticker: str,
    mode: str,
    duration: str = "1 D",
    bar_size: str = "5 mins",
) -> list[dict]:
    """OHLCV bars from TWS. Returns list of {t, o, h, l, c, v}."""
    ib = await _get_ib(mode)
    contract = Stock(ticker, "SMART", "USD")
    qualified = await ib.qualifyContractsAsync(contract)
    if not qualified:
        return []
    bars = await ib.reqHistoricalDataAsync(
        qualified[0],
        endDateTime="",
        durationStr=duration,
        barSizeSetting=bar_size,
        whatToShow="TRADES",
        useRTH=True,
        formatDate=1,
    )
    return [{"t": b.date, "o": b.open, "h": b.high, "l": b.low, "c": b.close, "v": b.volume} for b in bars]
