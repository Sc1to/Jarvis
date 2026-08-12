# STACK.md
# Personal AI Platform — Tech Stack Reference v0.1
# Specific versions, install commands, and configuration notes for every component.
# Read ARCHITECTURE.md first for system context.

---

## CONVENTIONS

- All services run on the mini PC (Ubuntu 24.04 LTS)
- Development happens on a separate dev machine
- Python virtual environments per service — never system-wide pip installs
- Node/React built on dev machine, static files served by Caddy or FastAPI
- All services run as systemd units for auto-restart and boot persistence
- Ports are internal only — Caddy is the single public-facing entry point

---

## PORT MAP

| Service | Port |
|---|---|
| Caddy | 80, 443 (public) |
| Open WebUI (Docker) | 3000 |
| Admin panel backend | 8000 |
| Autocoder — Conductor | 8001 |
| Autocoder — RE-agent | 8002 |
| Autocoder — Backend specialist | 8003 |
| Autocoder — Frontend specialist | 8004 |
| Autocoder — DB specialist | 8005 |
| Autocoder — Tester specialist | 8006 |
| Autocoder — Refactorer specialist | 8007 |
| Chat app backend | 8010 |
| Writer app backend | 8011 |
| Coding assistant backend | 8012 |
| Autocoder dashboard | 8050 |
| platform-trading backend | 8030 |
| platform-trading-auditor | 8031 |
| Trading dashboard push endpoint | 8765 (internal only, not in Caddy) |
| Ollama | 11434 |
| ChromaDB | 8020 |
| IBKR TWS — paper trading | 7497 |
| IBKR TWS — live trading | 7496 |

New apps registered via admin panel are assigned ports from 8100 upward.

---

## OPERATING SYSTEM

**Ubuntu 24.04 LTS**

- Download: https://ubuntu.com/download/desktop
- Install as primary OS on mini PC (replaces Windows)
- Enable automatic security updates during install or via:

```bash
sudo apt install unattended-upgrades
sudo dpkg-reconfigure unattended-upgrades
```

- Disable sleep and hibernate:

```bash
sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
```

---

## TAILSCALE

**Version:** Latest stable (auto-updates)
**Purpose:** Secure remote access from any device

**Install:**
```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

**Configuration:**
- Enable as systemd service (done automatically on install)
- Machine will appear in Tailscale admin console at https://login.tailscale.com
- Assign a stable machine name (e.g. `ms-s1`) in Tailscale console
- Access platform at `http://ms-s1.tail-xxxx.ts.net` from any Tailscale device

**Admin panel integration:**
- Tailscale status readable via `tailscale status --json`
- Device management links out to Tailscale console

---

## CADDY

**Version:** 2.x latest stable
**Purpose:** Reverse proxy, routing, automatic HTTPS

**Install:**
```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install caddy
```

**Base Caddyfile location:** `/etc/caddy/Caddyfile`

**Base configuration pattern:**
```
ms-s1.tail-xxxx.ts.net {
    handle /admin* {
        reverse_proxy localhost:8000
    }
    handle /autocoder* {
        reverse_proxy localhost:8001
    }
    handle /chat* {
        reverse_proxy localhost:8010
    }
    handle /writer* {
        reverse_proxy localhost:8011
    }
    handle /coding* {
        reverse_proxy localhost:8012
    }
}
```

**Admin panel integration:**
- Admin panel writes new route blocks to Caddyfile when apps are registered
- Caddy reloads config without downtime: `sudo systemctl reload caddy`
- Admin panel triggers reload after config changes

**Trading app routing (special case — two backend services):**
```
handle /trading/api/* {
    reverse_proxy localhost:8030
}
handle /trading/audit/* {
    uri strip_prefix /trading/audit
    reverse_proxy localhost:8031
}
handle /trading* {
    root * /opt/platform/frontend/trading/dist
    file_server
}
```

---

## OLLAMA

**Version:** Latest stable
**Purpose:** Local LLM serving and model management

**Install:**
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

**Service:** Runs automatically as systemd service on port 11434

**GPU memory configuration:**
- Set UMA Frame Buffer Size to **Auto** in BIOS. Do NOT use a fixed value — a fixed partition hides memory from the ROCm allocator, limiting model loading to ~27 GB regardless of physical RAM. Auto leaves the full pool CPU-visible, which is what ROCm needs on this iGPU (NO_VMM=1 architecture).
- Disable the display manager: `sudo systemctl disable gdm3` — the GNOME compositor claims GPU memory through the KMS/DRM stack, blocking ROCm from using it.
- Verify GPU is being used: `ollama run qwen2.5:72b-instruct-q4_K_M "test"` then check `ollama ps` — should show 100% GPU

