# ARCHITECTURE.md
# Personal AI Platform — System Architecture v0.2
# Reference document for Claude Code. Read this before working on any component.

---

## OVERVIEW

A locally-run personal AI platform hosted on a Minisforum MS-S1 Max mini PC. The platform serves multiple independent AI-powered web applications through a single reverse proxy, accessible remotely from any device via Tailscale. The flagship application is an autonomous multi-agent development system (autocoder) capable of overnight unsupervised runs.

---

## HARDWARE

- **Device:** Minisforum MS-S1 Max
- **CPU/APU:** AMD Ryzen AI Max+ 395 (Strix Halo, 16x Zen 5 cores)
- **GPU:** Integrated RDNA 3.5, 40 Compute Units
- **Memory:** Up to 128GB LPDDR5x-8000 unified (shared CPU/GPU)
- **Network:** Dual 10GbE, WiFi 7
- **Expansion:** PCIe x16, 2U rack support

**Critical BIOS settings:**
- Maximize GPU memory allocation (unified memory split — as much as possible to iGPU)
- Enable auto power-on after power loss
- Disable sleep and hibernate
- Configure fan curve for sustained workloads

---

## OPERATING SYSTEM

- **OS:** Ubuntu 24.04 LTS
- **Update policy:** Automatic security patches via unattended-upgrades. Major updates triggered manually through admin panel. Updates blocked during active autocoder sessions.

---

## TECH STACK

| Layer | Technology | Purpose |
|---|---|---|
| OS | Ubuntu 24.04 LTS | Base operating system |
| Remote access | Tailscale | Secure remote access from any device |
| Reverse proxy | Caddy | Routing, HTTPS, URL management |
| Model backend | Ollama | Local LLM serving, model management |
| Chat interface | Open WebUI | Primary chat UI (Docker, port 3000) |
| Agent orchestration | Custom (FastAPI) | Platform services; LangGraph for autocoder only |
| Containers | Docker | Infrastructure services + per-user trading isolation |
| Backend | Python + FastAPI | All custom service backends |
| Frontend | React | All custom web UIs, mobile-responsive |
| Vector DB | ChromaDB | Cross-run memory, semantic search |
| Structured storage | SQLite | Session memory, project memory, platform config |
| Version control | Git | Codebase versioning, Conductor-controlled |
| Web access | Playwright | Sandboxed read-only web access for agents |
| APScheduler | 4.x latest | Scheduled job execution for trading system |

---

## PLATFORM APPLICATIONS

All apps served through Caddy. Each is an independent service with its own backend and frontend.

```
ms-s1.tail123.ts.net/admin       → Admin panel
ms-s1.tail123.ts.net/autocoder   → Multi-agent development system
ms-s1.tail123.ts.net/chat        → Open WebUI (Docker, port 3000)
ms-s1.tail123.ts.net/writer      → Long-form writing assistant
ms-s1.tail123.ts.net/coding      → Personal coding assistant
ms-s1.tail123.ts.net/trading     → Trading dashboard, both pools, positions, alerts, settings
ms-s1.tail123.ts.net/...         → Extensible via admin panel
```

**Note on chat:** Open WebUI is served via Docker and proxied through Caddy. The custom
`platform/chat` service from Phase 3 is superseded by Open WebUI for general-purpose chat.

Each application:
- Runs as its own FastAPI service on a dedicated port
- Has its own React frontend
- Is registered and managed through the admin panel
- Can be added, removed, or reconfigured without touching other apps

---

## ADMIN PANEL

Central control surface for the entire platform. The primary interface for platform management — terminal access should rarely be needed after initial setup.

**Responsibilities:**
- Tailscale management — device list, network status, access control
- URL and routing management — register, remove, configure app routes
- Access control — per-app access permissions
- Ollama management — download models, load/unload, monitor GPU memory usage
- Service health — running status of all services, manual restart
- OS update management — trigger updates, blocked during active autocoder sessions
- System stats — CPU, GPU utilization, memory usage, temperature
- Agent creator — build, configure, and deploy new agents
- Tool library management — register and configure available tools

