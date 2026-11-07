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
8. `/docs/BOOKFORGE.md` — bookforge book-writing pipeline (Phase 14, only when working on it)

If anything in a task prompt contradicts these documents, flag the contradiction
and ask before proceeding. Do not resolve contradictions silently.

---

## BUILD STATUS

Update this section at the start of each session to reflect current reality.

```
Current phase:     Phase 13 — Trading System
Last completed:    Phase 13.19 — Paper trading validation tooling; Phase DEV — Docker, deploy scripts, test suite
                   Writer app enhancements (2026-09-23) — author scene-prose editing, manual-mode QA hold, first writer tests
                   Writer app steering (2026-09-24) — length targets + trimming, anti-recap context, standing notes, pause/regenerate scenes
                   Writer app token-usage reduction (2026-09-25) — LLM usage logging (llm_usage_log table), capped entity eventLog for QA prompts (cap_event_logs), fixed unbounded QA prior-scenes text in rewrite_scene
                   Writer app token-usage reduction II (2026-10-29) — QA ledger scoped to scene entities (+ names-only roster), QA gets condensed prior scenes, QA-failed retries use a targeted fix call (no ledger/history) instead of a full rewrite
                   Bible Workshop manual editing (2026-11-04) — edit unapproved Book/Acts/chapter-plan/scene-brief text directly; structural validation + confirm detected counts before save; optional brief QA
                   Phase 14 planning (2026-11-05) — bookforge spec adopted as docs/BOOKFORGE.md; ports, colibri backend, systemd names and BUILD_SEQUENCE entry documented (docs only, no code)
                   Phase 14.0 (2026-11-05) — bookforge service shell: platform/bookforge (health + error envelope, 5 tests), systemd unit, frontend/bookforge placeholder, deploy.sh / build-frontends.sh wiring; not yet deployed
                   Phase 14.1 (2026-11-05) — bookforge skeleton: CLI (new/run/status/approve/doctor), layered config, state.json, vcs.py (git per series), fake LLM client; 75 tests; layer handlers still empty
                   Phase 14.2 (2026-11-05) — bookforge llm.py (retrying OpenAI-compatible client, call log), research/search.py (Playwright web tool wrapper with URL safety checks), doctor endpoint + web checks; 142 tests
                   Phase 14.3 (2026-11-05) — bookforge layers 1-3: prompt templates (series-overridable), shared generate/check/correct loop, series + book north stars and synopsis, direction checkpoint (approve commits your edits); 184 tests; prompts are first drafts, not yet run against a real model
                   Phase 14.4 (2026-11-05) — bookforge research step: questions, web-tool search + fetch, facts kept only with a verbatim quote from the page, sources.jsonl / questions.jsonl / notes per scope, blocked-search detection; shared web_tool now returns page links; 242 tests; only run against scripted searches (DuckDuckGo is blocked from the dev sandbox)
                   Phase 14.5 (2026-11-05) — bookforge layers 4-6 + bible: acts, cast/constants, chapters (per act) + state tracks, scenes (per chapter) + timeline, cached resumable pieces, state_at lookups + `state-at` command, whole-book cross-checks; 355 tests; structural checks only, prompts not yet run against a real model
                   Phase 14.6 (2026-11-05) — bookforge briefing builder (token budget, trimming order), deps.yaml content fingerprints, prose layer (drafts, best-of by mechanical score, summaries, voice checkpoint after chapter 1), mechanical checker, `briefing` and `check` commands, starter banned list; 432 tests; no model critic yet (14.7), prompts not yet run against a real model
                   Phase 14.7 (2026-11-05) — bookforge quality control: pairwise judge, continuity questions (planner model stands in for System One), rubric critic, passage-level revision loop, extraction of observed states + gaps, critic review of layers 4-6 (unresolved notes in reports/review-notes.jsonl), `review` command; model-based layers each switchable under qc:; prompts not yet run against a real model
                   Phase 14 first mini-PC run (2026-11-05) — tests pass on the MS-S1 (Python 3.14); doctor, series north star and research questions ran against Ollama (llama3.3); search engines block the web tool, so research now defaults to Wikipedia's API (research.source), doctor probes search and accepts Ollama's implicit :latest; the rest of the first book not yet reviewed; Ollama answered some requests as if they were the previous one (same opening words) — every request now starts with a unique line (`isolate_requests`, default on); research facts must now fit the story's setting (per-question `setting`, relevance check `research.check_relevance`, list articles read last)
                   Phase 14.8 (2026-11-05) — bookforge staleness + change requests: `stale` scans deps.yaml fingerprints (and a plan snapshot taken at structure approval), `stale --fix` re-checks, patches or redrafts scene by scene (hand-written text never rewritten), `stale --accept`; extraction gaps filed as change requests (`changes` list/--approve/--reject; within-chapter ones auto-applied per qc.critic_may_accept); 594 tests; not yet run against a real model
                   Phase 14.9 (2026-11-05) — bookforge morning report (reports/<date>.md at the end of every run; `report`), assembly (`assemble`, manuscript.md, final checkpoint, b1-draft-N tags; run assembles when complete), regression benchmarks (`bench`, 5 shipped briefs, pairwise judge vs accepted run); 620 tests; not yet run against a real model
                   Phase 14.10 (2026-11-05) — bookforge service API: /api routes for series, status, scenes, reports, manuscript, stale, change requests, approvals, assemble, plus background jobs (run, stale/fix, bench; one per series, records in logs/jobs); CLI and API share bookforge/ops.py; tests; frontend still the 14.0 placeholder
                   Phase 14.11 (2026-11-05) — bookforge dashboard (frontend/bookforge): series list, overview with run/approve/assemble, progress tree, scene view with draft compare + review, inbox (change-request diffs, stale, morning report), track timeline, research browser, manuscript, jobs; Web Push (push.py, own push.db, sw.js); API gained structure/tracks/research/drafts/push routes; checked at 390px against a seeded service; no frontend unit tests
                   Phase 14.12 (2026-11-05) — bookforge export (`export`, Pandoc): DOCX manuscript format, EPUB, print PDF (Typst/XeLaTeX/LuaLaTeX, untested here: no engine installed), companion book; matter files, export: config, scene-break filter, b1-export-<date> tags, exports/ not in Git; API job + downloads, dashboard Export card, doctor checks; 20 + 2 new tests
                   Phase 14.13 (2026-11-05) — bookforge workbench: rules panel (workbench/rules.yaml; banned phrases, style rules, hard constraints, character voices enforced by the mechanical checker, writer/critic prompts and continuity; hit counts, health, test-before-save, feedback-to-rule), briefing preview + X-ray with diagnosis, prompt studio, blind A/B tests with promote, calibration chart, tension curve with consequence preview, thread map; Workbench tab in the dashboard; character arc lanes not built
                   HTTPS (2026-11-05) — Caddy site address is now the Tailscale MagicDNS name (automatic Tailscale certificate) plus http://<tailscale-ip> as fallback, generated by scripts/build-frontends.sh (and setup.sh); needed for service workers / Bookforge Web Push; one-time tailnet + tailscaled setup in docs/SETUP.md "Enable HTTPS"; verified on the mini PC (valid cert, push test arrives)
                   Bookforge fixes from the first real run (2026-11-05) — qwen3.5:35b on Ollama needs `models.<role>.extra_body: {reasoning_effort: none}` (else it thinks until the token budget is gone); `rewrite` command (deleting a scene's files never rewrote it); read the direction/structure/bible/voice files in the dashboard (Documents tab); delete books and series (trash for series); research now searches the real web through a self-hosted SearXNG (docker, 127.0.0.1:8060, scripts/setup-searxng.sh; auto-falls back to Wikipedia), reads the relevant parts of pages, skips junk sites, and `research-test` shows one question end to end; SearXNG not yet installed or tried on the mini PC
                   Bookforge research rework (2026-11-06) — web tool waits for script-filled pages; the model picks which search results to read first (`research.model_pick`); `research-test --show-pages`; a claim may say only what its quote says (reader prompt + relevance check); knowledge needs with a stance (ground / extrapolate / bend / invent): realism setting in both north stars, `needs.jsonl` per scope, `needs` command + API + Inbox card to approve, reject or edit proposed rules, approved decisions in the scene briefing / continuity / deps.yaml filtered by `applies_to`, `research-eval` batch check; design in docs/BOOKFORGE.md "Knowledge needs"; 840+ tests; none of it yet run against a real model (qwen3.5)
                   Bookforge series management (2026-11-06) — add books to a series (own brief + north star, inherits the series north star), book titles, rename a series, `redo` a planning layer with a note (cascade, checkpoints reset, nothing deleted), edit documents in the dashboard (validated, only new problems refuse), Stop a running job (cooperative: before the next model call); ids of deleted books never reused; prepares the first end-to-end run; ledger writer, series config in the app and a book switcher not yet built
                   Bookforge flagged scenes (2026-11-06) — a flagged scene is revised from its saved text with specific per-finding prompts (the words, the fact, what to do) before it is written again, and the writer is told what was wrong; a must_show change that is not shown is repaired by an inserted passage; findings can be dismissed (false alarm) or given an instruction in the scene's Review tab (`finding` command); a state that begins in the scene gets no fixed-fact question and approved decisions only warn; first real run fixes: YAML colons, ship settings, tracks by chapter, new-track owners, text shapes, redo archives research
                   Bookforge run activity + cut-off replies (2026-11-06) — a running job's Overview card shows the layer, scene, step, model calls, scenes done and 'waiting for the model for N s' (activity.py, in memory, server clock); a cut-off scene draft is a failed draft (no larger limit, the other draft carries the scene), a repeating model is detected and the call log keeps the tail of a cut-off reply, `layers.prose.max_tokens` separates the draft ceiling from `words`; small calls still retry with a larger limit
                   Bookforge write the prose again (2026-11-06) — 'Write again…' on the prose row of the Overview (all scenes or one chapter, preview of what is reset, keep or discard your own text, optionally ask for the voice checkpoint again); `rewrite all`, `--reset-voice`, `GET .../rewrite-plan`
                   Bookforge continuity answers (2026-11-06) — the continuity check answers with a relation (contradicts / agrees / silent; shown / not_shown) instead of yes/no: on the first prose run scenes were flagged because the model answered 'yes' and quoted words that CONFIRMED the fact; only 'contradicts' with a real quote flags a scene
                   Bookforge critic rewrite (2026-11-06) — a scene the critic marks down on beats_covered or pacing (whole-scene criteria three patched lines cannot fix) is written again once with the critic's notes in the briefing (failed scores with the rubric line, the quoted weak lines and what is wrong with them, the beats in order); a flagged scene gets the same notes on the next Run; `qc.critic_rewrite`
                   Bookforge tokens per run (2026-11-06) — the Overview shows the tokens spent this run (prompt in / reply out, from the server's usage, cut-off replies included), the Jobs tab keeps each run's total, the call log keeps the usage of a cut-off call so the morning report counts it
                   Bookforge continuity second check (2026-11-06) — every 'contradicts' flag is re-asked in a narrow call (fact + quoted paragraph, the two compared values named) and kept only if confirmed; unconfirmed ones go to 'unsure' (`qc.confirm_contradictions`)
                   Bookforge pause and resume (2026-11-07) — the next Run continues at a stated scene (Overview line, `status`); interrupted scene first, scenes still to do next, flagged scenes retried last (`layers.prose.retry_flagged`); an interrupted scene keeps its drafts and passed judge/continuity/critic checks (`progress.json`); Stop is now Pause
                   Bookforge one model for the prose layer (2026-11-07) — `qc.model` (default `writer`): the draft judge, continuity questions and rubric critic run on the writer model at `qc.temperature` 0.2, so prose needs one loaded model instead of swapping per scene; `critic` restores the old behaviour; planning layers unchanged; docs/BOOKFORGE.md corrected (the pipeline never grouped calls by model); 996 tests; not yet run against a real model
                   Bookforge models and dark mode (2026-11-07) — Models tab + `GET /api/models` / `PUT /api/series/{s}/models` (backends, loaded and installed models, memory warning, who uses which); research and extraction roles (`models.assign`), per-layer models and named endpoints (`models.extra`), choices in `<series>/models.local.yaml`; an Ollama model no role uses is unloaded; colibri read-only (one model per server, no load API); dark mode (Auto/Light/Dark, remembered, no flash); 1010 tests; checked at 390px in both themes against a fake Ollama; not yet run against real colibri
Currently working: Phase 13.20 — Live trading activation (manual user decision); Phase 14 — Bookforge (14.0–14.13 done; Phase 14 complete, awaiting a real-model run)
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
- [ ] Phase 14  — Bookforge (14.0-14.13 done: shell, skeleton, llm + doctor, layers 1-3, research, layers 4-6 + bible, briefing + prose + mechanical checks, critic/continuity/judge/revision/extraction, staleness + change requests, morning report + assembly + benchmarks, service API, dashboard, export, workbench; every milestone built, none yet run end to end against the real models)

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
- Docker is used for infrastructure services only (Open WebUI, SearXNG for bookforge research, per-user trading conductors)
- Custom platform services (admin, autocoder, trading core, etc.) run as systemd units — not Docker
- Per-user trading conductor containers use env vars for isolation: `TRADING_DB_PATH`, `TRADING_AUDITOR_URL`, `OLLAMA_BASE_URL`, `IBKR_CLIENT_ID`

**Database:**
- Default SQLite path: `/opt/platform/data/platform.db`
- Trading per-user path: set via `TRADING_DB_PATH` env var on each container
- ChromaDB is always at `http://localhost:8020`
- Ollama is always at `http://localhost:11434` (default model backend for all apps; the one exception is bookforge, which uses colibri on `:8040` / `:8041` — see STACK.md)

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
│   ├── bookforge/              ← Phase 14 (shell + CLI skeleton)
│   ├── coding/
│   ├── memory/                 ← shared memory package
│   └── tools/                  ← shared tool library
├── frontend/                   ← all React apps
│   ├── admin/
│   ├── autocoder/
│   ├── chat/
│   ├── writer/
│   ├── bookforge/              ← Phase 14 (placeholder)
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
