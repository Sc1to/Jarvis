# BUILD_SEQUENCE.md
# Personal AI Platform — Build Sequence v0.1
# Ordered build plan with dependencies and Claude Code task instructions.
# Read ARCHITECTURE.md and STACK.md before working on any component.

---

## HOW TO USE THIS DOCUMENT

Each phase contains:
- **Goal** — what this phase achieves
- **Dependencies** — what must be complete before starting
- **Components** — individual buildable units in order
- **Claude Code prompt** — paste this when starting each component

Complete phases in order. Do not skip ahead — each phase validates the foundation for the next.

When starting a new component, always tell Claude Code:
1. Read ARCHITECTURE.md
2. Read STACK.md
3. Read this BUILD_SEQUENCE.md
4. Then read the specific prompt below

---

## PHASE 1 — FOUNDATION

**Goal:** Mini PC is running Ubuntu, remotely accessible, traffic routed correctly.
**Note:** This phase is setup work on the mini PC, not development work. Follow SETUP.md (ELI5 manual). No code is written here — the output is a running, accessible server.

### 1.1 Ubuntu Installation
See SETUP.md — step by step installation guide.

### 1.2 BIOS Configuration
See SETUP.md — GPU memory allocation, auto power-on, disable sleep.

### 1.3 Tailscale
See SETUP.md — install, authenticate, verify remote access.

### 1.4 Caddy
See SETUP.md — install, base Caddyfile, verify routing.

### 1.5 Core Dependencies
See SETUP.md — Python, Git, Node.js, npm.

**Phase 1 complete when:** You can open a browser on your phone, navigate to your Tailscale URL, and see a Caddy default page.

---

## PHASE 2 — OLLAMA & MODEL BACKEND

**Goal:** Models are running and queryable. Foundation for every agent.
**Dependencies:** Phase 1 complete.

### 2.1 Ollama Installation and Configuration

**Claude Code prompt:**
```
Read ARCHITECTURE.md, STACK.md, and BUILD_SEQUENCE.md.

Task: Set up Ollama on the mini PC.

Create the following:
1. A shell script at /opt/platform/scripts/install-ollama.sh that:
   - Installs Ollama via the official install script
   - Sets the required environment variables (OLLAMA_HOST, OLLAMA_MAX_LOADED_MODELS, OLLAMA_NUM_PARALLEL) in /etc/systemd/system/ollama.service.d/override.conf
   - Reloads and restarts the Ollama systemd service
   - Verifies Ollama is running by hitting http://localhost:11434

2. A shell script at /opt/platform/scripts/download-models.sh that:
   - Downloads qwen2.5:14b
   - Downloads qwen2.5-coder:32b
   - Downloads qwen2.5:72b-instruct-q4_K_M
   - Reports download progress and confirms each model is available

3. A Python test script at /opt/platform/scripts/test-ollama.py that:
   - Sends a short test prompt to each downloaded model
   - Reports response time per model
   - Confirms all three models are working

Use the Ollama API patterns from STACK.md.
```

### 2.2 Ollama Admin Panel Integration (Basic)

**Note:** Full admin panel comes in Phase 5. This is a minimal standalone page to verify model management works before the admin panel exists.

**Claude Code prompt:**
```
Read ARCHITECTURE.md, STACK.md, and BUILD_SEQUENCE.md.

Task: Create a minimal Ollama status page — a temporary tool, not the final admin panel.

Create a FastAPI service at /opt/platform/ollama-status/ on port 8099 that:
1. GET /models — returns list of downloaded models from Ollama API
2. GET /running — returns currently loaded models
3. GET /health — returns Ollama status

Create a single React page (no routing needed) that:
- Lists all downloaded models with size and last modified
- Shows which models are currently loaded in memory
- Shows Ollama health status
- Has a button to unload all models (free memory)
- Auto-refreshes every 10 seconds

Register this at /ollama in Caddy as a temporary route.
Create the systemd service file following STACK.md patterns.

This page will be removed when the admin panel is built in Phase 5.
```

**Phase 2 complete when:** You can see all three models listed on the Ollama status page from your phone.

---

## PHASE 3 — PLATFORM VALIDATION

**Goal:** Prove the full stack works end to end before building complexity. Get a real usable app running.
**Dependencies:** Phase 2 complete.

### 3.1 Chat App Backend

**Claude Code prompt:**
```
Read ARCHITECTURE.md, STACK.md, and BUILD_SEQUENCE.md.

Task: Build the Chat app backend service.

Create a FastAPI service at /opt/platform/chat/ on port 8010 with:

1. POST /chat — accepts {message: string, model: string, history: array} returns streaming response from Ollama
2. GET /models — returns available models from Ollama (proxy to Ollama API)
3. GET /health — service health check

Requirements:
- Support streaming responses (Server-Sent Events)
- Maintain no server-side session state — history is passed in by the client each request
- Model selection per request — default to qwen2.5:14b if not specified
- Proper CORS headers for React frontend
- Error handling — if Ollama is unavailable, return a clear error

Create requirements.txt, main.py, and systemd service file following STACK.md patterns.
Register on port 8010.
```

### 3.2 Chat App Frontend

**Claude Code prompt:**
```
Read ARCHITECTURE.md, STACK.md, and BUILD_SEQUENCE.md.

Task: Build the Chat app frontend.

Create a React app at /opt/platform/frontend/chat/ using Vite that:

1. Chat interface:
   - Message input with send button (Enter to send)
   - Message history displayed in chat bubble style
   - Streaming response — text appears as it arrives (SSE)
   - Clear conversation button

2. Model selector:
   - Dropdown populated from GET /models
   - Selected model persists in localStorage
   - Shows currently selected model

3. Design requirements:
   - Clean, minimal design
   - Mobile-responsive — works well at 390px width
   - Dark mode preferred
   - No unnecessary UI elements — this is a tool, not a product

4. Technical requirements:
   - Use axios for HTTP, standard EventSource for SSE streaming
   - No authentication (handled at Tailscale level)
   - Build output goes to dist/

Configure Caddy to serve the built frontend at /chat and proxy API calls to /chat/api/* → localhost:8010.
```

