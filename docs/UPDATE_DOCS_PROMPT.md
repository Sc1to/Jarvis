# UPDATE_DOCS_PROMPT.md
# One-time prompt to run now to sync all documentation with current state.
# Run this in Claude Code once. After this, use MAINTENANCE_PROMPT.md going forward.
# This is a longer session — it reads everything and makes many targeted updates.

---

## CONTEXT FOR CLAUDE CODE

We have been designing the system in a separate conversation and several
significant additions have been made that are not yet reflected in the codebase
documentation. This prompt brings everything into sync.

New additions to integrate:
1. Trading system (full architecture)
2. Agent naming convention and domain separation
3. Documentation maintenance routine
4. Dev tooling (Docker, deployment scripts, test suite)

---

## THE PROMPT

```
This is a documentation synchronisation session. We are not building anything.
We are bringing all documentation into sync with a set of design decisions
made outside of Claude Code.

Read every file in the docs/ directory in full before doing anything else.
Also read CLAUDE.md in full.
List every document you have read and confirm you have read them completely
before proceeding.

---

PART 1 — ADD TRADING ARCHITECTURE DOCUMENT

Create docs/TRADING_ARCHITECTURE.md with the following content.
This is a new document — it does not exist yet.

[PASTE THE FULL CONTENTS OF TRADING_ARCHITECTURE.md HERE]

---

PART 2 — ADD IBKR SETUP DOCUMENT

Create docs/IBKR_SETUP.md with the following content.
This is a new document — it does not exist yet.

[PASTE THE FULL CONTENTS OF IBKR_SETUP.md HERE]

---

PART 3 — ADD MAINTENANCE PROMPT DOCUMENT

Create docs/MAINTENANCE_PROMPT.md with the following content.

[PASTE THE FULL CONTENTS OF MAINTENANCE_PROMPT.md HERE]

---

PART 4 — UPDATE CLAUDE.md

Make the following surgical additions to CLAUDE.md.
Do not rewrite sections that already exist unless they directly contradict
what is listed below. Add, do not replace.

4A — Add to the READ THESE FIRST section (additional documents):
  5. docs/TRADING_ARCHITECTURE.md — trading system design, pools, agents, rules
  6. docs/IBKR_SETUP.md — broker connection setup and configuration

4B — Add a new AGENT NAMING CONVENTION section:

  ## AGENT NAMING CONVENTION

  All agents follow this naming pattern without exception:
  {domain}_{role}_{variant}

  Domain values:
    autocoder   — agents that are part of the multi-agent development system
    trading     — agents that are part of the trading system
    platform    — general platform apps (chat, writer, coding assistant)
    custom      — agents created by user via agent creator

  Examples:
    autocoder_conductor
    autocoder_specialist_backend
    autocoder_specialist_frontend
    autocoder_specialist_db
    autocoder_specialist_tester
    autocoder_specialist_refactorer
    autocoder_re_agent
    trading_monitor_stocks
    trading_monitor_crypto
    trading_wsb_dd
    trading_wsb_mentions
    trading_validator_signal
    trading_validator_risk_gate
    trading_execution_stocks
    trading_execution_crypto
    trading_auditor_compliance
    trading_position_manager
    trading_learning_engine
    platform_chat
    platform_writer
    platform_coding

  This convention is enforced in:
  - Admin panel agent grouping (agents grouped by domain prefix)
  - Systemd service names: platform-{domain}-{role}-{variant}
  - Database agent table: name column follows this convention
  - Log entries: agent_name field follows this convention

4C — Add a new DOMAIN SEPARATION section:

  ## DOMAIN SEPARATION

  Agents in different domains cannot share tools, memory, or context.
  This is enforced architecturally, not just by convention.

  - autocoder agents have no access to trading tools or trading memory
  - trading agents have no access to autocoder tools or project memory
  - platform agents are independent of both
  - Cross-domain communication does not exist by design

  The admin panel agent view groups agents by domain with collapsible sections.
  Within each domain, agents are listed by role.
  Custom agents appear in their own section regardless of what they do.

4D — Add a new DOCUMENTATION MAINTENANCE section:

  ## DOCUMENTATION MAINTENANCE

  At the end of every Claude Code session, run the maintenance routine
  in docs/MAINTENANCE_PROMPT.md. This is mandatory, not optional.

  The routine:
  - Updates BUILD_STATUS to reflect session completions
  - Merges new information into correct documents
  - Resolves contradictions across documents
  - Verifies naming convention compliance
  - Produces a maintenance report

  Never close a session without running this routine.

4E — Update BUILD_STATUS to add Phase 13 and dev tooling phases:

  In the completed components checklist, add:
  - [ ] Phase 13 — Trading System
  - [ ] Phase DEV — Dev Tooling (Docker, deployment, test suite)

  Mark whichever phases are already complete based on what you know
  from the current state of the codebase.

---

PART 5 — UPDATE ARCHITECTURE.md

Make the following targeted additions:

5A — Add trading app to the platform applications section:
  /trading    → Trading dashboard, both pools, positions, alerts, settings

5B — Add trading agents to the agent definitions section.
  Add a new subsection TRADING AGENTS after the existing AUTOCODER AGENTS section.
  Keep it brief — full detail is in TRADING_ARCHITECTURE.md.
  Just list: agent name (following naming convention), model, one-line responsibility.

5C — Add domain separation note to the agent section:
  "Agents are grouped by domain. Domain boundaries are enforced architecturally.
  See CLAUDE.md domain separation section and TRADING_ARCHITECTURE.md for full detail."

5D — Add APScheduler to the tech stack table:
  APScheduler | Scheduled job execution for trading system

---

PART 6 — UPDATE STACK.md

Make the following targeted additions:

6A — Add to the PORT MAP:
  platform-trading backend:   8030
  (trading frontend served via Caddy static files, no separate port)

6B — Add new section APSCHEDULER after the existing service entries:

  ## APSCHEDULER

  Version: 4.x latest
  Purpose: Scheduled job execution for trading system

  Install (trading service venv):
  pip install apscheduler

  Runs within the trading FastAPI service — not a separate service.

  Job schedule:
  - Trailing stop check:      every 15 minutes
  - Full compliance audit:    every 2 hours
  - Market open audit:        daily at market open (09:30 EST stocks, continuous crypto)
  - WSB monitoring:           every 30 minutes during market hours, hourly overnight
  - Catalyst calendar check:  daily at 06:00
  - Learning engine:          daily at 05:00
  - Morning brief generation: daily at 07:00

6C — Add to the DIRECTORY STRUCTURE:
  trading/                    # trading system backend service
    ├── venv/
    ├── main.py
    ├── scheduler.py           # APScheduler jobs
    ├── risk_gate.py           # hard-coded risk rules
    ├── compliance_auditor.py  # independent compliance checker
    └── requirements.txt

6D — Add to SYSTEMD SERVICES REGISTRY:
  platform-trading  |  /etc/systemd/system/platform-trading.service

6E — Add new section BROKER AND EXCHANGE TOOLS:

  ## BROKER AND EXCHANGE TOOLS

  ### IBKR Client Portal API
  Authentication: Session token, refreshed automatically
  Base URL: https://localhost:5000/v1/api (Client Portal Gateway runs locally)
  Library: Direct REST via httpx — no third party IBKR library
  Paper trading URL: identical, different account credentials
  See docs/IBKR_SETUP.md for full setup instructions.

  ### Crypto Exchange (Coinbase Advanced Trade)
  Authentication: API key + secret stored in SQLite config table
  Library: Direct REST via httpx
  Sandbox available: yes — use for all development and testing

  ### Reddit API
  Authentication: OAuth2, credentials in SQLite config table
  Library: praw (Python Reddit API Wrapper)
  pip install praw
  Rate limits: 60 requests per minute — scheduler must respect this

  ### Pushshift (Historical Reddit)
  Base URL: https://api.pushshift.io
  Authentication: none required for basic access
  Purpose: Historical WSB data for correlation engine bootstrap
  Library: Direct REST via httpx

  ### SEC EDGAR
  Base URL: https://data.sec.gov/api/xbrl/
  Authentication: none required, include User-Agent header
  Purpose: Verify fundamental catalysts from primary source
  Library: Direct REST via httpx

---

PART 7 — UPDATE BUILD_SEQUENCE.md

Add Phase 13 entry at the end of the document.
Phase 13 follows Phase 12 (Documentation).

Phase 13 — Trading System

Goal: Fully operational two-pool autonomous trading system.
Dependencies: Phase 12 complete. Paper trading account with IBKR active.

List the following components in order with placeholder prompts.
We will write the full Claude Code prompts for Phase 13 in a separate session.
For now, just list them with "PROMPT: TBD — see TRADING_ARCHITECTURE.md for spec":

13.1  Trading data schema — new SQLite tables
13.2  IBKR tool — paper trading account
13.3  Crypto exchange tool — Coinbase sandbox
13.4  Reddit API tool + Pushshift historical tool
13.5  SEC EDGAR tool
13.6  APScheduler integration
13.7  Market Monitor agents (stocks + crypto)
13.8  WSB Monitor + correlation engine
13.9  Catalyst Calendar + temporal state management
13.10 Signal Validator + conviction scoring
13.11 Risk Gate — hard-coded, fully tested
13.12 Execution Engine (stocks + crypto)
13.13 Position Manager + trailing stop management
13.14 Compliance Auditor — independent service
13.15 Learning Engine + shadow portfolio
13.16 Morning brief generation
13.17 Trading app frontend
13.18 Notification system
13.19 Paper trading validation — minimum 4 weeks
13.20 Live trading activation — explicit user decision required

Also add Phase DEV entry before Phase 13:

Phase DEV — Development Tooling
Goal: Local testing, deployment, and validation infrastructure.
Status: Prompts written in docs/PHASE_DEV_TOOLING.md
Components: Docker Compose setup, deployment scripts, test suite.

---

PART 8 — DEDUPLICATION PASS

After completing Parts 1-7, do a final deduplication pass across all documents.

For each piece of information that appears in more than one document, decide:
- Is this appropriate redundancy (same info needed in two places for context)?
  → Keep both, make sure they are identical
- Is this accidental duplication (copy-paste drift)?
  → Keep the authoritative location, remove from the other, add a cross-reference

Appropriate redundancy examples:
  Port numbers in both STACK.md port map and ARCHITECTURE.md service list — keep both
  Tech stack in both STACK.md and ARCHITECTURE.md — keep both, they serve different purposes

Accidental duplication examples:
  Agent descriptions written in full in both ARCHITECTURE.md and TRADING_ARCHITECTURE.md
  → Full description in the domain-specific document, one-line summary in ARCHITECTURE.md

---

PART 9 — PRODUCE SYNC REPORT

After completing all parts, produce a full sync report:

DOCUMENTATION SYNC REPORT — {date}

New documents created:
  {list}

Documents updated:
  CLAUDE.md — {list of sections added or changed}
  ARCHITECTURE.md — {list of changes}
  STACK.md — {list of changes}
  BUILD_SEQUENCE.md — {list of changes}

Contradictions found and resolved:
  {list or "none"}

Naming convention violations found:
  {list or "none"}

Duplicates resolved:
  {list or "none"}

Documents verified current and unchanged:
  {list}

Ready for next session:
  Phase {X} — {component}
```

---

## AFTER RUNNING THIS PROMPT

1. Review the sync report Claude Code produces
2. If anything looks wrong, correct it before the next build session
3. From this point forward use MAINTENANCE_PROMPT.md at the end of every session
4. The UPDATE_DOCS_PROMPT.md is a one-time document — archive it after use
