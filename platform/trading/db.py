"""
Trading system SQLite schema.
All tables use the trading_ prefix.
DB path is per-user in multi-instance deployments: set TRADING_DB_PATH env var.
Ollama base URL: set OLLAMA_BASE_URL env var (default localhost; use host.docker.internal inside Docker).
"""
import os
import sqlite3
from contextlib import contextmanager

DB_PATH     = os.environ.get("TRADING_DB_PATH", "/opt/platform/data/platform.db")
OLLAMA_BASE = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS trading_config (
    key   TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS trading_signals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pool        TEXT NOT NULL,
    ticker      TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    direction   TEXT,
    strength    REAL,
    metadata    TEXT DEFAULT '{}',
    conviction  REAL,
    action      TEXT,
    rationale   TEXT,
    outcome_pnl REAL,
    timestamp   TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_signals_ticker ON trading_signals (ticker);
CREATE INDEX IF NOT EXISTS idx_signals_ts     ON trading_signals (timestamp);

CREATE TABLE IF NOT EXISTS trading_positions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    pool            TEXT NOT NULL,
    ticker          TEXT NOT NULL,
    direction       TEXT NOT NULL DEFAULT 'LONG',
    status          TEXT NOT NULL DEFAULT 'open',
    quantity        REAL NOT NULL,
    entry_price     REAL NOT NULL,
    exit_price      REAL,
    cost_basis      REAL NOT NULL,
    current_price   REAL,
    unrealised_pnl  REAL,
    realised_pnl    REAL,
    trailing_stop   REAL,
    signal_id       INTEGER REFERENCES trading_signals(id),
    opened_at       TEXT DEFAULT (datetime('now')),
    closed_at       TEXT
);
CREATE INDEX IF NOT EXISTS idx_positions_status ON trading_positions (status);
CREATE INDEX IF NOT EXISTS idx_positions_ticker ON trading_positions (ticker);

CREATE TABLE IF NOT EXISTS trading_orders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    pool            TEXT NOT NULL,
    ticker          TEXT NOT NULL,
    direction       TEXT NOT NULL,
    order_type      TEXT NOT NULL DEFAULT 'market',
    quantity        REAL NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    broker_order_id TEXT,
    fill_price      REAL,
    fill_quantity   REAL,
    position_id     INTEGER REFERENCES trading_positions(id),
    signal_id       INTEGER REFERENCES trading_signals(id),
    submitted_at    TEXT DEFAULT (datetime('now')),
    filled_at       TEXT
);
CREATE INDEX IF NOT EXISTS idx_orders_status ON trading_orders (status);