### 3.3 End-to-End Validation

**Claude Code prompt:**
```
Read ARCHITECTURE.md, STACK.md, and BUILD_SEQUENCE.md.

Task: Create a platform validation script.

Create a Python script at /opt/platform/scripts/validate-platform.py that checks:

1. Tailscale — is the service running
2. Caddy — is it responding on port 80
3. Ollama — is it running, are all three models available
4. Chat backend — is port 8010 responding, does /health return OK
5. Chat frontend — is it being served at /chat
6. End-to-end — send a test message through the chat API, verify response

Print a clear pass/fail for each check with a summary at the end.
This script should be runnable at any time to verify platform health.
```

**Phase 3 complete when:** You can have a conversation with the chat app from your phone via Tailscale, with model selection working.

---

## PHASE 4 — TOOL LIBRARY

**Goal:** Reusable agent tools built, tested, and available as importable Python modules.
**Dependencies:** Phase 3 complete.

### 4.1 Tool Library Structure

**Claude Code prompt:**
```
Read ARCHITECTURE.md, STACK.md, and BUILD_SEQUENCE.md.

Task: Create the tool library base structure.

Create /opt/platform/tools/ as a Python package with:

1. Base tool interface at /opt/platform/tools/base.py:
   - Abstract base class Tool with: name, description, execute(params) -> ToolResult
   - ToolResult dataclass: success: bool, output: str, error: str | None, metadata: dict
   - All tools must implement this interface

2. Tool registry at /opt/platform/tools/registry.py:
   - ToolRegistry class that loads and manages available tools
   - register(tool: Tool) method
   - get(name: str) -> Tool method
   - list() -> list[ToolInfo] method

3. /opt/platform/tools/__init__.py that exports the registry and base classes

No individual tools yet — just the foundation.
Write unit tests for the base structure in /opt/platform/tools/tests/.
```

### 4.2 Filesystem Tool

**Claude Code prompt:**
```
Read ARCHITECTURE.md, STACK.md, and BUILD_SEQUENCE.md.

Task: Build the filesystem tool.

Create /opt/platform/tools/filesystem.py implementing the Tool base class with these operations:

- read_file(path) — read file contents, enforces path is within allowed_root
- write_file(path, content) — write file, creates directories if needed
- list_directory(path) — list files and folders
- create_directory(path) — create directory
- delete_file(path) — delete a single file (not directories)
- file_exists(path) — check if path exists
- get_file_info(path) — size, modified date, type

Security requirements:
- Every operation validates path is within the configured allowed_root
- Path traversal attacks (../) must be rejected
- allowed_root is set per agent at instantiation time — never global
- Symlinks outside allowed_root must be rejected

Write unit tests covering both normal usage and security boundary cases.
```

### 4.3 Terminal Tool

**Claude Code prompt:**
```
Read ARCHITECTURE.md, STACK.md, and BUILD_SEQUENCE.md.

Task: Build the terminal tool.

Create /opt/platform/tools/terminal.py implementing the Tool base class:

- execute_command(command, working_directory) — run a shell command
- Returns: stdout, stderr, exit_code, execution_time

Security requirements:
- working_directory must be within configured allowed_root (same pattern as filesystem tool)
- Blocked commands list: rm -rf /, sudo, su, chmod 777, wget, curl (agents use web tool instead), ssh
- Command timeout: 60 seconds hard limit, configurable per instantiation
- No interactive commands — stdin is always /dev/null
- Environment variables are minimal and controlled — no inheriting sensitive env vars

Output requirements:
- Truncate stdout/stderr to 50,000 characters if longer, append truncation notice
- Always return structured ToolResult even on failure

Write unit tests including timeout behavior and blocked command rejection.
```

### 4.4 Git Tool

**Claude Code prompt:**
```
Read ARCHITECTURE.md, STACK.md, and BUILD_SEQUENCE.md.

Task: Build the Git tool.

Create /opt/platform/tools/git_tool.py implementing the Tool base class:

Operations:
- init(repo_path) — initialize new git repo
- status(repo_path) — working tree status
- add(repo_path, paths=["."] ) — stage files
- commit(repo_path, message) — commit staged files
- diff(repo_path, staged=False) — show diff
- log(repo_path, limit=10) — commit history
- branch_list(repo_path) — list branches
- branch_create(repo_path, name) — create branch
- branch_checkout(repo_path, name) — checkout branch

Requirements:
- All operations scoped to repo_path — no global git config changes
- Commit author always set to "Platform Conductor <conductor@platform.local>"
- Uses subprocess following STACK.md Git patterns
- Returns structured output — not raw git text
- Log returns list of {hash, message, timestamp, author} dicts

Write unit tests using a temporary directory as repo.
```

### 4.5 GitHub Tool

**Claude Code prompt:**
```
Read ARCHITECTURE.md, STACK.md, and BUILD_SEQUENCE.md.

Task: Build the GitHub tool.

Create /opt/platform/tools/github_tool.py implementing the Tool base class:

Operations:
- list_repos(username) — list user's repositories
- clone_repo(repo_url, destination_path) — clone to local path
- push(repo_path, remote="origin", branch="main") — push commits
- create_pr(repo, title, body, head_branch, base_branch="main") — create pull request
- list_issues(repo) — list open issues
- get_repo_info(repo) — metadata, description, default branch

Authentication:
- Personal Access Token stored in platform SQLite config table (never hardcoded)
- Token loaded at instantiation from config
- Token never logged or included in ToolResult output

Requirements:
- Use PyGithub library
- All operations return structured ToolResult
- Graceful error handling — expired token, repo not found, no permissions

Write unit tests using mocked PyGithub responses.
```

