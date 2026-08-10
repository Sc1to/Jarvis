"""
Momentum indicators — pure math, no I/O, no external dependencies.
All functions operate on lists of floats (oldest-first OHLCV data).
"""


def calculate_rsi(closes: list[float], period: int = 14) -> float:
    """
    Wilder's RSI. Returns 50.0 (neutral) if insufficient data.
    Requires at least period+1 closes.
    """
    if len(closes) < period + 1:
        return 50.0

    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(d, 0.0) for d in deltas]
    losses = [abs(min(d, 0.0)) for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    # Wilder smoothing over remaining bars
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0.0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 2)


def calculate_volume_ratio(volumes: list[float], window: int = 20) -> float:
    """
    Current bar volume / mean of previous `window` bars.
    Returns 1.0 (neutral) if data is insufficient.
    """
    if len(volumes) < 2:
        return 1.0
    history = volumes[-(window + 1):-1]
    if not history:
        return 1.0
    avg = sum(history) / len(history)
    if avg == 0.0:
        return 1.0
    return round(volumes[-1] / avg, 3)


def calculate_price_momentum(closes: list[float], lookback: int = 5) -> float:
    """
    Percent price change from `lookback` bars ago to current bar.
    Positive = price rose, negative = price fell.
    Returns 0.0 if insufficient data.
    """
    if len(closes) < lookback + 1:
        return 0.0
    base = closes[-(lookback + 1)]
    if base == 0.0:
        return 0.0
    return round((closes[-1] - base) / base * 100.0, 3)


def score_signal(
    rsi: float,
    volume_ratio: float,
    momentum_5: float,
    momentum_20: float = 0.0,
) -> tuple[str, float]:
    """
    Combine indicators into a directional signal and a 0-100 strength score.

    Returns (direction, strength):
      direction: 'BUY' | 'SELL' | 'NEUTRAL'
      strength:  0-100 (higher = stronger conviction from momentum alone;
                 overall conviction is finalised by trading_validator_signal in 13.10)

    Thresholds:
      BUY:  RSI > 60, momentum_5 > 1.5%, volume_ratio > 1.5
      SELL: RSI < 40, momentum_5 < -1.5%, volume_ratio > 1.5

    Volume must be elevated in both cases — avoids signals on thin-volume noise.
    """
    if volume_ratio < 1.5:
        return "NEUTRAL", 0.0

    if rsi > 60.0 and momentum_5 > 1.5:
        # Contribution: RSI overshoot (0-40), volume spike (0-30), momentum (0-30)
        rsi_pts = min((rsi - 60.0) / 40.0 * 40.0, 40.0)
        vol_pts = min((volume_ratio - 1.0) / 3.0 * 30.0, 30.0)
        mom_pts = min(momentum_5 / 5.0 * 30.0, 30.0)
        # Longer-term momentum alignment adds a small bonus
        if momentum_20 > 0:
            mom_pts = min(mom_pts * 1.1, 30.0)
        return "BUY", round(rsi_pts + vol_pts + mom_pts, 1)

    if rsi < 40.0 and momentum_5 < -1.5:
        rsi_pts = min((40.0 - rsi) / 40.0 * 40.0, 40.0)
        vol_pts = min((volume_ratio - 1.0) / 3.0 * 30.0, 30.0)
        mom_pts = min(abs(momentum_5) / 5.0 * 30.0, 30.0)
        if momentum_20 < 0:
            mom_pts = min(mom_pts * 1.1, 30.0)
        return "SELL", round(rsi_pts + vol_pts + mom_pts, 1)

    return "NEUTRAL", 0.0


def extract_closes(bars: list[dict]) -> list[float]:
    """Pull close prices from OHLCV bar list (oldest-first). Handles IBKR ('c') and Coinbase ('close') formats."""
    result = []
    for b in bars:
        val = b.get("c") if b.get("c") is not None else b.get("close", 0.0)
        result.append(float(val or 0.0))
    return result


def extract_volumes(bars: list[dict]) -> list[float]:
    """Pull volumes from OHLCV bar list (oldest-first). Handles IBKR ('v') and Coinbase ('volume') formats."""
    result = []
    for b in bars:
        val = b.get("v") if b.get("v") is not None else b.get("volume", 0.0)
        result.append(float(val or 0.0))
    return result
