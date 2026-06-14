# MAISYS dev-down — tear down the local stack.
#
# Usage:
#   .\scripts\dev-down.ps1               # stop containers, keep volumes
#   .\scripts\dev-down.ps1 -Volumes      # also remove volumes (lose data)
#
# PowerShell 5.1 compatible.

[CmdletBinding()]
param(
    [switch]$Volumes
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

# Pick compose
$DC = $null
try {
    docker compose version | Out-Null
    $DC = @("docker", "compose")
}
catch {
    if (Get-Command docker-compose -ErrorAction SilentlyContinue) {
        $DC = @("docker-compose")
    }
    else {
        Write-Error "docker compose is not available."
        exit 1
    }
}

function Invoke-DC {
    param([Parameter(ValueFromRemainingArguments = $true)]$Args)
    $cmd = $DC[0]
    $cmdArgs = @()
    if ($DC.Length -gt 1) { $cmdArgs += $DC[1..($DC.Length - 1)] }
    $cmdArgs += $Args
    & $cmd $cmdArgs
}

if ($Volumes) {
    Write-Host "Stopping stack and REMOVING volumes (all data will be lost):"
    Write-Host "  postgres_data, redis_data, qdrant_data, rabbitmq_data, minio_data"
    $confirm = Read-Host "Continue? [y/N]"
    if ($confirm -notmatch '^(y|Y|yes|YES)$') {
        Write-Host "Aborted."
        exit 0
    }
    Invoke-DC down --volumes --remove-orphans
    Write-Host "`nStack stopped, volumes removed."
}
else {
    Invoke-DC down --remove-orphans
    Write-Host "`nStack stopped. Volumes preserved."
    Write-Host "To also remove volumes: .\scripts\dev-down.ps1 -Volumes"
}