### 4.6 Web Tool

**Claude Code prompt:**
```
Read ARCHITECTURE.md, STACK.md, and BUILD_SEQUENCE.md.

Task: Build the web tool.

Create /opt/platform/tools/web_tool.py implementing the Tool base class:

Operations:
- search(query) — search the web, return list of {title, url, snippet}
- fetch_page(url) — fetch and extract readable text content from a URL

Requirements:
- Read-only enforced — block all non-GET HTTP methods via Playwright route interception
- Timeout: 30 seconds per request
- Block known tracking/analytics domains
- Extract clean text from pages — strip navigation, ads, boilerplate
- Use DuckDuckGo for search (no API key needed): https://html.duckduckgo.com/html/?q={query}

Logging requirements (mandatory):
- Before any request: log to SQLite internet_log table {timestamp, agent_name, action, url, session_id}
- After response: update log entry with {results_summary, used_in_output: false}
- The Conductor updates used_in_output=true when it confirms the result was used
- ToolResult metadata must include log_entry_id

Write unit tests using Playwright's mock routes.
```

### 4.7 Test Runner Tool

**Claude Code prompt:**
```
Read ARCHITECTURE.md, STACK.md, and BUILD_SEQUENCE.md.

Task: Build the test runner tool.

Create /opt/platform/tools/test_runner.py implementing the Tool base class:

Operations:
- run_tests(project_path, test_command=None) — execute test suite
  - Auto-detects test framework if test_command not provided (pytest, jest, mocha)
  - Returns structured results
- run_single_test(project_path, test_identifier) — run one specific test
- get_coverage(project_path) — return coverage report if available

Return structure:
- total: int — total tests found
- passed: int
- failed: int
- errors: int
- skipped: int
- failures: list of {test_name, error_message, file, line}
- coverage: float | None — percentage if available
- execution_time: float — seconds
- raw_output: str — truncated to 10,000 chars

Requirements:
- Uses terminal tool internally for execution — inherits its security boundaries
- Timeout: 5 minutes hard limit
- Returns structured ToolResult even if all tests fail — failure is data, not an error

Write unit tests using minimal pytest and jest projects as fixtures.
```

### 4.8 Code Interpreter Tool

**Claude Code prompt:**
```
Read ARCHITECTURE.md, STACK.md, and BUILD_SEQUENCE.md.

Task: Build the code interpreter tool.

Create /opt/platform/tools/code_interpreter.py implementing the Tool base class:

Operations:
- run_python(code, working_directory) — execute Python code snippet
- run_javascript(code, working_directory) — execute Node.js code snippet
- validate_syntax(code, language) — check syntax without executing

Requirements:
- Executes in isolated subprocess — not eval() or exec()
- working_directory must be within allowed_root
- Timeout: 30 seconds
- Capture stdout, stderr, exit code
- Block imports of: os.system, subprocess (within executed code), socket
- Return structured ToolResult with output and any errors

Write unit tests covering normal execution, timeout, and blocked imports.
```

**Phase 4 complete when:** All tools have passing unit tests and are importable from the tool registry.

---

## PHASE 5 — ADMIN PANEL

**Goal:** Full platform management UI. Central control for everything built so far and everything to come.
**Dependencies:** Phase 4 complete.

### 5.1 Admin Panel Backend

**Claude Code prompt:**
```
Read ARCHITECTURE.md, STACK.md, and BUILD_SEQUENCE.md.

Task: Build the admin panel backend service.

Create a FastAPI service at /opt/platform/admin/ on port 8000.

Initialize the SQLite database at /opt/platform/data/platform.db with these tables:

apps:
- id, name, description, route, port, backend_port, status, created_at

agents:
- id, name, description, model, tools (JSON array), memory_scope, ui_route, system_prompt, created_at

config:
- key, value, updated_at (for GitHub token, etc.)

internet_log:
- id, session_id, agent_name, action, url, results_summary, used_in_output, timestamp

API endpoints:

System:
- GET /health
- GET /stats — CPU, GPU, memory, temperature (use psutil + rocm-smi)

Apps:
- GET /apps — list all registered apps
- POST /apps — register new app (writes to SQLite + Caddyfile + reloads Caddy)
- DELETE /apps/{id} — remove app (removes from SQLite + Caddyfile + reloads Caddy)
- POST /apps/{id}/restart — restart app's systemd service

Ollama:
- GET /ollama/models — list downloaded models
- GET /ollama/running — currently loaded models
- POST /ollama/pull — download a model (streaming progress)
- DELETE /ollama/models/{name} — delete a model
- POST /ollama/unload — unload all models from memory

Tailscale:
- GET /tailscale/status — network status and connected devices

OS:
- GET /updates/available — check for pending updates
- POST /updates/apply — apply updates (blocked if active autocoder session)

Create requirements.txt and systemd service file.
Remove the temporary Ollama status page from Phase 2.2 — this replaces it.
```

### 5.2 Admin Panel Frontend

