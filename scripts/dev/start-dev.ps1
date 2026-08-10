#Requires -Version 5.1
<#
.SYNOPSIS
    Start the Jarvis dev environment.
.PARAMETER Mock
    Use the mock Ollama service instead of real Ollama. No GPU required.
.EXAMPLE
    .\start-dev.ps1          # real Ollama (requires Ollama to be available)
    .\start-dev.ps1 -Mock    # mock LLM for UI/integration testing
#>
param(
    [switch]$Mock
)

$ComposeDir = Join-Path $PSScriptRoot "..\..\docker"

function Assert-DockerRunning {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Write-Host "Docker Desktop is not installed. Get it at: https://www.docker.com/products/docker-desktop" -ForegroundColor Red
        exit 1
    }
    docker ps 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { return }

    $exe = "${env:ProgramFiles}\Docker\Docker\Docker Desktop.exe"
    if (-not (Test-Path $exe)) {
        Write-Host "Docker daemon is not running. Start Docker Desktop and retry." -ForegroundColor Red
        exit 1
    }
    Write-Host "Docker Desktop is not running. Starting it..." -ForegroundColor Yellow
    Start-Process $exe
    $deadline = [datetime]::Now.AddSeconds(90)
    while ([datetime]::Now -lt $deadline) {
        Start-Sleep 3
        docker ps 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { Write-Host "Docker is ready." -ForegroundColor Green; return }
        Write-Host "  Waiting for Docker Desktop..." -ForegroundColor Gray
    }
    Write-Host "Docker did not start in 90s. Start Docker Desktop manually and retry." -ForegroundColor Red
    exit 1
}

if ($Mock) {
    Assert-DockerRunning
    Write-Host ""
    Write-Host "Starting platform with MOCK LLM -- no real AI responses." -ForegroundColor Yellow
    Write-Host "Use this for UI and integration testing only." -ForegroundColor Yellow
    Write-Host "Run without -Mock flag when Ollama is available." -ForegroundColor Yellow
    Write-Host ""
    Push-Location $ComposeDir
    docker compose --profile mock up --build @args
    Pop-Location
} else {
    Write-Host ""
    Write-Host "Starting platform with real Ollama." -ForegroundColor Green
    Write-Host "Ensure Ollama models are downloaded before use." -ForegroundColor Green
    Write-Host ""
    Push-Location $ComposeDir
    docker compose --profile real up @args
    Pop-Location
}
