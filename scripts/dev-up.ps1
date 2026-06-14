# MAISYS dev-up — bring the local stack up and wait for healthy.
#
# Usage:
#   .\scripts\dev-up.ps1            # up and wait for healthy
#   .\scripts\dev-up.ps1 logs       # up, then tail logs
#
# PowerShell 5.1 compatible.

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Subcommand = ""
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

$HealthTimeout = if ($env:HEALTH_TIMEOUT) { [int]$env:HEALTH_TIMEOUT } else { 180 }
$HealthPollInterval = 3

# ── 1. Docker running? ──────────────────────────────────────────
try {
    docker info | Out-Null
}
catch {
    Write-Error "Docker is not running. Start Docker Desktop and try again."
    exit 1
}

# ── 2. .env present? ────────────────────────────────────────────
if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env"
        Write-Warning ".env did not exist; copied .env.example -> .env. Review before committing anything."
    }
    else {
        Write-Error "Neither .env nor .env.example found. Cannot continue."
        exit 1
    }
}

# ── 3. Pick the compose command ─────────────────────────────────
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
        Write-Error 'Neither "docker compose" nor "docker-compose" is available.'
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

# ── 4. Bring it up ──────────────────────────────────────────────
Write-Host "Bringing up the stack (this builds the auth-service image on first run)..."
Invoke-DC up --build -d
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# ── 5. Wait for healthy ─────────────────────────────────────────
$ServicesWithHealth = @("postgres", "redis", "qdrant", "rabbitmq", "minio", "auth-service")

Write-Host "Waiting (up to ${HealthTimeout}s) for services to be healthy..."
$Start = Get-Date

while ($true) {
    $AllHealthy = $true
    foreach ($svc in $ServicesWithHealth) {
        $cid = (Invoke-DC ps -q $svc) 2>$null
        if (-not $cid) {
            $AllHealthy = $false
            break
        }
        $status = (docker inspect --format='{{.State.Health.Status}}' $cid) 2>$null
        if ($status -ne "healthy") {
            $AllHealthy = $false
            break
        }
    }

    if ($AllHealthy) { break }

    $elapsed = [int]((Get-Date) - $Start).TotalSeconds
    if ($elapsed -ge $HealthTimeout) {
        Write-Error "Healthcheck timed out after ${HealthTimeout}s."
        Write-Host "Service status:"
        Invoke-DC ps
        Write-Host "`nLast 30 log lines from each unhealthy service:"
        foreach ($svc in $ServicesWithHealth) {
            $cid = (Invoke-DC ps -q $svc) 2>$null
            if ($cid) {
                $st = (docker inspect --format='{{.State.Health.Status}}' $cid) 2>$null
                if ($st -ne "healthy") {
                    Write-Host "`n--- $svc ($st) ---"
                    docker logs --tail 30 $cid
                }
            }
        }
        exit 1
    }
    Start-Sleep -Seconds $HealthPollInterval
}

$totalElapsed = [int]((Get-Date) - $Start).TotalSeconds
Write-Host "`nAll services healthy in ${totalElapsed}s.`n"

# ── 6. Summary table ────────────────────────────────────────────
"{0,-22} {1,-12} {2,-12} {3}" -f "SERVICE", "PORTS", "HEALTH", "IMAGE"
"{0,-22} {1,-12} {2,-12} {3}" -f "----------------------", "------------", "------------", "-----"

foreach ($svc in @("postgres", "redis", "qdrant", "rabbitmq", "minio", "auth-service")) {
    $cid = (Invoke-DC ps -q $svc) 2>$null
    if (-not $cid) {
        "{0,-22} {1,-12} {2,-12} {3}" -f $svc, "-", "absent", "-"
        continue
    }
    $name = (docker inspect --format='{{.Name}}' $cid).TrimStart('/')
    $image = docker inspect --format='{{.Config.Image}}' $cid
    $status = docker inspect --format='{{.State.Health.Status}}' $cid 2>$null
    $ports = docker inspect --format='{{range $p, $conf := .NetworkSettings.Ports}}{{if $conf}}{{(index $conf 0).HostPort}} {{end}}{{end}}' $cid
    "{0,-22} {1,-12} {2,-12} {3}" -f $name, $ports.Trim(), $status, $image
}

Write-Host "`nOpenAPI docs:   http://localhost:8001/docs"
Write-Host "Metrics:        http://localhost:8001/metrics"
Write-Host "RabbitMQ UI:    http://localhost:15672  (guest/guest)"
Write-Host "MinIO console:  http://localhost:9001   (minioadmin/minioadmin)"
Write-Host "`nRun .\scripts\dev-smoke-test.ps1 to exercise the auth-service end-to-end."

# ── 7. Optional logs subcommand ─────────────────────────────────
if ($Subcommand -eq "logs") {
    Write-Host "`nTailing logs (Ctrl-C to detach)...`n"
    Invoke-DC logs -f
}