**Claude Code prompt:**
```
Read ARCHITECTURE.md, STACK.md, and BUILD_SEQUENCE.md.

Task: Build the admin panel frontend.

Create a React app at /opt/platform/frontend/admin/ with these sections:

Navigation: sidebar with icons — Dashboard, Apps, Models, Agents, Network, Updates

Dashboard view:
- System stats cards: CPU%, GPU%, Memory used/total, Temperature
- Service health: list of all registered services with status indicator (green/red)
- Quick restart button per service
- Auto-refreshes every 15 seconds

Apps view:
- List of registered apps with name, route, port, status
- Register new app form: name, description, route, backend port
- Remove app button with confirmation
- Restart service button per app

Models view (replaces Phase 2.2 temporary page):
- List downloaded models: name, size, last used
- Currently loaded models with memory usage
- Search and download new model by name
- Delete model button with confirmation
- Unload all models button

Agents view (placeholder for Phase 6 — shows empty state for now):
- "No agents configured yet" message
- Will be built out in Phase 6

Network view:
- Tailscale status: connected/disconnected
- Device list from Tailscale
- Link to Tailscale admin console

Updates view:
- Current Ubuntu version
- Pending updates list
- Apply updates button (disabled with tooltip if autocoder session is active)
- Last updated timestamp

Design requirements:
- Clean, dark theme
- Mobile-responsive — collapsible sidebar on mobile
- No unnecessary decoration
```

### 5.3 Agent Creator

**Claude Code prompt:**
```
Read ARCHITECTURE.md, STACK.md, and BUILD_SEQUENCE.md.

Task: Build the agent creator backend and UI.

Backend additions to /opt/platform/admin/main.py:

Agents API:
- GET /agents — list all configured agents
- POST /agents — create new agent
- PUT /agents/{id} — update agent configuration
- DELETE /agents/{id} — remove agent
- POST /agents/{id}/deploy — create and start systemd service for agent
- POST /agents/{id}/stop — stop agent service

POST /agents body:
{
  name: string,
  description: string,
  model: string,                    // must be in available Ollama models
  tools: string[],                  // tool names from tool library
  memory_scope: "session" | "project" | "global",
  system_prompt: string,
  ui_type: "chat" | "dashboard" | "none",
  ui_route: string | null           // e.g. "/coding"
}

On deploy:
1. Create FastAPI service file from template
2. Create systemd service file from template
3. If ui_type is "chat": create minimal React chat UI from template, build it, register route in Caddy
4. Register in apps table

Frontend additions to admin panel — Agents view:
- List configured agents with status
- Create agent form with all fields
- System prompt textarea with syntax highlighting
- Tool multi-select from available tool library tools
- Model dropdown from available Ollama models
- Memory scope selector
- Deploy/Stop buttons per agent
- Edit agent configuration
```

**Phase 5 complete when:** Admin panel is accessible, all services visible, models manageable, and you can create a basic agent through the UI.

---

## PHASE 6 — PERSONAL CODING ASSISTANT

**Goal:** First real agent built using the agent creator. Validates the full agent pipeline before building autocoder complexity.
**Dependencies:** Phase 5 complete.

### 6.1 Coding Assistant Agent

**Claude Code prompt:**
```
Read ARCHITECTURE.md, STACK.md, and BUILD_SEQUENCE.md.

Task: Build the personal coding assistant agent.

This is a single conversational coding agent — not part of the autocoder multi-agent system.
Think: Claude Code, but running locally on the platform.

Create the agent service at /opt/platform/coding/ on port 8012.

Agent configuration:
- Model: qwen2.5-coder:32b
- Tools: filesystem (scoped to user project folders), terminal, git_tool, github_tool, web_tool
- Memory scope: project
- System prompt: see below

System prompt:
"You are a coding assistant. You have access to the user's project files, terminal, Git, and GitHub.
When given a task:
1. Understand the existing codebase before making changes
2. Make targeted, minimal changes — do not rewrite what works
3. Always run tests after making changes if a test suite exists
4. Commit working changes with clear commit messages
5. Explain what you did and why after completing a task
Ask clarifying questions before starting if requirements are ambiguous."

GitHub integration:
- On first use, prompt for GitHub Personal Access Token — store in config table
- Allow user to specify which repos and local project folders are accessible
- Project folders stored in SQLite per user: user_projects table {id, name, local_path, github_repo, created_at}

Frontend (built via agent creator UI template, customized):
- Chat interface (same pattern as chat app)
- File tree panel showing current project structure
- Active project selector — switch between configured projects
- Git status panel — current branch, staged/unstaged changes, recent commits
- GitHub quick actions — push, create PR

Register at /coding in Caddy.
```

**Phase 6 complete when:** You can open /coding, select a GitHub repo, ask it to make a code change, and see it committed and pushed.

---

## PHASE 7 — MEMORY INFRASTRUCTURE

**Goal:** All three memory layers operational and tested before autocoder agents use them.
**Dependencies:** Phase 6 complete (validates SQLite is working correctly).

### 7.1 Memory Service

**Claude Code prompt:**
```
Read ARCHITECTURE.md, STACK.md, and BUILD_SEQUENCE.md.

Task: Build the memory service — a shared internal service all agents call.

Create /opt/platform/memory/ as an importable Python package (not a web service — imported directly).

Session memory (SQLite):
- create_session(project_id, description) -> session_id
- log_event(session_id, agent, event_type, content, metadata={}) -> event_id
  - event_type: "task_start" | "task_complete" | "failure" | "replan" | "commit" | "internet_access" | "parked"
- get_session_log(session_id) -> list[Event]
- close_session(session_id, outcome: "success" | "parked" | "failed")

Project memory (SQLite):
- get_project(project_id) -> Project | None
- create_project(name, description) -> project_id
- save_decision(project_id, decision_type, content, rationale) -> decision_id
- get_decisions(project_id, decision_type=None) -> list[Decision]
- save_open_issue(project_id, description) -> issue_id
- resolve_issue(issue_id, resolution)
- get_open_issues(project_id) -> list[Issue]

Cross-run memory (ChromaDB):
- store_preference(content, metadata={}) — user preferences and patterns
- store_resolution(failure_type, resolution, metadata={}) — how failures were resolved
- query(text, n_results=5) -> list[MemoryResult] — semantic search
- query_preferences(context, n_results=3) -> list[MemoryResult]

Write unit tests for all three layers.
The memory package must be importable by any platform service.
Install path: /opt/platform/memory/ added to PYTHONPATH.
```

