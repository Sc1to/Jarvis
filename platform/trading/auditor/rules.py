"""
Compliance rule checks — pure functions, no I/O.
Each returns True if a VIOLATION is found.
The auditor calls these and decides what action to take.
"""
from datetime import datetime, timedelta


def pool_ceiling_breach(total_cost_basis: float, ceiling: float) -> bool:
    """Deployed capital exceeds pool ceiling."""
    return total_cost_basis > ceiling


def position_size_breach(cost_basis: float, ceiling: float, max_position_pct: float) -> bool:
    """Single position exceeds max_position_pct% of ceiling at entry."""
    return cost_basis > ceiling * max_position_pct / 100


def daily_loss_breach(daily_loss_pct: float, limit_pct: float) -> bool:
    """Today's realised + unrealised loss as % of pool exceeds limit."""
    return daily_loss_pct >= limit_pct


def weekly_drawdown_breach(drawdown_pct: float, limit_pct: float) -> bool:
    """This week's loss as % of pool exceeds limit."""
    return drawdown_pct >= limit_pct


def data_is_stale(last_updated_iso: str | None, max_age_minutes: int = 60) -> bool:
    """Position price data hasn't been refreshed within max_age_minutes."""
    if last_updated_iso is None:
        return True
    try:
        last = datetime.fromisoformat(last_updated_iso)
        return datetime.utcnow() - last > timedelta(minutes=max_age_minutes)
    except (ValueError, TypeError):
        return True


def order_is_orphaned(submitted_at_iso: str | None, max_age_minutes: int = 30) -> bool:
    """Pending order has been sitting unfilled longer than max_age_minutes."""
    if submitted_at_iso is None:
        return False
    try:
        submitted = datetime.fromisoformat(submitted_at_iso)
        return datetime.utcnow() - submitted > timedelta(minutes=max_age_minutes)
    except (ValueError, TypeError):
        return False


def pool_loss_pct(total_pnl: float, ceiling: float) -> float:
    """Convert pool P&L to a positive loss percentage (0 if profitable)."""
    if ceiling <= 0 or total_pnl >= 0:
        return 0.0
    return abs(total_pnl) / ceiling * 100
