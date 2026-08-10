# TRADING_ARCHITECTURE.md
# Personal AI Platform — Trading System Architecture
# Full specification for the autonomous two-pool trading system (Phase 13).
# Read ARCHITECTURE.md first for platform context.

---

## OVERVIEW

An autonomous trading system running on the platform mini PC.
Two independent pools — stocks and crypto — each governed by its own agent pipeline.
Signals come from momentum analysis, WSB sentiment, and fundamental catalysts.
All trades pass through a hard-coded risk gate before execution.
A learning engine tracks outcomes and tunes signal weights over time.
Paper trading for minimum 3-6 months before any live activation.
Live activation is a manual, deliberate decision by the user — never automatic.

---

## DESIGN PRINCIPLES

- **Autonomous by default, human for exceptions.** The system runs overnight with no supervision.
  Alerts go out for unusual situations. Morning brief covers everything else.
- **Risk gate is sacred.** It is hard-coded, never touched by AI agents, and reviewed by the user
  before every live switch. It is the last line of defense.
- **Compliance auditor is independent.** It runs as a separate service with no dependency on other
  trading agents. It can force-exit positions without asking anything else.
- **Paper trading is not optional.** 3-6 months minimum. No exceptions.
- **Pool ceilings are configuration, not guardrails.** The user sets them. The system enforces them.
  The compliance auditor checks them independently.

---

## POOL STRUCTURE

### Stock Pool
- Universe: S&P 500 + NASDAQ 100
- Broker: IBKR TWS via ib_insync (paper: port 7497, live: port 7496)
- Signal sources: momentum, WSB DD posts, catalyst calendar, SEC filings
- Maximum positions: configurable (default 10)
- Pool ceiling: configurable dollar amount

### Crypto Pool
- Universe: Top 20 by market cap (Bitcoin, Ethereum, etc.)
- Exchange: Coinbase Advanced Trade API
- Signal sources: momentum, WSB mentions, sentiment velocity
- Maximum positions: configurable (default 5)
- Pool ceiling: configurable dollar amount

Pools are independent. An agent in the stock pipeline cannot access crypto pool state and vice versa.

---

## SIGNAL PIPELINE

Each pool follows the same pipeline pattern:

```
Market data (continuous)
    → trading_monitor_{stocks|crypto}
        monitors price, volume, momentum
        emits raw signals

WSB data (scheduled)
    → trading_wsb_dd          (DD-flair posts)
    → trading_wsb_mentions    (general mention velocity)
        emits sentiment signals

Catalyst calendar (daily check)
    → temporal state manager
        flags upcoming catalysts, earnings dates

Signal convergence
    → trading_validator_signal
        scores conviction (0-100)
        factors: momentum strength, WSB confirmation, catalyst alignment
        temporal state: pre-catalyst / post-catalyst / neutral
        output: BUY | WATCH | SKIP + conviction score

Risk evaluation
    → trading_validator_risk_gate
        hard-coded compliance checks (see RISK GATE section)
        PASS or BLOCK — no middle ground

Order execution (if PASS)
    → trading_execution_{stocks|crypto}
        places order via broker API
        confirms fill
        logs to position manager

Position management (continuous)
    → trading_position_manager
        monitors open positions
        manages trailing stops
        logs cost basis and P&L

Compliance audit (every 2 hours + on every trade)
    → trading_auditor_compliance
        independent check of all open positions
        force-exits any position violating rules

Learning (daily)
    → trading_learning_engine
        runs shadow portfolio analysis
        updates signal weights based on outcomes
```

---

## AGENT DEFINITIONS

### trading_monitor_stocks
- **Port:** runs within trading service (not a separate HTTP service)
- **Model:** None — uses deterministic momentum calculations, not LLM
- **Schedule:** Continuous during market hours (via APScheduler)
- **Responsibility:** Watch S&P 500 + NASDAQ 100 price and volume data.
  Calculate momentum indicators. Emit raw signals when conditions are met.
- **Tools:** httpx (market data API), SQLite (signal log)
- **Output:** Raw signal: {ticker, direction, strength, timestamp, indicators}