**Phase 7 complete when:** All memory operations pass unit tests and are importable from other services.

---

## PHASE 8 — AUTOCODER FOUNDATION

**Goal:** Conductor and dashboard operational. The orchestration layer exists before specialist agents.
**Dependencies:** Phase 7 complete.

### 8.1 Autocoder Dashboard Backend

**Claude Code prompt:**
```
Read ARCHITECTURE.md, STACK.md, and BUILD_SEQUENCE.md.

Task: Build the autocoder dashboard backend.

Create a FastAPI service at /opt/platform/autocoder/dashboard/ on port 8050.

API endpoints:

Sessions:
- GET /sessions — list recent sessions with status
- GET /sessions/{id} — full session detail
- GET /sessions/{id}/log — timestamped event log
- GET /sessions/{id}/internet — internet access log entries
- GET /sessions/{id}/internet/{entry_id} — drill-down detail for one entry

Projects:
- GET /projects — list all projects
- GET /projects/{id} — project detail with memory, decisions, open issues
- GET /projects/{id}/sessions — sessions for this project

Agents:
- GET /agents/status — current status of all autocoder agents
  Returns: list of {agent_name, status, current_task, last_active}
  Status values: "idle" | "active" | "completed" | "failed" | "parked"

WebSocket:
- WS /ws/session/{id} — real-time session events
  Pushes events as they are logged to session memory
  Used by dashboard to update agent board without polling

Git:
- GET /projects/{id}/commits — recent commits for project repo
- GET /projects/{id}/commits/{hash}/diff — diff for specific commit
```

### 8.2 Autocoder Dashboard Frontend

**Claude Code prompt:**
```
Read ARCHITECTURE.md, STACK.md, and BUILD_SEQUENCE.md.

Task: Build the autocoder dashboard frontend.

Create a React app at /opt/platform/frontend/autocoder/.

Views: Agent Board (default), Session Log, Morning Review, Project History

Agent Board view:
- Grid of agent cards — one per autocoder specialist plus Conductor and RE-agent
- Each card shows: agent name, current status, current task (truncated to one line)
- Color schema strictly as defined:
  ⚪ Idle — grey
  🔵 Active — blue, subtle pulse animation
  ✅ Completed — green
  🔴 Failed — red
  🟡 Parked — amber
- Cards for agents that have contributed to the current project are always visible
- Cards for agents not yet used in this project are shown as inactive/greyed
- Updates in real-time via WebSocket connection

Session Log view:
- Timestamped list of Conductor-level events
- Normal events: white text
- Failed events: red text with icon
- Parked events: amber text with icon, expandable to show Conductor explanation
- Internet access entries: grey with expand to show detail
- Infinite scroll — loads older events on demand

Morning Review view:
- Summary card: what was built, duration, outcome
- Per-agent section: what each agent did, files changed
- Git commits list with diff expandable per commit
- Test results summary
- Open issues list — things the Conductor flagged but could not resolve
- Parked explanation if session was parked

Project History view:
- List of all sessions for selected project
- Each session: date, duration, outcome, summary
- Click to open that session's Morning Review

Mobile requirements:
- Agent board stacks to single column on mobile
- Session log readable on mobile
- Morning review readable on mobile
```

### 8.3 Conductor Service

**Claude Code prompt:**
```
Read ARCHITECTURE.md, STACK.md, and BUILD_SEQUENCE.md.

Task: Build the Conductor service.

Create a FastAPI + LangGraph service at /opt/platform/autocoder/conductor/ on port 8001.

The Conductor is the orchestrator of the autocoder pipeline. It does not write code.

API endpoints:
- POST /session/start — start a new autocoder session
  Body: {project_id, requirements_document: string}
  Returns: session_id
- GET /session/{id}/status — current pipeline status
- POST /session/{id}/pause — pause a running session
- POST /session/{id}/resume — resume a paused session

LangGraph pipeline nodes:

1. validate_requirements(state):
   - Checks requirements document for completeness
   - Required sections: objective, scope, constraints, acceptance criteria, tech context
   - If incomplete: logs event, returns error — session does not start
   - If complete: proceeds to plan_pipeline

2. plan_pipeline(state):
   - Uses 70B model to analyse requirements
   - Decides which specialist agents are needed
   - Determines dependency order (e.g. DB before Backend before Frontend)
   - Selects model per agent based on task characteristics (see ARCHITECTURE.md)
   - Generates instruction set for each agent using that agent's template
   - Logs plan to session memory

3. execute_agent(state):
   - Sends task to specialist agent via HTTP POST
   - Waits for completion (polls /status endpoint)
   - Receives structured output

4. review_output(state):
   - Uses 70B model to evaluate specialist output against quality rubric
   - Quality rubric is loaded from agent's configuration
   - Decision: accept | reject
   - If accept: trigger git_commit, log event, move to next agent
   - If reject: classify_failure

5. classify_failure(state):
   - Uses 70B model to classify why output was rejected
   - Classification: solvable | scope | architectural | capability
   - Routes to appropriate handler

6. handle_failure(state):
   - solvable: refine instructions, retry same agent
   - scope: expand instructions, retry same agent
   - architectural: replan from plan_pipeline with updated context
   - capability: swap to larger model, retry
   - Logs all decisions and rationale to session memory

7. git_commit(state):
   - Uses git_tool to stage and commit all changes
   - Conductor writes commit message summarising what was built
   - Logs commit hash to session memory

8. park_session(state):
   - Called when failure cannot be resolved
   - Logs full explanation of what was attempted and why it failed
   - Updates session status to "parked"
   - Sends WebSocket event to dashboard

All state changes must:
- Log to session memory via memory service
- Push WebSocket event to dashboard backend
- Update agent status in dashboard

Use the memory service from Phase 7.
Use the git_tool from Phase 4.
```

