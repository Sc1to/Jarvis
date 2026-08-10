# CLAUDE.md
# This file is read automatically by Claude Code at the start of every session.
# Do not modify this file without updating BUILD_STATUS to reflect current reality.

---

## WHAT THIS PROJECT IS

A locally-run personal AI platform hosted on a Minisforum MS-S1 Max mini PC.
The platform serves multiple independent AI-powered web applications through a single
reverse proxy, accessible remotely from any device via Tailscale.

The flagship application is an autonomous multi-agent development system (autocoder)
capable of overnight unsupervised runs — the user defines intent, agents design,
build, test, and refactor code autonomously.

This is a solo project. There is one developer. Clarity and maintainability matter
more than cleverness.

---

## READ THESE FIRST — ALWAYS

Before writing any code, creating any file, or running any command, read these documents
in this order. They are the authoritative source of truth for this project.

1. `/docs/ARCHITECTURE.md` — system design, agent definitions, flows, memory layers
2. `/docs/STACK.md` — tech stack, exact versions, install commands, port map, directory structure
3. `/docs/BUILD_SEQUENCE.md` — what to build, in what order, with prompts per component
4. `/docs/SETUP.md` — Ubuntu setup manual (reference only — do not modify without reason)
5. `/docs/TRADING_ARCHITECTURE.md` — trading system design, pools, agents, rules
6. `/docs/IBKR_SETUP.md` — broker connection and IBKR gateway setup
7. `/docs/PHASE_DEV_TOOLING.md` — local testing, deployment, and validation

If anything in a task prompt contradicts these documents, flag the contradiction
and ask before proceeding. Do not resolve contradictions silently.

---

## BUILD STATUS

Update this section at the start of each session to reflect current reality.

```
Current phase:     Phase 13 — Trading System
Last completed:    Phase 13.19 — Paper trading validation tooling; Phase DEV — Docker, deploy scripts, test suite
Currently working: Phase 13.20 — Live trading activation (manual user decision)
Blocked on:        Infra phases (1, 2) are hardware setup; 3-6 months paper trading runtime
Remaining:         Phase 13.20 (manual user decision)
```

**Completed components:**
- [ ] Phase 1  — Foundation (mini PC setup)
- [ ] Phase 2  — Ollama & Model Backend
- [x] Phase 3  — Platform Validation (Chat app)
- [x] Phase 4  — Tool Library
- [x] Phase 5  — Admin Panel
- [x] Phase 6  — Personal Coding Assistant
- [x] Phase 7  — Memory Infrastructure
- [x] Phase 8  — Autocoder Foundation
- [x] Phase 9  — Autocoder Specialist Agents
- [x] Phase 10 — Writer App
- [x] Phase 11 — Hardening
- [x] Phase 12 — Documentation
- [x] Phase DEV — Dev tooling (Docker, deployment scripts, test suite)
- [ ] Phase 13  — Trading system (13.1–13.19 complete; 13.20 is manual user decision)

---

## HARD RULES

These rules are non-negotiable. Follow them on every task without being reminded.

**Python:**
- Always use virtual environments — never `pip install` without an active venv
- Every service has its own `venv/` inside its directory
- Every service has a `requirements.txt` — keep it updated
- Python version: 3.12

**Services:**
- Every backend service runs via `uvicorn` on a dedicated port
- Every service gets a systemd unit file — see STACK.md for the template
- Every service must have a `GET /health` endpoint returning `{status, version, uptime_seconds}`
- Ports are assigned in STACK.md — check the port map before assigning a new one
- New app ports start at 8100 — never reuse or assume a port

**Frontend:**
- React 18 with Vite
- All UIs must be mobile-responsive — minimum tested width 390px
- Use Tailwind for styling
- Build output always goes to `dist/`

**Caddy:**
- Never edit the Caddyfile manually for app registration — always go through the admin panel logic
- Caddy reload command: `sudo systemctl reload caddy`

**Git:**
- The Conductor controls Git inside autocoder sessions — no other service commits
- Outside of autocoder sessions, commits are made normally by the developer
- Commit messages are clear and descriptive — never "fix" or "update"

**Security:**
- Agent internet access always goes through the Playwright web tool — never direct httpx or requests calls from agents
- Filesystem and terminal tools always enforce path restrictions — no exceptions
- GitHub tokens and API keys always stored in SQLite config table — never hardcoded, never in env files committed to git

**Docker:**
- Docker is used for infrastructure services only (Open WebUI, per-user trading conductors)
- Custom platform services (admin, autocoder, trading core, etc.) run as systemd units — not Docker
- Per-user trading conductor containers use env vars for isolation: `TRADING_DB_PATH`, `TRADING_AUDITOR_URL`, `OLLAMA_BASE_URL`, `IBKR_CLIENT_ID`

**Database:**
- Default SQLite path: `/opt/platform/data/platform.db`
- Trading per-user path: set via `TRADING_DB_PATH` env var on each container
- ChromaDB is always at `http://localhost:8020`
- Ollama is always at `http://localhost:11434`

**Testing:**
- Every tool in the tool library must have unit tests
- Every service must have at minimum a health check integration test
- Tests live in a `tests/` directory inside each service directory

**Documentation:**
- When a component is completed, update BUILD_STATUS in this file
- When a component changes significantly, update the relevant section in ARCHITECTURE.md or STACK.md

---

## PROJECT STRUCTURE

