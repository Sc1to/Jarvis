"""
APScheduler job definitions for the trading service.
All agents run as async functions within this service, scheduled here.
Job stubs are replaced with real implementations as each Phase 13 component is built.
"""
import logging
import os

from apscheduler import AsyncScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

log = logging.getLogger(__name__)


# ── Job functions (implemented progressively through Phase 13) ────────────────

async def check_trailing_stops():
    """13.13 — trading_position_manager: check and update trailing stops."""
    from position_manager import run as _run
    await _run()


_AUDITOR_URL = os.environ.get("TRADING_AUDITOR_URL", "http://localhost:8031/audit/run")


async def run_compliance_audit():
    """13.14 — Trigger the compliance auditor service (separate process on port 8031)."""
    try:
        async with __import__("httpx").AsyncClient(timeout=30) as client:
            await client.post(_AUDITOR_URL)
    except Exception as exc:
        log.warning("Could not reach compliance auditor: %s", exc)


async def monitor_stocks():
    """13.7 — trading_monitor_stocks: price/volume/momentum tick."""
    from monitors.stocks import run as _run_stocks
    await _run_stocks()


def monitor_crypto():
    """13.7 — trading_monitor_crypto: continuous crypto tick."""
    from monitors.crypto import run as _run_crypto
    _run_crypto()


async def monitor_wsb():
    """13.8 — trading_wsb_dd + trading_wsb_mentions + correlation."""
    from wsb.mention_tracker import run as _mentions
    from wsb.dd_monitor import run as _dd
    from wsb.correlation import run as _correlate

    _mentions()          # sync — fast, no LLM
    await _dd()          # async — calls Ollama + EDGAR
    _correlate()         # sync — SQL only


async def check_catalyst_calendar():
    """13.9 — catalyst calendar: fetch earnings + expire past events."""
    from catalysts.calendar import run as _run_calendar
    await _run_calendar()


async def execute_stocks():
    """13.12 — trading_execution_stocks: place IBKR orders for BUY signals."""
    from execution.stocks import run as _run
    await _run()


async def execute_crypto():
    """13.12 — trading_execution_crypto: place Coinbase orders for BUY signals."""
    from execution.crypto import run as _run
    await _run()


async def validate_signals():
    """13.10 — trading_validator_signal: score conviction for new raw signals."""
    from validator.signal_validator import run as _run_validator
    await _run_validator()


async def run_learning_engine():
    """13.15 — trading_learning_engine: daily retrospective analysis at 05:00."""
    from learning_engine import run as _run
    await _run()


async def generate_morning_brief():
    """13.16 — morning brief generation at 07:00."""
    import asyncio
    from morning_brief import run as _run
    await _run()
    try:
        from notifications import send_push
        await asyncio.to_thread(send_push, "Morning Brief Ready", "Today's trading brief is available.", "/trading/")
    except Exception as exc:
        log.warning("Morning brief push notification failed: %s", exc)


# ── Scheduler setup ───────────────────────────────────────────────────────────

async def register_jobs(scheduler: AsyncScheduler):
    """
    Register all trading jobs. Called from lifespan after the scheduler has started.
    Schedule matches STACK.md APScheduler section.
    """
    # Trailing stop checks — every 15 minutes, all hours, all days
    await scheduler.add_schedule(
        check_trailing_stops, IntervalTrigger(minutes=15), id="trailing_stops"
    )
    # Full compliance audit — every 2 hours
    await scheduler.add_schedule(
        run_compliance_audit, IntervalTrigger(hours=2), id="compliance_audit"
    )
    # Stock monitor — every 5 minutes (position manager filters market hours)
    await scheduler.add_schedule(
        monitor_stocks, IntervalTrigger(minutes=5), id="monitor_stocks"
    )
    # Crypto monitor — every 5 minutes (crypto never closes)
    await scheduler.add_schedule(
        monitor_crypto, IntervalTrigger(minutes=5), id="monitor_crypto"
    )
    # Execution agents — every 5 minutes, pick up BUY conviction signals
    await scheduler.add_schedule(
        execute_stocks, IntervalTrigger(minutes=5), id="execute_stocks"
    )
    await scheduler.add_schedule(
        execute_crypto, IntervalTrigger(minutes=5), id="execute_crypto"
    )
    # WSB monitoring — every 30 minutes
    await scheduler.add_schedule(
        monitor_wsb, IntervalTrigger(minutes=30), id="monitor_wsb"
    )
    # Signal validator — every 10 minutes
    await scheduler.add_schedule(
        validate_signals, IntervalTrigger(minutes=10), id="validate_signals"
    )
    # Catalyst calendar — daily at 06:00
    await scheduler.add_schedule(
        check_catalyst_calendar, CronTrigger(hour=6, minute=0), id="catalyst_calendar"
    )
    # Learning engine — daily at 05:00
    await scheduler.add_schedule(
        run_learning_engine, CronTrigger(hour=5, minute=0), id="learning_engine"
    )
    # Morning brief — daily at 07:00
    await scheduler.add_schedule(
        generate_morning_brief, CronTrigger(hour=7, minute=0), id="morning_brief"
    )
    log.info("All trading jobs scheduled")
