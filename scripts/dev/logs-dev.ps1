#Requires -Version 5.1
<#
.SYNOPSIS
    Tail logs from the Jarvis dev environment.
.PARAMETER Service
    Name of a specific service (admin, chat, writer, coding, conductor, re-agent,
    autocoder-dashboard, caddy, chromadb). Omit to tail all services.
.EXAMPLE
    .\logs-dev.ps1              # all services
    .\logs-dev.ps1 -Service caddy
#>
param(
    [string]$Service = ""
)

$ComposeDir = Join-Path $PSScriptRoot "..\..\docker"

Push-Location $ComposeDir
if ($Service) {
    docker compose logs -f $Service @args
} else {
    docker compose logs -f @args
}
Pop-Location
