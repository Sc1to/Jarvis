"""
Conviction scoring — pure math, no I/O.
All inputs come from the DB; this module is fully testable without one.

Signal weights are loaded from trading_learning_weights by the caller and
passed in as a plain dict. This keeps the math decoupled from persistence.
"""

# Mapping from signal_type in trading_signals to weight key in trading_learning_weights
_WEIGHT_KEYS: dict[str, str] = {
    "momentum":        "momentum_weight",
    "wsb_dd":          "wsb_dd_weight",
    "wsb_mentions":    "wsb_mentions_weight",
    "wsb_correlation": "wsb_correlation_weight",
}

# Default weights used when the DB hasn't been seeded yet
_DEFAULTS: dict[str, float] = {
    "momentum_weight":              1.0,
    "wsb_dd_weight":                0.8,
    "wsb_mentions_weight":          0.4,
    "wsb_correlation_weight":       1.1,
    "pre_catalyst_modifier":        0.5,
    "post_catalyst_positive_modifier": 1.3,
}


def calculate_conviction(
    signal_strengths: dict[str, float],   # {signal_type: max_strength}
    weights: dict[str, float],
) -> float:
    """
    Weighted average of all present signals.

    Only signal types that are actually present (have an entry in signal_strengths)
    contribute to both the numerator and the denominator.  A missing signal type
    is treated as absent data, not as a zero-strength signal — this avoids
    penalising a ticker for lacking a WSB DD post when only momentum fired.

    Returns raw conviction in [0, 100] before temporal modifiers.
    """
    numerator = 0.0
    denominator = 0.0
    for sig_type, strength in signal_strengths.items():
        w_key = _WEIGHT_KEYS.get(sig_type)
        if w_key is None:
            continue
        w = weights.get(w_key, _DEFAULTS.get(w_key, 1.0))
        numerator += w * strength
        denominator += w
    if denominator == 0.0:
        return 0.0
    return round(min(numerator / denominator, 100.0), 2)


def apply_temporal_modifier(
    raw_conviction: float,
    temporal_state: str,
    weights: dict[str, float],
) -> tuple[float, str | None]:
    """
    Apply the temporal state multiplier.

    Returns (modified_conviction, action_override):
      action_override is 'WATCH' for pre_catalyst, 'SKIP' for post_catalyst_negative,
      None otherwise (let determine_action decide normally).
    """
    if temporal_state == "pre_catalyst":
        mod = weights.get("pre_catalyst_modifier", _DEFAULTS["pre_catalyst_modifier"])
        return round(raw_conviction * mod, 2), "WATCH"

    if temporal_state == "post_catalyst_positive":
        mod = weights.get("post_catalyst_positive_modifier", _DEFAULTS["post_catalyst_positive_modifier"])
        return round(min(raw_conviction * mod, 100.0), 2), None

    if temporal_state == "post_catalyst_negative":
        return 0.0, "SKIP"

    # neutral
    return raw_conviction, None


def determine_action(conviction: float, threshold: float) -> str:
    """
    BUY  — conviction >= threshold (default 70)
    WATCH — conviction >= threshold × 0.7
    SKIP  — below both bands
    """
    if conviction >= threshold:
        return "BUY"
    if conviction >= threshold * 0.7:
        return "WATCH"
    return "SKIP"


def score(
    signal_strengths: dict[str, float],
    temporal_state: str,
    weights: dict[str, float],
    threshold: float = 70.0,
) -> tuple[float, str]:
    """
    Full pipeline: weighted average → temporal modifier → action.
    Returns (conviction, action).
    """
    raw = calculate_conviction(signal_strengths, weights)
    conviction, override = apply_temporal_modifier(raw, temporal_state, weights)
    action = override if override else determine_action(conviction, threshold)
    return conviction, action