---

## TOOL LIBRARY

Reusable building blocks available to any agent. Managed through the admin panel.

| Tool | Capability | Notes |
|---|---|---|
| Filesystem | Scoped read/write | Path restrictions enforced per agent |
| Terminal | Sandboxed command execution | Restricted to project sandbox |
| Git | Local version control | Clone, commit, branch, diff, push |
| GitHub | OAuth, repo management | Push, pull, PR creation, repo access |
| Web | Read-only browsing | Playwright, logged, sandboxed |
| Database | SQLite + ChromaDB access | Scoped per project |
| Test runner | Execute and report | Returns structured pass/fail results |
| Code interpreter | Run and evaluate code | Sandboxed execution environment |

---

## AGENT CREATOR

Accessible via admin panel. Enables creation of fully capable custom agents without code changes.

**Per-agent configuration:**
- **Purpose** — system prompt defining behavior and constraints
- **Model** — selected from available Ollama models
- **Tools** — assigned from tool library
- **Integrations** — GitHub OAuth, API keys, external services
- **Memory scope** — session only / project / global
- **UI** — chat interface, dashboard, or none
- **URL** — registered route if UI is needed

---

## MODEL STRATEGY

All models served via Ollama. Model selection is task-driven.

| Task type | Model size | Example |
|---|---|---|
| Complex reasoning, orchestration | 70B quantized | Conductor, Architect |
| Domain-specific coding | 32B coding model | Qwen2.5-Coder 32B |
| Conversational, routing | 14B | RE-agent, simple chat |

The Conductor selects model per agent based on:
- Task complexity
- Domain specificity (general vs. code-trained)
- Whether the agent is blocking others (speed sensitivity)
- Context size required

---

## MEMORY ARCHITECTURE

Three distinct layers with different scopes and lifetimes.

### Session Memory
- **Scope:** Single autocoder run
- **Storage:** SQLite
- **Content:** Agent outputs, Conductor decisions, failure classifications, retry history, internet access log
- **Purpose:** Feeds the dashboard and morning review. Discarded or archived after review.

### Project Memory
- **Scope:** Per project, persists across sessions
- **Storage:** SQLite
- **Content:** Architecture decisions and rationale, what has been built, refactor history, open issues carried forward, morning review feedback
- **Purpose:** Enables session 2, 3, N on the same project. RE-agent reads this at session start.

### Cross-Run Memory
- **Scope:** Global, across all projects
- **Storage:** ChromaDB (vector database)
- **Content:** User preferences, recurring patterns, failure types and resolutions, coding style preferences
- **Purpose:** System learns over time. RE-agent queries relevant context at start of each new conversation.

**Git** handles codebase state — project memory focuses on decisions and rationale, not code.

---

## MULTI-USER ISOLATION

The platform supports multiple users (currently: Jonas, wife, a friend). Isolation is
data-level, not security-level — users do not have malicious intent, only a need to
keep their data separate (separate trading history, separate writing projects, etc.).

**Trading system isolation:**
Each user runs their own Docker container hosting a trading conductor instance.
Each container gets its own env vars pointing to a separate SQLite database:

```
TRADING_DB_PATH=/opt/platform/data/<username>/platform.db
TRADING_AUDITOR_URL=http://localhost:<user-specific-port>/audit/run
OLLAMA_BASE_URL=http://localhost:11434
IBKR_CLIENT_ID=<unique client id per container>
```

No `user_id` columns anywhere in the trading schema — the code is user-agnostic.
Docker container boundary is the isolation mechanism. See STACK.md for container setup.

**Other apps (writer, autocoder, coding assistant):**
Project-level isolation via separate project workspaces. No container isolation needed —
different users work on different projects and do not interfere.

---

## DOMAIN SEPARATION

Agents are grouped by domain. Domain boundaries are enforced architecturally —
agents cannot access tools, memory, or APIs belonging to another domain.
See CLAUDE.md (DOMAIN SEPARATION) and TRADING_ARCHITECTURE.md for full detail.

