# PHASE_DEV_TOOLING.md
# Development Tooling Phase — Three Claude Code Prompts
# Run in order. Each prompt builds on the previous one.
# Goal: full platform runs locally on Windows 11, deploys in one command.

---

## CONTEXT

Development happens on a Windows 11 machine.
The platform runs on a Ubuntu mini PC (ms-s1).
This phase bridges that gap.

After Phase DEV:
- Full platform runs locally in Docker (Windows 11) for development
- One command deploys any service to the mini PC
- Test suite validates both local and remote environments

---

## PROMPT 1 — DOCKER COMPOSE LOCAL ENVIRONMENT

```
Read ARCHITECTURE.md, STACK.md, BUILD_SEQUENCE.md, and SETUP.md.

Task: Create a local Docker Compose environment that runs the full platform on Windows 11.

This is for development only — not for production deployment.
The mini PC still runs the platform in production.
This environment lets you develop and test without SSH-ing into the mini PC.

Create at /Jarvis/docker/:

1. docker-compose.yml — defines all services:
   - ollama: official ollama image, port 11434, GPU passthrough if available
   - chromadb: official chromadb image, port 8020, persistent volume
   - admin: builds from platform/admin/, port 8000
   - chat: builds from platform/chat/, port 8010
   - writer: builds from platform/writer/, port 8011
   - coding: builds from platform/coding/, port 8012
   - autocoder-dashboard: builds from platform/autocoder/dashboard/, port 8050
   - conductor: builds from platform/autocoder/conductor/, port 8001
   - re-agent: builds from platform/autocoder/re-agent/, port 8002
   All services share a network and a data volume at /opt/platform/data/

2. Dockerfile template — base Python 3.12 image pattern all services use:
   - FROM python:3.12-slim
   - WORKDIR /app
   - COPY requirements.txt .
   - RUN pip install -r requirements.txt
   - COPY . .
   - CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "${PORT}"]

3. Individual Dockerfiles for each service (at platform/<service>/Dockerfile)
   following the template above.

4. .env.docker file (never committed to Git) with:
   - DB_PATH=/opt/platform/data/platform.db
   - OLLAMA_URL=http://ollama:11434
   - CHROMADB_URL=http://chromadb:8020

5. docker/setup-windows.ps1 — PowerShell script for first-time Windows setup:
   - Checks Docker Desktop is installed
   - Checks WSL 2 is enabled
   - Creates the data directory
   - Pulls required Docker images
   - Runs docker compose up

6. docker/start.sh and docker/stop.sh for Linux/Mac users

Requirements:
- Services must resolve each other by container name (use Docker network)
- Data volume must persist between restarts
- PYTHONPATH must include /opt/platform so memory and tools packages resolve
- If GPU is not available (common on dev machine), Ollama falls back to CPU
- Ollama in Docker: use OLLAMA_HOST=0.0.0.0

Phase DEV Prompt 1 complete when: docker compose up starts all services,
admin panel is accessible at http://localhost:8000, and Ollama responds at http://localhost:11434.
```

---

## PROMPT 2 — DEPLOYMENT SCRIPTS