CREATE TABLE IF NOT EXISTS trading_wsb_posts (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    reddit_id         TEXT UNIQUE,
    title             TEXT,
    author            TEXT,
    flair             TEXT,
    score             INTEGER,
    ticker            TEXT,
    thesis_summary    TEXT,
    quality_score     REAL,
    catalyst_verified INTEGER DEFAULT 0,
    source_url        TEXT,
    created_utc       INTEGER,
    processed_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_wsb_posts_ticker ON trading_wsb_posts (ticker);

CREATE TABLE IF NOT EXISTS trading_wsb_mentions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker       TEXT NOT NULL,
    mention_count INTEGER NOT NULL,
    velocity     REAL,
    baseline     REAL,
    spike_factor REAL,
    window_start TEXT NOT NULL,
    window_end   TEXT NOT NULL,
    recorded_at  TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_wsb_mentions_ticker ON trading_wsb_mentions (ticker);

CREATE TABLE IF NOT EXISTS trading_catalysts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker         TEXT NOT NULL,
    catalyst_type  TEXT NOT NULL,
    description    TEXT,
    event_date     TEXT NOT NULL,
    temporal_state TEXT NOT NULL DEFAULT 'upcoming',
    outcome_notes  TEXT,
    source         TEXT,
    created_at     TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_catalysts_ticker ON trading_catalysts (ticker);
CREATE INDEX IF NOT EXISTS idx_catalysts_date   ON trading_catalysts (event_date);

CREATE TABLE IF NOT EXISTS trading_shadow_portfolio (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    pool                 TEXT NOT NULL,
    ticker               TEXT NOT NULL,
    reason_not_taken     TEXT NOT NULL,
    rule_violated        TEXT,
    signal_id            INTEGER REFERENCES trading_signals(id),
    simulated_entry_price REAL,
    simulated_exit_price  REAL,
    simulated_pnl         REAL,
    opened_at            TEXT DEFAULT (datetime('now')),
    closed_at            TEXT
);

CREATE TABLE IF NOT EXISTS trading_learning_weights (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    weight_key     TEXT UNIQUE NOT NULL,
    weight_value   REAL NOT NULL,
    previous_value REAL,
    updated_at     TEXT DEFAULT (datetime('now')),
    rationale      TEXT
);

CREATE TABLE IF NOT EXISTS trading_audit_log (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_type            TEXT NOT NULL,
    findings              TEXT DEFAULT '{}',
    positions_checked     INTEGER,
    violations_found      INTEGER DEFAULT 0,
    force_exits_executed  INTEGER DEFAULT 0,
    ran_at                TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS trading_risk_gate_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    pool          TEXT NOT NULL,
    ticker        TEXT NOT NULL,
    signal_id     INTEGER REFERENCES trading_signals(id),
    decision      TEXT NOT NULL,
    rule_violated TEXT,
    rule_details  TEXT DEFAULT '{}',
    evaluated_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS trading_morning_briefs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    brief_date   TEXT NOT NULL UNIQUE,
    content      TEXT NOT NULL,
    generated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS trading_universe (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    pool     TEXT NOT NULL,
    ticker   TEXT NOT NULL,
    active   INTEGER NOT NULL DEFAULT 1,
    added_at TEXT DEFAULT (datetime('now')),
    UNIQUE (pool, ticker)
);
CREATE INDEX IF NOT EXISTS idx_universe_pool ON trading_universe (pool, active);

CREATE UNIQUE INDEX IF NOT EXISTS idx_catalysts_dedup
    ON trading_catalysts (ticker, event_date, catalyst_type);

CREATE TABLE IF NOT EXISTS trading_push_subscriptions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint   TEXT UNIQUE NOT NULL,
    p256dh     TEXT NOT NULL,
    auth       TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);
"""

_DEFAULT_CONFIG = {
    # pool limits
    "stocks_pool_ceiling": "5000",
    "crypto_pool_ceiling": "2000",
    # risk gate parameters
    "max_position_pct": "20",
    "max_sector_pct": "40",
    "daily_loss_limit_pct": "5",
    "weekly_drawdown_pct": "15",
    "conviction_threshold": "70",
    "trailing_stop_pct": "5",
    # operation mode
    "trading_mode": "paper",
    # catalyst calendar
    "alphavantage_api_key": "",
    "pre_catalyst_days": "5",
    "post_catalyst_days": "3",
    # learning engine
    "learning_rate": "0.05",
    "learning_min_samples": "3",
    "learning_lookback_days": "30",
    "learning_max_change": "0.1",
    # credentials (must be filled before trading starts)
    "ibkr_account_id": "",
    "coinbase_api_key_name": "",
    "coinbase_api_private_key": "",
    "reddit_client_id": "",
    "reddit_client_secret": "",
    "reddit_user_agent": "platform-trading/1.0",
    # manual validation confirmations (set to "true" when confirmed)
    "validation_ibkr_reconnect_ok": "",
    "validation_logs_reviewed": "",
    "validation_outcome_reviewed": "",
}

_DEFAULT_WEIGHTS = {
    "momentum_weight": 1.0,
    "wsb_dd_weight": 0.8,
    "wsb_mentions_weight": 0.4,
    "wsb_correlation_weight": 1.1,
    "pre_catalyst_modifier": 0.5,
    "post_catalyst_positive_modifier": 1.3,
}


def init_db():
    with _open() as conn:
        conn.executescript(_SCHEMA)
    _seed_defaults()


def _seed_defaults():
    with _open() as conn:
        for k, v in _DEFAULT_CONFIG.items():
            conn.execute(
                "INSERT OR IGNORE INTO trading_config (key, value) VALUES (?, ?)", (k, v)
            )
        for k, v in _DEFAULT_WEIGHTS.items():
            conn.execute(
                "INSERT OR IGNORE INTO trading_learning_weights (weight_key, weight_value) VALUES (?, ?)",
                (k, v),
            )


@contextmanager
def _open():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_db():
    """FastAPI dependency — yields a committed-on-success connection."""
    with _open() as conn:
        yield conn


def get_config(conn, key: str) -> str | None:
    row = conn.execute(
        "SELECT value FROM trading_config WHERE key = ?", (key,)
    ).fetchone()
    return row["value"] if row else None


def set_config(conn, key: str, value: str):
    conn.execute(
        "INSERT OR REPLACE INTO trading_config (key, value, updated_at) VALUES (?, ?, datetime('now'))",
        (key, value),
    )