### trading_monitor_crypto
- **Port:** runs within trading service
- **Model:** None — deterministic
- **Schedule:** Continuous (crypto markets never close)
- **Responsibility:** Watch top 20 crypto by market cap. Same momentum logic as stocks.
- **Tools:** httpx (exchange API), SQLite
- **Output:** Same structure as stocks monitor

### trading_wsb_dd
- **Port:** runs within trading service
- **Model:** 32B+ for thesis extraction, verification, and quality scoring — trading DD analysis requires stronger reasoning than conversational tasks
- **Schedule:** Every 30 minutes during market hours, hourly overnight
- **Responsibility:** Monitor r/wallstreetbets for posts with DD flair.
  Extract ticker, thesis, timeframe, catalyst. Cross-reference with SEC EDGAR.
  Score thesis quality. Emit confirmed DD signals.
- **Tools:** praw (Reddit), httpx (SEC EDGAR), SQLite
- **Output:** DD signal: {ticker, thesis_summary, quality_score, catalyst_verified, source_url}

### trading_wsb_mentions
- **Port:** runs within trading service
- **Model:** None — text matching + velocity calculation
- **Schedule:** Every 30 minutes during market hours, hourly overnight
- **Responsibility:** Track how often each ticker appears in WSB regardless of post type.
  Calculate mention velocity (rate of change, not absolute count).
  Unusual velocity spikes are signals.
- **Tools:** praw, SQLite
- **Output:** Mention signal: {ticker, velocity, baseline, spike_factor, timestamp}

### trading_validator_signal
- **Port:** runs within trading service
- **Model:** 32B (reasoning) — conviction scoring requires reliable multi-factor analysis
- **Schedule:** Triggered by incoming signals from monitors and WSB agents
- **Responsibility:** Combine all available signal types into a conviction score.
  Apply temporal state (pre-earnings? recent catalyst? post-news?).
  Output: BUY recommendation with conviction score, or SKIP.
  Conviction threshold for order generation: configurable (default 70/100).
- **Tools:** SQLite (signals, catalyst calendar)
- **Output:** {ticker, action: BUY|SKIP, conviction: 0-100, rationale: string}

### trading_validator_risk_gate
- **Port:** runs within trading service
- **Model:** None — deterministic rule engine
- **Responsibility:** Hard-coded pre-order compliance checks. No LLM involvement.
  This code is never modified by AI agents. User reviews before live switch.
  Returns PASS or BLOCK with specific rule violated.
- **Rules:** See RISK GATE section below
- **Output:** {decision: PASS|BLOCK, rule_violated: string|null}

### trading_execution_stocks
- **Port:** runs within trading service
- **Model:** None — deterministic order construction
- **Responsibility:** Place and manage stock orders via IBKR TWS.
  Construct order from signal (size based on pool allocation + conviction score).
  Submit order. Confirm fill. Register with position manager. Log everything.
- **Tools:** ib_insync (TWS port 7497 paper / 7496 live)
- **Output:** {order_id, ticker, direction, size, fill_price, status}

### trading_execution_crypto
- **Port:** runs within trading service
- **Model:** None — deterministic
- **Responsibility:** Same as stocks but via Coinbase Advanced Trade API.
- **Tools:** httpx (Coinbase API)
- **Output:** Same structure as stocks execution

### trading_position_manager
- **Port:** runs within trading service
- **Model:** None — deterministic
- **Schedule:** Every 15 minutes (trailing stop checks), real-time on fill events
- **Responsibility:** Track all open positions. Manage trailing stops.
  Update cost basis and unrealized P&L. Trigger exit orders when stops hit.
- **Tools:** httpx (broker APIs), SQLite
- **Output:** Position updates to SQLite; exit orders to execution agents

### trading_auditor_compliance
- **Port:** runs as separate FastAPI service
- **Model:** None — deterministic rule engine
- **Schedule:** Every 2 hours + triggered on every new position open
- **Responsibility:** Independent check of all open positions against risk rules.
  No dependency on other trading agents — reads directly from SQLite and broker APIs.
  Can force-exit positions by calling execution endpoints directly.
  Reports to admin panel via /internal/event.
- **Important:** This service is the last defense against rule violations.
  It must remain independent. Never integrate it into the main trading pipeline.