**Environment variables (add to systemd service or ~/.bashrc):**
```bash
OLLAMA_HOST=0.0.0.0          # Allow connections from other services
OLLAMA_MAX_LOADED_MODELS=3   # Limit simultaneous loaded models (memory management)
OLLAMA_NUM_PARALLEL=1         # One request at a time per model
```

**Initial model downloads:**
```bash
# 14B — conversational, RE-agent, routing
ollama pull qwen2.5:14b

# 32B coding — specialist agents
ollama pull qwen2.5-coder:32b

# 70B — Conductor, complex reasoning (quantized)
ollama pull qwen2.5:72b-instruct-q4_K_M
```

**API usage (internal, Python):**
```python
import httpx

response = httpx.post("http://localhost:11434/api/chat", json={
    "model": "qwen2.5-coder:32b",
    "messages": [{"role": "user", "content": "prompt here"}],
    "stream": False
})
```

**Admin panel integration:**
- List models: `GET http://localhost:11434/api/tags`
- Pull model: `POST http://localhost:11434/api/pull`
- Delete model: `DELETE http://localhost:11434/api/delete`
- Running models: `GET http://localhost:11434/api/ps`

---

---

## OPEN WEBUI

**Version:** Latest stable (Docker image: `ghcr.io/open-webui/open-webui:main`)
**Purpose:** Primary chat interface — replaces the custom Phase 3 chat app
**Port:** 3000 (Docker internal → Caddy proxies `/chat`)

**Run:**
```bash
docker run -d \
  --name open-webui \
  --restart always \
  -p 3000:8080 \
  -v open-webui:/app/backend/data \
  -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
  ghcr.io/open-webui/open-webui:main
```

**Caddy route** (add to Caddyfile):
```
handle /chat* {
    reverse_proxy localhost:3000
}
```

---

## PYTHON

**Version:** 3.12 (ships with Ubuntu 24.04)

**Virtual environment per service:**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**Never install packages system-wide with pip.**

---

## FASTAPI

**Version:** 0.115.x latest
**Purpose:** Backend for all services

**Install (per service venv):**
```bash
pip install fastapi uvicorn[standard]
```

**Run pattern:**
```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload  # development
uvicorn main:app --host 0.0.0.0 --port 8000            # production
```

**Systemd service template** (`/etc/systemd/system/platform-admin.service`):
```ini
[Unit]
Description=Platform Admin Service
After=network.target

[Service]
Type=simple
User=jarvis
WorkingDirectory=/opt/platform/admin
ExecStart=/opt/platform/admin/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable platform-admin
sudo systemctl start platform-admin
```

---

## REACT

**Version:** 18.x
**Purpose:** Frontend for all web applications
**Build tool:** Vite

**Create new app:**
```bash
npm create vite@latest app-name -- --template react
cd app-name
npm install
```

**Key dependencies (install per app as needed):**
```bash
npm install axios                    # HTTP client
npm install react-router-dom         # Routing
npm install @tanstack/react-query    # Server state management
npm install zustand                  # Client state management
npm install tailwindcss              # Styling
```

**Build for production:**
```bash
npm run build
# Output in dist/ — serve via Caddy or FastAPI static files
```

**Mobile-responsive requirement:**
- All UIs must work on mobile browsers (accessed via Tailscale)
- Use Tailwind responsive prefixes (sm:, md:, lg:) throughout
- Test at 390px width minimum

---

## LANGGRAPH

**Version:** 0.2.x latest
**Purpose:** Multi-agent orchestration and state management

**Install (per service venv):**
```bash
pip install langgraph langchain langchain-community
```

**Core pattern for Conductor:**
```python
from langgraph.graph import StateGraph, END
from typing import TypedDict, Annotated
import operator

class PipelineState(TypedDict):
    requirements: str
    current_agent: str
    agent_outputs: Annotated[list, operator.add]
    failure_count: dict
    session_log: Annotated[list, operator.add]

graph = StateGraph(PipelineState)
graph.add_node("conductor", conductor_node)
graph.add_node("backend_agent", backend_node)
# ... add nodes
graph.add_conditional_edges("conductor", route_to_agent)
```