---

## AGENT PATTERNS

Three patterns cover all agent types on the platform:

### Interactive (user-present)
Agent drives a conversation to elicit information or produce content with real-time feedback.
- User and agent exchange multiple turns
- Session exists only while the user is present
- Examples: RE-agent, platform_chat, platform_writer, platform_coding

### Always-on
Agent runs continuously and produces output without user interaction.
- Starts at boot, stops only when service stops
- Produces events, signals, or state updates on its own schedule
- Examples: trading_monitor_stocks, trading_monitor_crypto, trading_position_manager, trading_auditor_compliance

### Job-based
Agent runs to completion on a trigger (time, event, or API call) and then stops.
- Stateless between runs — reads inputs, writes outputs, exits
- Examples: trading_wsb_dd, trading_wsb_mentions, trading_validator_signal, trading_validator_risk_gate, trading_execution_stocks, trading_execution_crypto, trading_learning_engine, morning_brief

---

## TRADING DASHBOARD PUSH CONTRACT

The trading conductor pushes status and events to the trading frontend over an internal HTTP endpoint.
This is Layer 3 — not exposed externally, not routed through Caddy.

**Endpoint:** `POST http://localhost:8765/push`

**Payload:**
```json
{
  "conductor": "trading",
  "agent": "trading_monitor_stocks",
  "type": "status|alert|insight",
  "timestamp": "2026-08-10T07:00:00Z",
  "user": "jarvis",
  "payload": { ... }
}
```

**Message types:**
- `status` — routine state update (positions, scheduler heartbeats, mode changes)
- `alert` — requires user attention (broker disconnected, rule breach, position force-exit)
- `insight` — informational (morning brief ready, learning engine weight update)

Port 8765 is reserved for this internal push channel. It is not exposed through Caddy and is not accessible externally.

---

## AUTOCODER — AGENT DEFINITIONS

### RE-agent
- **Role:** Requirements elicitation and quality gate
- **Model:** 14B (conversational)
- **Responsibility:** Capture user intent through dialogue. Stress-test requirements. Surface ambiguities and force resolution before pipeline starts. Produce a structured requirements document.
- **Quality gate:** Conductor validates requirements completeness before pipeline begins. If insufficient, returns to RE-agent — not to the user.
- **Reads:** Project memory, cross-run memory (user preferences, past patterns)

### Conductor
- **Role:** Orchestrator, planner, reviewer, Git controller
- **Model:** 70B
- **Responsibility:**
  - Validate RE-agent output completeness
  - Plan pipeline — which agents, which models, dependency order
  - Generate instructions for each specialist using per-agent templates
  - Review specialist output against quality rubric
  - Classify failures and decide response
  - Manage Git commits after each approved stage
  - Log all decisions to session memory
  - Control internet access logging
- **Does not:** Execute code, write implementation, interact with user during run

### Specialist Pool
Activated by Conductor as needed per project. Each has an instruction template and quality rubric.

| Agent | Model | Responsibility |
|---|---|---|
| Backend | Qwen2.5-Coder 32B | API design, server logic, data models |
| Frontend | Qwen2.5-Coder 32B | UI components, API integration |
| DB | Qwen2.5-Coder 32B | Schema design, migrations, queries |
| Tester | Qwen2.5-Coder 32B | Test writing, execution, coverage |
| Refactorer | Qwen2.5-Coder 32B | Code quality, consistency, optimisation |

---

## TRADING AGENTS

Full specification in `docs/TRADING_ARCHITECTURE.md`. One line per agent:

