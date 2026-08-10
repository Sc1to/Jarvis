#Requires -Version 7
# First-time Docker Compose setup for Windows 11 dev machine.
# Run from the docker/ directory: .\setup-windows.ps1

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-OK   { param($msg) Write-Host "[OK]  $msg" -ForegroundColor Green }
function Write-Fail { param($msg) Write-Host "[FAIL] $msg" -ForegroundColor Red }
function Write-Info { param($msg) Write-Host "[....] $msg" -ForegroundColor Cyan }

# ── Check prerequisites ───────────────────────────────────────────────────────

Write-Info "Checking Docker Desktop..."
try {
    $null = docker version 2>&1
    Write-OK "Docker Desktop is running"
} catch {
    Write-Fail "Docker Desktop not found or not running. Install from https://docs.docker.com/desktop/install/windows/"
    exit 1
}

Write-Info "Checking Docker Compose..."
try {
    $null = docker compose version 2>&1
    Write-OK "Docker Compose available"
} catch {
    Write-Fail "Docker Compose not available (included with Docker Desktop >= 3.x)"
    exit 1
}

Write-Info "Checking WSL 2..."
$wsl = wsl --list --verbose 2>&1
if ($wsl -match "VERSION") {
    Write-OK "WSL 2 is enabled"
} else {
    Write-Fail "WSL 2 not found. Run: wsl --install"
    exit 1
}

# ── Create .env.docker if missing ────────────────────────────────────────────

if (-not (Test-Path ".env.docker")) {
    Copy-Item ".env.docker.example" ".env.docker"
    Write-OK ".env.docker created from example — review and edit if needed"
} else {
    Write-OK ".env.docker already exists"
}

# ── Pull infrastructure images ────────────────────────────────────────────────

Write-Info "Pulling infrastructure images (this may take a few minutes)..."
docker pull ollama/ollama:latest
docker pull chromadb/chroma:latest
Write-OK "Infrastructure images pulled"

# ── Build platform services ───────────────────────────────────────────────────

Write-Info "Building platform service images..."
docker compose build
Write-OK "Platform images built"

# ── Start all services ────────────────────────────────────────────────────────

Write-Info "Starting all services..."
docker compose up -d
Write-OK "Services started"

# ── Wait and verify ───────────────────────────────────────────────────────────

Write-Info "Waiting 10 seconds for services to initialise..."
Start-Sleep 10

$services = @(
    @{ name = "admin";               url = "http://localhost:8000/health" },
    @{ name = "chat";                url = "http://localhost:8010/health" },
    @{ name = "writer";              url = "http://localhost:8011/health" },
    @{ name = "coding";              url = "http://localhost:8012/health" },
    @{ name = "autocoder-dashboard"; url = "http://localhost:8050/health" },
    @{ name = "conductor";           url = "http://localhost:8001/health" },
    @{ name = "re-agent";            url = "http://localhost:8002/health" },
    @{ name = "ollama";              url = "http://localhost:11434/api/tags" },
    @{ name = "chromadb";            url = "http://localhost:8020/api/v1/heartbeat" }
)

$passed = 0
foreach ($svc in $services) {
    try {
        $r = Invoke-WebRequest -Uri $svc.url -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
        if ($r.StatusCode -eq 200) {
            Write-OK "$($svc.name)"
            $passed++
        } else {
            Write-Fail "$($svc.name) — HTTP $($r.StatusCode)"
        }
    } catch {
        Write-Fail "$($svc.name) — not responding"
    }
}

Write-Host ""
Write-Host "$passed/$($services.Count) services healthy" -ForegroundColor $(if ($passed -eq $services.Count) { "Green" } else { "Yellow" })
Write-Host ""
Write-Info "Admin panel: http://localhost:8000"
Write-Info "To stop:     docker compose down  (from docker/ directory)"
Write-Info "To view logs: docker compose logs -f [service-name]"