**Local LLM integration with LangGraph:**
```python
from langchain_community.chat_models import ChatOllama

llm = ChatOllama(model="qwen2.5:72b-instruct-q4_K_M", base_url="http://localhost:11434")
```

---

## CHROMADB

**Version:** 0.5.x latest
**Purpose:** Cross-run vector memory — user preferences, patterns, past context

**Install (per service venv):**
```bash
pip install chromadb
```

**Run as persistent server:**
```bash
chroma run --host localhost --port 8020 --path /opt/platform/data/chromadb
```

**Systemd service:** Follow FastAPI systemd pattern above, adjust ExecStart.

**Python client:**
```python
import chromadb

client = chromadb.HttpClient(host="localhost", port=8020)
collection = client.get_or_create_collection("cross_run_memory")

# Store
collection.add(
    documents=["user prefers minimal comments in code"],
    metadatas=[{"type": "preference", "project": "global"}],
    ids=["pref_001"]
)

# Query
results = collection.query(
    query_texts=["coding style"],
    n_results=5
)
```

---

## SQLITE

**Version:** Ships with Python (no install needed)
**Purpose:** Session memory, project memory, platform configuration

**Location:** `/opt/platform/data/platform.db`

**Python usage:**
```python
import sqlite3

conn = sqlite3.connect("/opt/platform/data/platform.db")
conn.row_factory = sqlite3.Row  # Access columns by name
```

**ORM (optional but recommended):**
```bash
pip install sqlalchemy alembic
```

**Key tables (defined per-component, listed here for reference):**
- `sessions` — autocoder run metadata
- `session_events` — timestamped log entries per session
- `projects` — project registry
- `project_memory` — decisions and rationale per project
- `agents` — registered agent configurations
- `apps` — registered platform apps and routes
- `internet_log` — agent web access records

---

## GIT

**Version:** Ships with Ubuntu
**Purpose:** Codebase versioning, Conductor-controlled

**Install if missing:**
```bash
sudo apt install git
```

**Conductor uses subprocess for Git operations:**
```python
import subprocess

def git_commit(repo_path: str, message: str):
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True)
    subprocess.run(["git", "commit", "-m", message], cwd=repo_path, check=True)
```

**Each project gets its own Git repo** under `/opt/platform/projects/<project-name>/`

---

## GITHUB

**Purpose:** Remote code storage, coding assistant integration
**Authentication:** OAuth per user via GitHub Apps or Personal Access Token

**Python library:**
```bash
pip install PyGithub
```

**Usage:**
```python
from github import Github

g = Github("access_token")
repo = g.get_repo("username/repo-name")
```

**Coding assistant agent** uses GitHub for:
- Cloning user repos into scoped project folders
- Pushing commits and branches
- Creating pull requests
- Reading issues and repository context

---

## PLAYWRIGHT

**Version:** Latest stable
**Purpose:** Sandboxed read-only web access for agents

**Install:**
```bash
pip install playwright
playwright install chromium
playwright install-deps chromium
```

**Usage pattern (read-only enforced):**
```python
from playwright.async_api import async_playwright

async def web_search(query: str) -> str:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        # Block all POST, PUT, DELETE, PATCH requests
        await page.route("**/*", lambda route: route.abort()
            if route.request.method != "GET"
            else route.continue_())
        await page.goto(f"https://search-engine.com/search?q={query}")
        content = await page.content()
        await browser.close()
        return content
```

**All web access must:**
1. Be logged to session memory before the call
2. Be logged with results summary after the call
3. Block non-GET HTTP methods
4. Run in headless mode
5. Have a timeout (30 seconds max per request)

---

## APSCHEDULER

**Version:** 4.x latest
**Purpose:** Scheduled job execution — runs within trading FastAPI service

**Install (trading service venv):**
```bash
pip install apscheduler
```

**Job schedule:**
- Trailing stop check:        every 15 minutes (all hours, all days)
- Full compliance audit:      every 2 hours
- Market open audit:          daily 09:30 EST (stocks), continuous (crypto)
- WSB monitoring:             every 30 minutes market hours, hourly overnight
- Catalyst calendar check:    daily at 06:00
- Learning engine:            daily at 05:00
- Morning brief generation:   daily at 07:00

---

## WEB PUSH NOTIFICATIONS

