# Jarvis — Personal AI Platform

A locally-run personal AI platform hosted on a Minisforum MS-S1 Max mini PC. The platform serves multiple independent AI-powered web applications through a single reverse proxy (Caddy), accessible remotely from any device via Tailscale. The flagship application is an autonomous multi-agent development system (autocoder) capable of overnight unsupervised runs — define intent once via conversation, agents design, build, test, and refactor overnight, review results in the morning.

---

## Applications

| App | Route | Description | Phase |
|---|---|---|---|
| Admin Panel | `/admin` | Platform management — services, models, agents, network | Phase 5 |
| Autocoder | `/autocoder` | Multi-agent autonomous development system | Phase 8–9 |
| Chat | `/chat` | Simple LLM chat interface | Phase 3 |
| Writer | `/writer` | Long-form writing assistant | Phase 10 |
| Coding | `/coding` | Personal coding assistant | Phase 6 |

---

## Tech Stack

- **OS:** Ubuntu 24.04 LTS
- **Remote access:** Tailscale
- **Reverse proxy:** Caddy
- **Model backend:** Ollama (local LLMs — Qwen2.5 14B / 32B Coder / 72B)
- **Agent orchestration:** LangGraph
- **Backend:** Python 3.12 + FastAPI (uvicorn)
- **Frontend:** React 18 + Vite + Tailwind CSS
- **Vector DB:** ChromaDB (cross-run agent memory)
- **Structured storage:** SQLite (session memory, project memory, config)
- **Web access (agents):** Playwright (sandboxed, read-only)

---

## Documentation

| Document | Purpose |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design, agent definitions, memory layers, flows |
| [docs/STACK.md](docs/STACK.md) | Tech stack, exact versions, port map, install commands |
| [docs/BUILD_SEQUENCE.md](docs/BUILD_SEQUENCE.md) | Ordered build plan with Claude Code prompts per component |
| [docs/SETUP.md](docs/SETUP.md) | ELI5 Ubuntu setup manual — from unboxing to running platform |

---

## Build Status

```
Current phase:     Phase 1 — Foundation (NOT STARTED)
Last completed:    Nothing yet — project just initialised
Currently working: Initial repository setup
Blocked on:        Nothing
```

**Completed components:**
- [ ] Phase 1  — Foundation (mini PC setup)
- [ ] Phase 2  — Ollama & Model Backend
- [ ] Phase 3  — Platform Validation (Chat app)
- [ ] Phase 4  — Tool Library
- [ ] Phase 5  — Admin Panel
- [ ] Phase 6  — Personal Coding Assistant
- [ ] Phase 7  — Memory Infrastructure
- [ ] Phase 8  — Autocoder Foundation
- [ ] Phase 9  — Autocoder Specialist Agents
- [ ] Phase 10 — Writer App
- [ ] Phase 11 — Hardening
- [ ] Phase 12 — Documentation

---

## Setup

See [docs/SETUP.md](docs/SETUP.md) for the full setup guide — from unboxing the mini PC to a running platform accessible from your phone.

The one-command setup (once the mini PC is running Ubuntu):

```bash
bash scripts/setup.sh
```

This script is implemented in Phase 12. See [docs/BUILD_SEQUENCE.md](docs/BUILD_SEQUENCE.md) to follow the build from the beginning.