| Agent | Responsibility |
|---|---|
| trading_monitor_stocks | Watches S&P 500 + NASDAQ 100 for momentum signals |
| trading_monitor_crypto | Watches top 20 crypto for momentum signals |
| trading_wsb_dd | Processes WSB DD-flair posts, verifies thesis |
| trading_wsb_mentions | Tracks general WSB mention velocity and sentiment |
| trading_validator_signal | Conviction scoring, temporal state, catalyst quality |
| trading_validator_risk_gate | Hard-coded pre-order compliance checks |
| trading_execution_stocks | Places and manages orders via IBKR |
| trading_execution_crypto | Places and manages orders via Coinbase |
| trading_position_manager | Manages open positions, trailing stops |
| trading_auditor_compliance | Independent compliance checker, force-exits breaches |
| trading_learning_engine | Shadow portfolio, retrospective analysis, weight tuning |

---

## AUTOCODER — FLOW

```
User → RE-agent conversation
     → Conductor validates requirements
     → Conductor plans pipeline
     → [Sequential execution loop]
         Specialist runs
         → Conductor reviews output
         → Failure classification
             Solvable     → retry same agent, refined instructions
             Scope        → retry same agent, expanded instructions
             Architectural → replan from Conductor level
             Capability   → swap to larger model, retry
         → Accept → Git commit → next agent
     → Pipeline complete
     → Morning review available on dashboard
```

**Stopping conditions:**
- All agents complete and Conductor approves — success
- Unresolvable failure after classification — pipeline parked, flagged in dashboard with explanation
- There is no hardcoded retry limit — failure classification drives continuation decisions

---

## INTERNET ACCESS

- **Scope:** Read-only. Agents may query and retrieve. No posting, submitting, or interacting.
- **Implementation:** Playwright, sandboxed
- **Logging:** Every call recorded to session memory
- **Dashboard display:** High-level only by default

```
17:34:12 Conductor    Backend agent queried web — 3 results used
```

- **Drill-down:** Available per log entry on demand — shows query, sources, how it influenced output
- **Blocked:** During OS updates

---

## VERSION CONTROL

- Git, controlled exclusively by Conductor
- One commit per approved specialist stage
- Commit messages written by Conductor — meaningful, describing what was built and why
- Produces a readable history of the overnight run

---

## DASHBOARD — AUTOCODER UI

**Agent board:**
- Shows all agents that have contributed to the current project
- Live state per agent with color schema:
  - ⚪ Idle — available, not currently assigned
  - 🔵 Active — currently running
  - ✅ Completed — finished and approved
  - 🔴 Failed — output rejected, awaiting retry or replan
  - 🟡 Parked — pipeline paused, needs morning review

**Conductor session log:**
- Timestamped, high-level events only
- Failures visually distinct from normal entries
- Example entries:

```
17:34:45  Backend agent task complete — committed
17:41:02  Tester found 3 failures — retrying Backend
17:55:18  Backend agent task complete — committed
18:02:33  [PARKED] Architectural conflict detected — see morning review
```

**Morning review (integrated):**
- Summary of what was built
- Git diff per stage
- Test results
- Any parked issues with Conductor explanation
- Accessible from mobile via Tailscale

---

## REMOTE ACCESS

- **Technology:** Tailscale
- **Scope:** All platform apps accessible from any device on the Tailscale network
- **UI requirement:** All frontends must be mobile-responsive
- **Admin panel:** Manages Tailscale configuration
- **Agent services:** Internal only — not exposed through Tailscale directly

---

## DEPLOYMENT

- Development happens on a separate dev machine
- Code pushed to GitHub as source of truth
- Deployed to mini PC via SSH over Tailscale
- Each app is an independent deployable service
- Admin panel handles service restarts after deployment

---

## DOCUMENTATION

- `ARCHITECTURE.md` — this document
- `STACK.md` — tech stack with versions and configuration notes
- `BUILD_SEQUENCE.md` — ordered build plan with dependencies
- `SETUP.md` — ELI5 Ubuntu setup manual, from unboxing to running platform
- Per-component instruction documents — one per major component
- All documentation version-controlled alongside codebase

---

## WHAT THIS DOCUMENT IS NOT

This document describes architecture and intent. It does not contain:
- Implementation code
- API specifications (defined per-component)
- Database schemas (defined per-component)
- Deployment scripts (defined per-component)

When building any component, read this document first for context, then read the relevant component document for specifics.