- **Tools:** httpx (broker APIs), SQLite, admin /internal/event endpoint

### trading_learning_engine
- **Port:** runs within trading service
- **Model:** 14B (analysis)
- **Schedule:** Daily at 05:00
- **Responsibility:** Maintain a shadow portfolio (simulated trades not taken).
  Run retrospective analysis on completed trades and shadow trades.
  Identify which signal combinations predicted good outcomes.
  Tune signal weights in SQLite — not code, not rules.
  Generate weekly performance report.
- **Tools:** SQLite (historical signals, outcomes, shadow portfolio)
- **Output:** Updated signal weights in SQLite + performance report

---

## RISK GATE

The risk gate is a list of hard-coded rules evaluated before every order.
It is not an LLM. It is a deterministic function that returns PASS or BLOCK.
This code lives in `platform/trading/risk_gate.py` and is never modified by AI.

**Current rules (exhaustive list):**

```
1. POOL_CEILING
   Pool value (open positions + cash allocated) must not exceed configured ceiling.

2. POSITION_SIZE_MAX
   No single position may exceed {max_position_pct}% of pool ceiling.
   Default: 20% (max 5 positions at full size)

3. PORTFOLIO_CONCENTRATION
   No single sector may exceed {max_sector_pct}% of stock pool.
   Default: 40%

4. DAILY_LOSS_LIMIT
   If today's realised + unrealised loss exceeds {daily_loss_limit_pct}%
   of pool value: block all new orders for the rest of the trading day.
   Default: 5%

5. WEEKLY_DRAWDOWN_LIMIT
   If this week's P&L is down more than {weekly_drawdown_pct}%:
   block all new orders until next Monday.
   Default: 15%

6. BROKER_AUTH_REQUIRED
   If broker session is not authenticated: block all orders.

7. IBKR_SESSION_CHECK (stocks only)
   If IBKR TWS is not connected: block all stock orders.

8. MARKET_HOURS_CHECK (stocks only)
   Stock orders only during regular market hours (09:30–16:00 EST, weekdays).
   Pre/post market orders blocked by default.

9. PENNY_STOCK_BLOCK
   Block any order for a stock with price below $5.

10. CONVICTION_MINIMUM
    Block orders with conviction score below threshold.
    Default: 70/100

11. DUPLICATE_POSITION
    Block order if position already open in that ticker.

12. EXISTING_ORDER
    Block order if unfilled order already exists for that ticker.
```

Rules are parameterised by config values stored in SQLite. Only the user
can change these values — not the trading agents.

---

## TEMPORAL STATE MANAGEMENT

Signals have different meanings at different times relative to catalysts.

**States:**
- `pre_catalyst`: Within N days before a known catalyst (earnings, FDA approval, product launch).
  Signals in this state carry elevated risk — wait for the event to resolve.
  Default behaviour: WATCH only, no new positions.

- `post_catalyst`: Within M days after a catalyst event.
  If the catalyst was positive and price is still moving: elevated conviction.
  If the catalyst was negative: block new positions.

- `neutral`: No known catalyst within window. Normal signal evaluation.

**Catalyst sources:**
- Earnings dates: from IBKR or financial data API
- FDA/regulatory: from catalyst calendar API (TBD in 13.9)
- Product launches: from WSB DD agent (extracted from posts)
- Macro events (FOMC, CPI): loaded manually into calendar

---

## LEARNING ENGINE DESIGN

The learning engine tunes signal weights, not code.

**What is tuned:**
- Weight of each signal type in conviction scoring
- Velocity thresholds for WSB mention spikes
- Catalyst alignment bonuses
- Temporal state modifiers

**What is not tuned:**
- Risk gate rules (hard-coded, user-controlled)
- Pool ceilings (user configuration)
- Order sizing formula

**Retrospective analysis:**
For each completed trade: gather all signals that contributed, the conviction score,
the actual outcome (P&L), and the shadow portfolio equivalent (what would have happened
if we had acted differently).
Identify: which signal types most reliably preceded good outcomes.
Update weights proportionally.
Cap weight changes per cycle to prevent overcorrection.