```
Read ARCHITECTURE.md, STACK.md, BUILD_SEQUENCE.md, and SETUP.md.

Task: Create deployment scripts for pushing code changes to the mini PC.

The workflow is:
  dev machine → Git push → SSH to ms-s1 → git pull → restart services

Create at /Jarvis/scripts/:

1. deploy.sh — full platform deploy:
   - Accepts optional service name argument: ./deploy.sh admin
   - If no argument: deploys all services
   - For each service:
     a. SSH to ubuntu@ms-s1
     b. cd /opt/platform
     c. git pull origin main
     d. cd to service directory
     e. source venv/bin/activate && pip install -r requirements.txt --quiet
     f. sudo systemctl restart platform-{service}
     g. Wait 5 seconds
     h. curl http://localhost:{port}/health and check status
   - Print clear PASS/FAIL for each service
   - At end: print summary of deployed services

2. deploy-frontend.sh — React frontend deploy:
   - Accepts app name argument: ./deploy-frontend.sh admin
   - On dev machine: cd frontend/{app} && npm run build
   - scp -r dist/ ubuntu@ms-s1:/opt/platform/frontend/{app}/dist/
   - sudo systemctl reload caddy
   - Verify app is serving at the expected URL

3. first-time-setup.sh — run once on a fresh mini PC after initial Ubuntu install:
   - Clones the repository to /opt/platform
   - Creates all virtual environments and installs dependencies
   - Sets up systemd services from the systemd/ directory
   - Creates the data directory at /opt/platform/data/
   - Runs the platform validation script
   - Prints clear instructions for next steps

4. rollback.sh — revert last deploy:
   - git stash or git reset --hard HEAD~1 on the mini PC
   - Restart affected services
   - Print WARN: requires knowing which commit to roll back to

Requirements:
- All scripts must work from the Windows dev machine using Git Bash
- SSH connection uses SSH key auth — no password prompting
- Scripts must handle service not found (typo in service name)
- Scripts must handle SSH connection failure with a clear error
- Use colors in terminal output: green for success, red for failure, yellow for warnings

Phase DEV Prompt 2 complete when: ./deploy.sh successfully pushes and restarts a service on the mini PC.
```

---

## PROMPT 3 — TEST SUITE

```
Read ARCHITECTURE.md, STACK.md, BUILD_SEQUENCE.md, and SETUP.md.

Task: Build a comprehensive test suite that validates the full platform.

The test suite must run against two targets:
  --target local   (Docker Compose on dev machine)
  --target remote  (mini PC at ms-s1 via Tailscale)

Create at /Jarvis/scripts/tests/:

1. test_health.py — health check tests:
   - Check every registered service returns {"status": "ok"} from /health
   - Check uptime_seconds is > 0
   - Check dependencies field is present (admin only)
   - Pass/fail per service

2. test_models.py — Ollama model tests:
   - Check all three required models are downloaded (qwen2.5:14b, qwen2.5-coder:32b, qwen2.5:72b-instruct-q4_K_M)
   - Send a short test prompt to each model, verify non-empty response
   - Report latency per model

3. test_memory.py — memory infrastructure tests:
   - Create a test session, log events, close session — verify via API
   - Create a test project, save decisions, retrieve them — verify
   - Store and query ChromaDB — verify semantic search works
   - Clean up test data after each test

4. test_tools.py — tool library tests:
   - Filesystem tool: create, read, write, delete a test file within allowed path
   - Terminal tool: run echo "hello" and verify output
   - Git tool: init a temp repo, make a commit, read log
   - Verify security: filesystem tool rejects path traversal attempt

5. test_pipeline.py — autocoder pipeline integration test:
   - Start a test session via POST /session/start on conductor
   - Submit the standard test requirements document (GET /ping endpoint)
   - Poll for session completion (timeout: 5 minutes)
   - Verify session events are logged in dashboard API
   - Verify at least one Git commit was created
   - Verify session closes with outcome: success or parked

6. test_ui.py — frontend smoke tests (using Playwright):
   - Visit each app URL via Tailscale (admin, chat, writer, coding, autocoder)
   - Check page title and key UI element present (no crash, no 404)
   - Check admin dashboard shows service list
   - Check chat app sends a message and receives a streaming response

7. run_tests.py — test runner:
   - Accepts --target local|remote
   - Accepts --suite health|models|memory|tools|pipeline|ui|all
   - Runs selected tests in order
   - Prints clear PASS/FAIL per test with timing
   - Prints summary: X/Y tests passed
   - Exit code 0 on all pass, 1 on any failure

Requirements:
- Tests must be runnable from Windows (use httpx, not curl)
- Tests must be idempotent — leave no permanent state behind
- Tests must have sensible timeouts — do not hang indefinitely
- Tests must not require a running autocoder session unless testing the pipeline
- Each test file must be independently runnable for quick local iteration

Phase DEV Prompt 3 complete when: run_tests.py --target local --suite health passes all services,
and run_tests.py --target remote --suite health passes when connected to the mini PC via Tailscale.
```