**Phase 8 complete when:** Conductor can start a session, validate requirements, and log events visible on the dashboard in real-time.

---

## PHASE 9 — AUTOCODER SPECIALIST AGENTS

**Goal:** Specialist agents built, tested individually, then connected to Conductor.
**Dependencies:** Phase 8 complete.

### 9.1 RE-agent

**Claude Code prompt:**
```
Read ARCHITECTURE.md, STACK.md, and BUILD_SEQUENCE.md.

Task: Build the RE-agent (Requirements Elicitation agent).

Create a FastAPI service at /opt/platform/autocoder/re-agent/ on port 8002.

The RE-agent is a conversational agent the user talks to before a pipeline run.
It does not write code. Its output is a structured requirements document.

API endpoints:
- POST /session/start — start a new RE-agent conversation
  Body: {project_id} — loads project memory if project exists
  Returns: session_id, greeting message
- POST /session/{id}/message — send user message, get agent response
  Body: {message: string}
  Returns: {response: string, is_complete: bool, requirements_document: object | null}
- GET /session/{id}/requirements — get current draft requirements document
- POST /session/{id}/finalise — mark requirements as complete, return final document

Model: qwen2.5:14b

System prompt:
"You are a requirements analyst. Your job is to fully understand what the user wants to build
before handing off to a development pipeline.

Your conversation should:
1. Understand the core problem being solved
2. Define scope clearly — what is included and what is not
3. Surface and resolve ambiguities — never let the user be vague if it matters
4. Define acceptance criteria — how will we know it is done
5. Understand technical constraints — existing codebase, preferred stack, integrations needed
6. Read back your understanding and get explicit confirmation before finalising

You are the quality gate. The pipeline cannot start until you are satisfied the requirements
are complete enough for autonomous execution. Be thorough. Ask uncomfortable questions.
A missed requirement discovered overnight costs hours."

On each turn, maintain a draft requirements document with sections:
- objective: string
- scope: {included: string[], excluded: string[]}
- constraints: string[]
- acceptance_criteria: string[]
- tech_context: string
- open_questions: string[] (cleared as you resolve them)

is_complete returns true only when:
- All sections are filled
- open_questions is empty
- User has explicitly confirmed the requirements are correct

Reads from project memory and cross-run memory at session start.
```

### 9.2 Backend Specialist Agent

**Claude Code prompt:**
```
Read ARCHITECTURE.md, STACK.md, and BUILD_SEQUENCE.md.

Task: Build the Backend specialist agent.

Create a FastAPI service at /opt/platform/autocoder/specialists/backend/ on port 8003.

API endpoints:
- POST /task — receive task from Conductor, begin execution
  Body: {session_id, project_path, instructions: string, context: object}
  Returns: {task_id}
- GET /task/{id}/status — poll for completion
  Returns: {status: "running"|"complete"|"failed", output: object | null}

Model: qwen2.5-coder:32b

Available tools: filesystem (scoped to project_path), terminal, git_tool (read-only — commits done by Conductor), test_runner, web_tool, code_interpreter

Instruction template (Conductor fills this per task):
"Project context: {context}
Task: {specific_task}
Constraints: {constraints}
Acceptance criteria: {acceptance_criteria}
Existing code to be aware of: {relevant_existing_code}
Do not modify: {locked_files}"

Quality rubric (Conductor uses this to review output):
- Does the code run without errors?
- Does it match the specified API contracts?
- Are there unit tests for new functionality?
- Is error handling present for external calls?
- Does it match the tech context from requirements?

Output structure returned to Conductor:
{
  files_created: string[],
  files_modified: string[],
  tests_passed: bool,
  test_summary: object,
  implementation_notes: string,
  concerns: string[]  // things the agent flagged but proceeded with
}
```

### 9.3 Tester Specialist Agent

**Claude Code prompt:**
```
Read ARCHITECTURE.md, STACK.md, and BUILD_SEQUENCE.md.

Task: Build the Tester specialist agent.

Create a FastAPI service at /opt/platform/autocoder/specialists/tester/ on port 8006.

Same API pattern as Backend specialist (POST /task, GET /task/{id}/status).

Model: qwen2.5-coder:32b

Available tools: filesystem (read + write, scoped to project_path), terminal, test_runner, code_interpreter

Responsibilities:
- Write tests for code produced by other specialists
- Execute existing tests and report results
- Identify untested edge cases
- Report failures with enough detail for Conductor to classify

Quality rubric (Conductor uses this to review output):
- Do all tests pass?
- Is coverage above 70% for new code?
- Are edge cases tested (empty input, null values, error states)?
- Are tests independent — do they rely on each other's state?

Output structure:
{
  tests_written: string[],
  test_results: object,   // from test_runner tool
  coverage: float | null,
  failing_tests: list,
  untested_areas: string[],
  recommendations: string[]
}
```

### 9.4 Remaining Specialists

**Claude Code prompt:**
```
Read ARCHITECTURE.md, STACK.md, and BUILD_SEQUENCE.md.

Task: Build the remaining three specialist agents following the exact same pattern
as the Backend and Tester agents above.

DB Specialist (port 8005):
- Responsibilities: schema design, migrations, seed data, query optimisation
- Tools: filesystem, terminal, code_interpreter
- Quality rubric: schema consistent with requirements, migrations are reversible,
  no raw SQL injection risks, indexes on foreign keys

Frontend Specialist (port 8004):
- Responsibilities: React components, API integration, mobile-responsive UI
- Tools: filesystem, terminal, test_runner, web_tool (for referencing docs)
- Quality rubric: components render without errors, API calls match backend contracts,
  responsive at 390px, no hardcoded values that should be config

Refactorer Specialist (port 8007):
- Responsibilities: code quality, consistency, removing duplication, performance
- Tools: filesystem (read + write), terminal, test_runner
- Quality rubric: all existing tests still pass after refactor, no new functionality
  added (scope: quality only), consistent style throughout

All three follow identical API pattern: POST /task, GET /task/{id}/status.
All use qwen2.5-coder:32b.
All return the standard output structure with files_created, files_modified,
tests_passed, test_summary, implementation_notes, concerns.
```