```
/
├── CLAUDE.md                   ← this file
├── docs/
│   ├── ARCHITECTURE.md
│   ├── STACK.md
│   ├── BUILD_SEQUENCE.md
│   └── SETUP.md
├── scripts/
│   ├── setup.sh                ← full platform setup script
│   ├── validate-platform.py    ← health check for all services
│   ├── install-ollama.sh
│   ├── download-models.sh
│   └── test-ollama.py
├── platform/                   ← all backend services (deployed to /opt/platform/ on mini PC)
│   ├── admin/
│   ├── autocoder/
│   │   ├── conductor/
│   │   ├── re-agent/
│   │   └── specialists/
│   │       ├── backend/
│   │       ├── frontend/
│   │       ├── db/
│   │       ├── tester/
│   │       └── refactorer/
│   ├── chat/
│   ├── writer/
│   ├── coding/
│   ├── memory/                 ← shared memory package
│   └── tools/                  ← shared tool library
├── frontend/                   ← all React apps
│   ├── admin/
│   ├── autocoder/
│   ├── chat/
│   ├── writer/
│   └── coding/
└── systemd/                    ← all systemd unit files
    ├── platform-admin.service
    ├── platform-chat.service
    └── ...
```

**Deployment path on mini PC:** `/opt/platform/`
**Data path on mini PC:** `/opt/platform/data/`
**Projects path on mini PC:** `/opt/platform/data/projects/`

---

## CONVENTIONS

**Naming:**
- Services: `platform-<name>` (systemd), `<name>/` (directory)
- Python files: `snake_case`
- React files: `PascalCase` for components, `camelCase` for utilities
- Database tables: `snake_case`
- API routes: `kebab-case`

**Error handling:**
- All FastAPI endpoints wrapped in try/except — no raw 500s
- All tool operations return `ToolResult` — never raise exceptions to callers
- All Ollama calls handle: model not found, service offline, timeout

**Logging:**
- Services log to stdout — systemd captures this via journalctl
- Use Python's built-in `logging` module — not print statements
- Log level: INFO for normal operations, ERROR for failures, DEBUG only in development

**API responses:**
- Success: `{data: ..., status: "ok"}`
- Error: `{error: string, status: "error", detail: string}`
- Health: `{status: "ok"|"degraded"|"down", version: string, uptime_seconds: int}`

---

## AGENT NAMING CONVENTION

All agents follow: `{domain}_{role}_{variant}`

**Domain values:**
- `autocoder`  — multi-agent development system agents
- `trading`    — trading system agents
- `platform`   — general apps (chat, writer, coding assistant)
- `custom`     — user-created agents via agent creator

**Examples:**
```
autocoder_conductor
autocoder_re_agent
autocoder_specialist_backend
autocoder_specialist_frontend
autocoder_specialist_db
autocoder_specialist_tester
autocoder_specialist_refactorer
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
```

**Enforced in:**
- Admin panel agent view — grouped and labelled by domain prefix
- Systemd service names: `platform-{domain}-{role}-{variant}`
- SQLite agents table: `name` column follows this convention
- All log entries: `agent_name` field follows this convention

---

## DOMAIN SEPARATION

Agents in different domains cannot share tools, memory, or context.
This is enforced architecturally, not just by convention.

- `autocoder` agents: no access to trading tools, trading memory, or trading APIs
- `trading` agents: no access to autocoder tools, project memory, or autocoder APIs
- `platform` agents: independent of both autocoder and trading
- Cross-domain API calls between agents do not exist by design

**Admin panel agent view:**
- Agents grouped by domain with collapsible sections
- Each domain section shows: agent name, model, status, tools assigned
- Custom agents appear in their own section

---

## DEVELOPMENT WORKFLOW

Code is written on a separate development machine and deployed to the mini PC.

```
Dev machine → GitHub → SSH to mini PC → git pull → systemctl restart
```

When working on a component:
1. Write and test locally where possible
2. Commit to GitHub with a clear message
3. SSH to mini PC: `ssh jarvis@ms-s1`
4. Pull and restart: `git pull && sudo systemctl restart platform-<name>`
5. Verify via admin panel or validate script

**Local testing:**
- Python services can be run locally for development
- Ollama can be installed locally on the dev machine for model testing
- Use `uvicorn main:app --reload` for development (auto-reloads on file changes)

---

## THINGS THAT DO NOT EXIST YET

Do not reference or import these until they are built:
- Memory service (Phase 7)
- Tool library (Phase 4)
- Admin panel (Phase 5)
- Any autocoder agent (Phase 8-9)

If a component you are building depends on something not yet built,
create a stub or mock and note it clearly with a `# TODO: replace with real implementation`
comment and a reference to the phase that will provide it.

---

## DOCUMENTATION MAINTENANCE

Run `docs/MAINTENANCE_PROMPT.md` at the end of every Claude Code session.
This is mandatory, not optional.
The routine updates BUILD_STATUS, merges new information into the correct
documents, resolves contradictions, and produces a maintenance report.
Never close a session without running it.

---

## CONTEXT FOR THE AUTOCODER DESIGN

The autocoder is the most complex part of this project. Keep these principles in mind:

**The user's core need:**
Define intent once via conversation → agents work overnight → review results in the morning.
One human interaction before, one after. Nothing in between.

**The Conductor's role:**
Orchestrate, review, classify failures, commit. It does not write code.

**Failure classification drives everything:**
There is no hardcoded retry limit. The Conductor classifies why something failed
and decides the appropriate response. This is intentional — see ARCHITECTURE.md.

**The RE-agent is the quality gate:**
If requirements are unclear, the pipeline does not start. Period.
Ambiguity at the Conductor level means the RE-agent failed — this should not happen.

**Specialist agents are effective, the Conductor is efficient:**
Specialists own the quality of their output.
The Conductor owns the quality of the overall plan and the sequencing.
