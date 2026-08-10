#Requires -Version 5.1
<#
.SYNOPSIS
    Hard-reset the Jarvis dev environment: stop, remove containers/volumes, rebuild, start.
.PARAMETER Mock
    Use the mock Ollama service instead of real Ollama.
#>
param(
    [switch]$Mock
)

$ComposeDir = Join-Path $PSScriptRoot "..\..\docker"

Write-Host "Stopping and removing all containers and volumes..." -ForegroundColor Yellow
Push-Location $ComposeDir
docker compose down -v

Write-Host "Rebuilding and starting..." -ForegroundColor Yellow
if ($Mock) {
    docker compose --profile mock up --build @args
} else {
    docker compose --profile real up --build @args
}
Pop-Location