**Purpose:** Server-to-browser push alerts for trading events (morning brief, force exits)
**Library:** `pywebpush>=2.0` — server-side Web Push with VAPID signing
**Standard:** Web Push API (VAPID, EC P-256)

**Install (trading service venv):**
```bash
pip install pywebpush
```

**Key points:**
- VAPID keys generated once on first startup, stored in `trading_config` (never in files)
- Subscriptions stored in `trading_push_subscriptions` table
- `pywebpush.webpush()` is synchronous — always call via `asyncio.to_thread()` from async contexts
- Dead subscriptions (HTTP 410 from push service) are automatically pruned

---

## BROKER AND EXCHANGE TOOLS

### IBKR TWS + ib_insync
**Purpose:** Stock order placement and management
**Connection:** TWS (Trader Workstation) running on mini PC, managed by IBC + Xvfb (headless)
**Library:** `ib_insync>=0.9.86` — Python async wrapper for the TWS API socket
**Paper trading port:** 7497
**Live trading port:** 7496
**Authentication:** Handled automatically by IBC — no daily re-auth required
**Full setup:** See `docs/IBKR_SETUP.md`

**Environment variables:**
```
IBKR_TWS_HOST=127.0.0.1
IBKR_TWS_PORT_PAPER=7497
IBKR_TWS_PORT_LIVE=7496
IBKR_CLIENT_ID=1            # unique per Docker container for multi-user
```

**Install (trading venv):**
```bash
pip install ib_insync
```

**Usage pattern:**
```python
from ib_insync import IB, Stock, MarketOrder, util
util.patchAsyncio()  # required for FastAPI compatibility

ib = IB()
await ib.connectAsync("127.0.0.1", 7497, clientId=1)  # paper
# or 7496 for live
```

### Coinbase Advanced Trade API
**Purpose:** Crypto order placement and management
**Authentication:** API key + secret stored in SQLite config table — never hardcoded
**Sandbox:** Available — use for all development and testing
**Library:** Direct REST via httpx

### Reddit API (praw)
**Purpose:** WSB monitoring — DD posts and general mention tracking
**Authentication:** OAuth2 credentials stored in SQLite config table
**Install:** `pip install praw`
**Rate limit:** 60 requests per minute — scheduler must respect this

### Pushshift
**Purpose:** Historical Reddit data for WSB correlation engine bootstrap
**Base URL:** `https://api.pushshift.io`
**Authentication:** None required for basic access
**Library:** Direct REST via httpx

### SEC EDGAR
**Purpose:** Verify fundamental catalysts from primary source
**Base URL:** `https://data.sec.gov/api/xbrl/`
**Authentication:** None required — include `User-Agent` header identifying the app
**Library:** Direct REST via httpx

---

## DIRECTORY STRUCTURE

```
/opt/platform/
├── admin/                  # Admin panel service
│   ├── venv/
│   ├── main.py
│   └── requirements.txt
├── autocoder/
│   ├── conductor/          # Conductor service
│   ├── re-agent/           # RE-agent service
│   └── specialists/        # Specialist agent services
├── chat/                   # Chat app service
├── writer/                 # Writer app service
├── coding/                 # Coding assistant service
├── trading/                # Trading system backend
│   ├── venv/
│   ├── main.py
│   ├── scheduler.py        # APScheduler job definitions
│   ├── risk_gate.py        # Hard-coded risk rules — never modified by AI
│   ├── compliance_auditor.py  # Independent compliance checker
│   └── requirements.txt
├── frontend/               # All React apps (built separately)
│   ├── admin/
│   ├── autocoder/
│   ├── chat/
│   └── writer/
├── data/
│   ├── platform.db         # SQLite database
│   ├── chromadb/           # ChromaDB persistent storage
│   └── projects/           # Autocoder project workspaces
│       └── <project-name>/
│           ├── .git/
│           └── src/
└── docs/                   # All documentation
    ├── ARCHITECTURE.md
    ├── STACK.md
    ├── BUILD_SEQUENCE.md
    └── SETUP.md
```

---

## SYSTEMD SERVICES REGISTRY

All platform services run as systemd units. Naming convention: `platform-<service-name>`

