#Requires -Version 5.1
<#
.SYNOPSIS
    Stop the Jarvis dev environment.
.PARAMETER Remove
    Also remove containers and volumes (full reset).
#>
param(
    [switch]$Remove
)

$ComposeDir = Join-Path $PSScriptRoot "..\..\docker"

Push-Location $ComposeDir
if ($Remove) {
    docker compose down -v @args
} else {
    docker compose down @args
}
Pop-Location