### 9.5 Full Pipeline Integration

**Claude Code prompt:**
```
Read ARCHITECTURE.md, STACK.md, and BUILD_SEQUENCE.md.

Task: Wire the full autocoder pipeline together and run an end-to-end test.

1. Verify all specialist agents are registered in the Conductor's agent registry
2. Verify the Conductor can reach all specialist endpoints
3. Verify the RE-agent output format matches what the Conductor expects as input
4. Verify the dashboard receives real-time events during a pipeline run

Create an integration test at /opt/platform/scripts/test-autocoder-pipeline.py that:
- Creates a test project
- Submits a minimal but real requirements document directly to the Conductor
  (bypassing RE-agent — this is an integration test, not an end-to-end test)
- Verifies the Conductor plans and executes at least one specialist agent
- Verifies session events appear in the dashboard API
- Verifies a Git commit is created after agent completion
- Reports pass/fail for each step

The test project should be: "Create a Python FastAPI endpoint GET /ping that returns
{status: ok, timestamp: ISO8601}. Include a pytest test."
This is simple enough to complete reliably but real enough to test the full pipeline.
```

**Phase 9 complete when:** Integration test passes end-to-end including Git commit and dashboard events.

---

## PHASE 10 — WRITER APP

**Goal:** Second independent app on the platform. Simpler build — validates app registration pattern.
**Dependencies:** Phase 5 complete (can be built in parallel with Phases 6-9).

### 10.1 Writer App

**Claude Code prompt:**
```
Read ARCHITECTURE.md, STACK.md, and BUILD_SEQUENCE.md.

Task: Build the Writer app — a long-form writing assistant.

Create a FastAPI service at /opt/platform/writer/ on port 8011.

API endpoints:
- POST /write — streaming response for writing tasks
  Body: {prompt, context, model, document_so_far}
- POST /continue — continue writing from where the document left off
- POST /edit — targeted edit of a selection
  Body: {selection, instruction, full_document}
- POST /suggest — suggest improvements without applying them

Model: qwen2.5:72b-instruct-q4_K_M (long-form benefits from larger model)

Frontend at /opt/platform/frontend/writer/:
- Clean document editor — full-width text area, minimal chrome
- Document persists in localStorage between sessions (simple, no backend storage)
- Sidebar with writing tools:
  - Continue writing
  - Improve selected text
  - Suggest edits
  - Change tone (formal / casual / academic)
  - Summarise
- Word count
- Export as plain text or markdown
- Model selector (some users may prefer faster smaller model)

Design: extremely minimal — the writing surface should dominate.
Think: iA Writer aesthetic. Nothing competes with the text.

Register at /writer in Caddy.
Create systemd service file.
```

**Phase 10 complete when:** You can write and export a long-form document from your phone.

---

## PHASE 11 — HARDENING

**Goal:** Production-grade reliability for overnight unsupervised runs.
**Dependencies:** Phase 9 complete.

### 11.1 Service Recovery

**Claude Code prompt:**
```
Read ARCHITECTURE.md, STACK.md, and BUILD_SEQUENCE.md.

Task: Implement service recovery and health monitoring.

1. Health check endpoint on every service — standardise /health response:
   {status: "ok"|"degraded"|"down", version: string, uptime_seconds: int, dependencies: object}

2. Platform health monitor at /opt/platform/scripts/health-monitor.py:
   - Runs as systemd service
   - Polls all service /health endpoints every 30 seconds
   - If a service is down: attempts restart via systemctl
   - Logs all restarts to SQLite platform_events table
   - Sends WebSocket event to admin panel

3. Autocoder session recovery:
   - If Conductor service crashes mid-session: on restart, detect incomplete sessions
   - Log the crash event to session memory
   - Mark session as "parked" with explanation "Service restart during session"
   - Never attempt to auto-resume — always require morning review

4. Admin panel additions:
   - Platform events log — shows service restarts, crashes, recovery
   - Alert banner if any service is currently down
```

### 11.2 OS Update Management

**Claude Code prompt:**
```
Read ARCHITECTURE.md, STACK.md, and BUILD_SEQUENCE.md.

Task: Implement OS update management with session awareness.

1. Update checker service — runs daily, checks for pending apt updates:
   - Stores pending update list in SQLite
   - Exposes to admin panel via GET /updates/available

2. Update logic in admin panel POST /updates/apply:
   - Check if any autocoder session is currently active (status = "running")
   - If active session: return error "Cannot update during active session"
   - If no active session: run apt upgrade, log to platform_events, restart affected services

3. Admin panel Updates view improvements:
   - Show pending updates with package names and descriptions
   - Last updated timestamp
   - Apply button — disabled with clear tooltip if session is active
   - Update history log
```

### 11.3 Error Handling Audit

**Claude Code prompt:**
```
Read ARCHITECTURE.md, STACK.md, and BUILD_SEQUENCE.md.

Task: Audit and improve error handling across all services.

Review every service and ensure:

1. All FastAPI endpoints have try/except — no unhandled 500s reach the client
2. All Ollama calls handle: model not found, Ollama offline, timeout
3. All tool calls handle: permission errors, missing files, subprocess failures
4. All SQLite operations handle: database locked, disk full
5. All ChromaDB operations handle: service unavailable
6. The Conductor handles: specialist agent unreachable, specialist timeout

For each failure type, the correct behaviour is:
- Log the error with full context to session memory (if in a session)
- Return a structured error response (never a raw exception)
- Do not crash the service

Create a test suite at /opt/platform/scripts/test-error-handling.py that
deliberately triggers each failure type and verifies the system handles it gracefully.
```