**Shadow portfolio:**
Every signal that meets conviction threshold but is blocked by risk gate or position limits
is tracked in the shadow portfolio as if we had acted on it.
This tells us what we missed and whether our risk rules are costing us.

---

## MORNING BRIEF

Generated daily at 07:00 by the learning engine / morning brief component.

**Contents:**
- Overnight P&L summary (both pools)
- Open positions with current price and unrealised P&L
- Any orders executed overnight (crypto only — stocks are market hours)
- Signals generated but blocked (risk gate, position limits)
- IBKR authentication status (with re-auth link if needed)
- Compliance audit results from overnight runs
- Pending alerts requiring user attention

**Delivery:** Trading app dashboard (`/trading`) and Web Push notifications (Phase 13.18).
Push alerts fire on: morning brief ready, daily loss breach force exit, weekly drawdown breach force exit.

---

## DATA STORAGE

All trading data in SQLite at `/opt/platform/data/platform.db`.
Separate table prefix `trading_*` to avoid collisions with platform tables.

**Key tables:**

| Table | Purpose |
|---|---|
| trading_config | All trading configuration (pool ceilings, risk params, API credentials) |
| trading_signals | Every signal generated, with source, conviction, outcome |
| trading_positions | All open and closed positions with full history |
| trading_orders | Order log with status, fill details |
| trading_wsb_posts | Processed WSB posts with extracted data |
| trading_wsb_mentions | Ticker mention counts over time |
| trading_catalysts | Known upcoming catalysts and their outcome records |
| trading_shadow_portfolio | Simulated trades not taken |
| trading_learning_weights | Current signal weights tuned by learning engine |
| trading_audit_log | Every compliance audit run and its findings |
| trading_risk_gate_log | Every risk gate evaluation with decision and rule |
| trading_morning_briefs | Historical morning briefs |
| trading_push_subscriptions | Web Push API subscription endpoints (VAPID) |

---

## DEPLOYMENT

The trading system runs as a single FastAPI service (`platform/trading/main.py`) on port 8030.
All agents run as async functions within this service, scheduled by APScheduler.

The compliance auditor runs as a separate service for independence (port 8031).

**Caddy route:** `/trading` → trading frontend static files + API on port 8030.

### Multi-user deployment

Each user gets their own Docker container running the trading service.
Containers share the Ollama backend and ChromaDB, but each has its own SQLite database.
See STACK.md (DOCKER section) for the exact run command and env vars.

---

## PAPER TRADING VALIDATION CRITERIA

The following must all be met before considering live switch.
Check current status at `/trading/validation` in the trading frontend.

**Automated checks (queried live from SQLite):**
- 90+ days of operation with no unhandled exceptions
- 90+ morning briefs generated without failure
- Risk gate triggered on 5+ different scenarios
- Compliance auditor triggered at least once (test breach)
- Learning engine completed 90+ daily cycles (3 months)
- Shadow portfolio has 10+ tracked trades with positive P&L
- Zero audit failures (clean operation)

**Manual confirmations (stored in `trading_config`, confirmed via validation UI):**
- IBC/TWS auto-reconnect verified — survives overnight without manual intervention
- All agent logs reviewed and contain no unexpected errors
- Total paper trading outcome reviewed and understood by the user

**The live switch is a conversation, not a button press.**

---

## KNOWN LIMITATIONS AND DESIGN DECISIONS

**No options trading in initial build.**
Options add complexity (Greeks, expiry, assignment risk) that is not worth it in v1.
The system is stocks and crypto only. Options can be added later.

**No short selling in initial build.**
Long positions only. The risk of unlimited downside on shorts is not appropriate
for an autonomous overnight system without deep risk modelling.

**WSB is a signal, not a strategy.**
WSB mention velocity and DD quality are one input into conviction scoring.
The system does not blindly follow WSB. It uses WSB as a confirmation layer.

**Pool sizes are small by design.**
This is a learning system. Start with amounts you are comfortable losing entirely.
The learning engine's value compounds over time — do not over-allocate early.

**No guaranteed fills.**
Market orders get fills. Limit orders may not. The execution agent uses
market orders for simplicity. This can be refined later.