| Service name | Unit file |
|---|---|
| platform-admin | /etc/systemd/system/platform-admin.service |
| platform-autocoder-conductor | /etc/systemd/system/platform-autocoder-conductor.service |
| platform-autocoder-re-agent | /etc/systemd/system/platform-autocoder-re-agent.service |
| platform-autocoder-specialist-backend | /etc/systemd/system/platform-autocoder-specialist-backend.service |
| platform-autocoder-specialist-frontend | /etc/systemd/system/platform-autocoder-specialist-frontend.service |
| platform-autocoder-specialist-db | /etc/systemd/system/platform-autocoder-specialist-db.service |
| platform-autocoder-specialist-tester | /etc/systemd/system/platform-autocoder-specialist-tester.service |
| platform-autocoder-specialist-refactorer | /etc/systemd/system/platform-autocoder-specialist-refactorer.service |
| platform-autocoder-dashboard | /etc/systemd/system/platform-autocoder-dashboard.service |
| platform-chat | /etc/systemd/system/platform-chat.service |
| platform-writer | /etc/systemd/system/platform-writer.service |
| platform-coding | /etc/systemd/system/platform-coding.service |
| platform-trading | /etc/systemd/system/platform-trading.service |
| platform-chromadb | /etc/systemd/system/platform-chromadb.service |
| platform-health-monitor | /etc/systemd/system/platform-health-monitor.service |
| platform-ibkr-tws | /etc/systemd/system/platform-ibkr-tws.service |

**Common commands:**
```bash
sudo systemctl status platform-admin     # Check status
sudo systemctl restart platform-admin    # Restart
sudo systemctl logs -u platform-admin    # View logs
sudo journalctl -u platform-admin -f     # Follow logs live
```

---

## DOCKER

**Purpose:** Infrastructure services (Open WebUI) and per-user trading conductor isolation
**Install:**
```bash
sudo apt install -y docker.io
sudo systemctl enable docker
sudo systemctl start docker
sudo usermod -aG docker jarvis
```

**Local dev environment:**
A Docker Compose stack lives in `docker/` for local development:
```bash
cd docker && cp .env.docker.example .env.docker  # fill in values
docker compose up -d
```
Covers: admin, chat, writer, coding, conductor, re-agent, autocoder-dashboard, chromadb, ollama.
Build contexts for Python services point to `platform/` (not per-service) so shared `memory/` and `tools/` packages are accessible.

Setup script for Windows: `./docker/setup-windows.ps1`

**Per-user trading conductor:**
Each user gets a Docker container running the trading conductor with isolated env vars:
```bash
docker run -d \
  --name trading-<username> \
  --restart always \
  -e TRADING_DB_PATH=/data/<username>/platform.db \
  -e TRADING_AUDITOR_URL=http://host.docker.internal:8031/audit/run \
  -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
  -e IBKR_CLIENT_ID=<unique-int> \
  -v /opt/platform/data:/data \
  platform-trading:latest
```

No `user_id` columns in the trading schema. Container boundary provides isolation.

---

## DEVELOPMENT WORKFLOW

1. Write and test code on dev machine
2. Push to GitHub
3. SSH into mini PC via Tailscale: `ssh jarvis@ms-s1`
4. Pull latest code: `git pull`
5. Restart affected service: `sudo systemctl restart platform-<service>`
6. Verify via admin panel service health view

**Deploy scripts (in `scripts/`):**
- `deploy.sh [service]` — pull + pip install + restart + health check for one or all services
- `deploy-frontend.sh [app]` — build React app + scp dist/ to mini PC + caddy reload
- `first-time-setup.sh` — initial venv creation and systemd unit installation (run once)
- `rollback.sh [service]` — revert to previous commit with confirmation prompt

**Test suite (`scripts/tests/`):**
```bash
python scripts/tests/run_tests.py --target local --suite all
python scripts/tests/run_tests.py --target remote --suite health,models
```
Suites: `health`, `models`, `memory`, `tools`, `pipeline`, `ui`

**Future:** Admin panel can trigger pull + restart directly, removing need for SSH after initial setup.

---

## NOTES FOR CLAUDE CODE

- Always use virtual environments — never system pip
- Always add new services to the systemd registry
- Always register new apps in the admin panel's app table, not hardcoded in Caddyfile
- All agent internet access must go through the Playwright web tool — never direct httpx/requests calls from agents
- SQLite database path is always `/opt/platform/data/platform.db`
- ChromaDB is always at `http://localhost:8020`
- Ollama is always at `http://localhost:11434`
- New ports for apps start at 8100 — check the port map before assigning