**Phase 11 complete when:** Error handling test suite passes, a simulated service crash recovers automatically, and OS updates are blocked correctly during an active session.

---

## PHASE 12 — DOCUMENTATION

**Goal:** All documentation complete, accurate, and version-controlled.
**Dependencies:** Phase 11 complete.

### 12.1 Setup Manual

**Claude Code prompt:**
```
Read ARCHITECTURE.md, STACK.md, and BUILD_SEQUENCE.md.

Task: Write the ELI5 setup manual — SETUP.md.

This document is for someone with zero Linux experience setting up the mini PC for the first time.
Assume the reader knows how to use Windows but has never touched a terminal.

Structure:
1. What you need before you start (USB stick, ethernet cable, monitor, keyboard)
2. Creating a bootable Ubuntu USB stick (on Windows — use Rufus)
3. BIOS settings — with exact key to press on boot, what each setting means in plain English
4. Installing Ubuntu — every screen, every click, what to choose and why
5. First boot — what you'll see, what to do
6. Opening the terminal for the first time — where to find it, what it is, don't be scared
7. Running the platform setup script — one command that does everything
8. Verifying it worked — what to look for
9. Connecting from your phone — installing Tailscale on phone, accessing the platform
10. What to do if something goes wrong — common issues and fixes

Writing rules:
- No assumed knowledge
- Every terminal command on its own line, in a code block, with plain English explanation of what it does
- Screenshots described in text (we cannot include actual screenshots)
- Friendly, calm tone — this is not scary, here is exactly what to do
- When something might look alarming (terminal output, password not showing as you type), explain it

Also create /opt/platform/scripts/setup.sh — a single script that:
- Installs all platform dependencies (Tailscale, Caddy, Ollama, Python, Node, Git)
- Creates the directory structure from STACK.md
- Downloads initial models
- Sets up all systemd services
- Runs the platform validation script from Phase 3.3

The setup manual should reference this script at step 7 — one command, everything installs.
```

**Phase 12 complete when:** A person with zero Linux experience could follow SETUP.md and have the platform running.

---

## BUILD COMPLETE

At this point the platform is:
- Fully operational on the mini PC
- Remotely accessible from any device
- Running chat, writer, coding assistant, and autocoder apps
- Capable of autonomous overnight development runs
- Self-monitoring with recovery
- Documented end-to-end

---

## PHASE DEV — DEVELOPMENT TOOLING

**Goal:** Local testing on Windows 11, one-command deployment to mini PC, full validation suite.
**Dependencies:** Phase 3 complete (chat app proves the stack works).
**Prompts:** Three prompts in `docs/PHASE_DEV_TOOLING.md` — run in order:
- Prompt 1: Docker Compose local environment + Windows setup script
- Prompt 2: Deployment scripts (full deploy + selective deploy + first-time setup)
- Prompt 3: Test suite (health, models, memory, tools, pipeline, UI tests)

**Phase DEV complete when:** Full platform runs locally in Docker on Windows 11, deploys to mini PC in one command, and test suite passes on both targets.

---

## PHASE 13 — TRADING SYSTEM

**Goal:** Fully operational two-pool autonomous trading system with learning.
**Dependencies:** Phase 12 complete. IBKR paper trading account active.
**See:** `docs/TRADING_ARCHITECTURE.md` for full specification.
**Note:** Minimum 4 weeks paper trading validation before live. Live switch is manual.

Components (Claude Code prompts to be written before each component):

| Component | Description |
|---|---|
| 13.1  | Trading SQLite schema — all trading tables |
| 13.2  | IBKR tool — paper trading account, full order lifecycle |
| 13.3  | Crypto exchange tool — Coinbase sandbox |
| 13.4  | Reddit API tool + Pushshift historical data tool |
| 13.5  | SEC EDGAR tool |
| 13.6  | APScheduler integration into trading service |
| 13.7  | trading_monitor_stocks + trading_monitor_crypto |
| 13.8  | trading_wsb_dd + trading_wsb_mentions + correlation engine |
| 13.9  | Catalyst calendar + temporal state management |
| 13.10 | trading_validator_signal — conviction scoring |
| 13.11 | trading_validator_risk_gate — hard-coded, exhaustively tested |
| 13.12 | trading_execution_stocks + trading_execution_crypto |
| 13.13 | trading_position_manager — trailing stops, cost basis accounting |
| 13.14 | trading_auditor_compliance — independent service, force-exit logic |
| 13.15 | trading_learning_engine — shadow portfolio, retrospective analysis |
| 13.16 | Morning brief generation |
| 13.17 | Trading app frontend — dashboard, positions, signals, WSB, calendar, audit log, analytics, settings |
| 13.18 | Notification system — Web Push API |
| 13.19 | Paper trading validation — minimum 4 weeks, all components verified |
| 13.20 | Live trading activation — explicit manual decision by user required |

**Phase 13 complete when:** 4+ weeks paper trading with no critical failures, live switch confirmed by user.

---

## BUILD COMPLETE (post-Phase 12)

At this point the core platform is:
- Fully operational on the mini PC
- Remotely accessible from any device
- Running chat, writer, coding assistant, and autocoder apps
- Capable of autonomous overnight development runs
- Self-monitoring with recovery
- Documented end-to-end

**Remaining phases after 12:**
- Phase DEV — local dev environment and deployment tooling
- Phase 13 — Trading system
- Voice interface for RE-agent (future)
- Wake-on-LAN for always-on services (future)
- Additional apps via agent creator (ongoing)
