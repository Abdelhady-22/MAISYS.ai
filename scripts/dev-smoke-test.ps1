# MAISYS auth-service smoke test (PowerShell).
#
# Walks one user through the full lifecycle against the running stack.
# Requires: curl.exe (Windows 10+ ships it) OR Invoke-RestMethod, plus
# docker on PATH. No jq needed — uses ConvertFrom-Json.
#
# Usage:  .\scripts\dev-smoke-test.ps1
# Exit:   0 on all-pass, non-zero on any failure.

[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$BaseUrl   = if ($env:BASE_URL) { $env:BASE_URL } else { "http://localhost:8001" }
$Container = if ($env:AUTH_SERVICE_CONTAINER) { $env:AUTH_SERVICE_CONTAINER } else { "maisys-auth-service" }
$Password  = 'SmokeT@st-Pass-1'
$KnownOtp  = '123456'

$script:Pass = 0
$script:Fail = 0

function Step  { param([int]$N, [string]$Title)   Write-Host ""; Write-Host "[$N] $Title" }
function Say   { param([string]$Msg)              Write-Host "  $Msg" }
function Ok    { param([string]$Msg) $script:Pass++; Write-Host "  PASS: $Msg" -ForegroundColor Green }
function Ko    { param([string]$Msg) $script:Fail++; Write-Host "  FAIL: $Msg" -ForegroundColor Red }

function Assert-Status {
    param([int]$Expected, [string]$Desc, [int]$Actual)
    if ($Actual -eq $Expected) {
        Ok "$Desc -> HTTP $Actual"
    } else {
        Ko "$Desc -> expected HTTP $Expected, got $Actual"
    }
}

# Invoke-WebRequest wrapper that returns status code + body even on non-2xx.
function Invoke-Http {
    param(
        [string]$Method,
        [string]$Url,
        [object]$Body = $null,
        [hashtable]$Headers = @{}
    )
    $params = @{
        Uri                = $Url
        Method             = $Method
        UseBasicParsing    = $true
        Headers            = $Headers
        SkipHttpErrorCheck = $false  # PS 5.1 doesn't have this — handled via try/catch
    }
    if ($Body) {
        $params.Body = ($Body | ConvertTo-Json -Compress)
        $params.ContentType = 'application/json'
    }
    try {
        $resp = Invoke-WebRequest @params
        return @{ Status = [int]$resp.StatusCode; Body = $resp.Content }
    } catch [System.Net.WebException] {
        $r = $_.Exception.Response
        if ($r) {
            $code = [int]$r.StatusCode
            $sr = New-Object System.IO.StreamReader($r.GetResponseStream())
            $body = $sr.ReadToEnd()
            return @{ Status = $code; Body = $body }
        }
        return @{ Status = 0; Body = $_.Exception.Message }
    } catch {
        return @{ Status = 0; Body = $_.Exception.Message }
    }
}

# ── Pre-flight ──────────────────────────────────────────────────
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error "docker not found."
    exit 1
}

$running = (docker ps --format '{{.Names}}') -split "`n" | Where-Object { $_ -eq $Container }
if (-not $running) {
    Write-Error "Container '$Container' is not running. Bring up the stack first:`n  .\scripts\dev-up.ps1"
    exit 1
}

$email = "smoke-test-$([int][double]::Parse((Get-Date -UFormat %s)))@example.com"
Write-Host "Smoke test against $BaseUrl"
Write-Host "Test email: $email"

# ── 1. Health ───────────────────────────────────────────────────
Step 1 "GET $BaseUrl/health"
$r = Invoke-Http -Method Get -Url "$BaseUrl/health"
Assert-Status 200 "/health" $r.Status

# ── 2. Generated email ──────────────────────────────────────────
Step 2 "Generated unique test email"
Ok "email=$email"

# ── 3. Register ─────────────────────────────────────────────────
Step 3 "POST $BaseUrl/auth/register"
$r = Invoke-Http -Method Post -Url "$BaseUrl/auth/register" -Body @{
    email = $email
    password = $Password
    language_preference = "en"
}
Assert-Status 201 "/auth/register" $r.Status

if ($r.Status -ne 201) {
    Say "Response body: $($r.Body)"
    Write-Host "`nSmoke test ABORTED (cannot proceed past register)."
    Write-Host "Summary: $($script:Pass) PASS / $($script:Fail) FAIL"
    exit 1
}

$userId = ($r.Body | ConvertFrom-Json).data.user_id
Say "user_id=$userId"

# ── 4. Inject known OTP via docker exec ─────────────────────────
Step 4 "Inject known OTP into auth database"
Say "Bypassing scrub_sensitive by overwriting the active OTP's code_hash"

$injectScript = @'
import asyncio, os, sys, uuid
from sqlalchemy import update
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from models.db import OTPCode
from utils.otp import hash_otp

async def inject():
    engine = create_async_engine(os.environ['DATABASE_URL'])
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        result = await s.execute(
            update(OTPCode)
            .where(OTPCode.user_id == uuid.UUID(os.environ['USER_ID']))
            .where(OTPCode.purpose == 'email_verify')
            .where(OTPCode.used == False)
            .values(code_hash=hash_otp(os.environ['KNOWN_OTP']))
        )
        await s.commit()
        if result.rowcount == 0:
            print('NO_ACTIVE_OTP', file=sys.stderr)
            sys.exit(2)
    await engine.dispose()
    print('OK')

asyncio.run(inject())
'@

$injectOut = docker exec -e USER_ID="$userId" -e KNOWN_OTP="$KnownOtp" $Container python -c $injectScript 2>&1
if ($LASTEXITCODE -ne 0) {
    Ko "OTP injection failed (exit $LASTEXITCODE): $injectOut"
    Write-Host "`nSmoke test ABORTED (no active OTP after registration)."
    exit 1
}
Ok "Active OTP overwritten with code=$KnownOtp"

# ── 5. Verify OTP ───────────────────────────────────────────────
Step 5 "POST $BaseUrl/auth/verify-otp"
$r = Invoke-Http -Method Post -Url "$BaseUrl/auth/verify-otp" -Body @{
    user_id = $userId
    code = $KnownOtp
    purpose = "email_verify"
}
Assert-Status 200 "/auth/verify-otp" $r.Status

# ── 6. Login ────────────────────────────────────────────────────
Step 6 "POST $BaseUrl/auth/login"
$r = Invoke-Http -Method Post -Url "$BaseUrl/auth/login" -Body @{
    email = $email
    password = $Password
}
Assert-Status 200 "/auth/login" $r.Status

if ($r.Status -ne 200) {
    Say "Response body: $($r.Body)"
    Write-Host "`nSmoke test ABORTED (cannot proceed past login)."
    exit 1
}

$loginData = ($r.Body | ConvertFrom-Json).data
$accessToken = $loginData.access_token
$refreshToken = $loginData.refresh_token
Say "access_token captured (length=$($accessToken.Length))"
Say "refresh_token captured (length=$($refreshToken.Length))"

# ── 7. GET /auth/me ─────────────────────────────────────────────
Step 7 "GET $BaseUrl/auth/me (Bearer token)"
$r = Invoke-Http -Method Get -Url "$BaseUrl/auth/me" -Headers @{
    Authorization = "Bearer $accessToken"
}
Assert-Status 200 "/auth/me" $r.Status
if ($r.Status -eq 200) {
    $meEmail = ($r.Body | ConvertFrom-Json).data.email
    if ($meEmail -eq $email) {
        Ok "/auth/me returned the registered email"
    } else {
        Ko "/auth/me returned email='$meEmail', expected '$email'"
    }
}

# ── 8. Refresh ──────────────────────────────────────────────────
Step 8 "POST $BaseUrl/auth/refresh"
$r = Invoke-Http -Method Post -Url "$BaseUrl/auth/refresh" -Body @{
    refresh_token = $refreshToken
}
Assert-Status 200 "/auth/refresh" $r.Status

$newAccess = $accessToken
if ($r.Status -eq 200) {
    $refreshData = ($r.Body | ConvertFrom-Json).data
    $newAccess = $refreshData.access_token
    $newRefresh = $refreshData.refresh_token
    if ($newRefresh -and $newRefresh -ne $refreshToken) {
        Ok "Refresh token rotated"
    } else {
        Ko "Refresh did not rotate the token"
    }
}

# ── 9. Logout ───────────────────────────────────────────────────
# NOTE: brief says expect 204; actual main.py returns 200 with envelope.
# See Conflict 1.5 in MAISYS_conflicts_and_decisions_log.md.
Step 9 "POST $BaseUrl/auth/logout"
$r = Invoke-Http -Method Post -Url "$BaseUrl/auth/logout" -Headers @{
    Authorization = "Bearer $newAccess"
}
Assert-Status 200 "/auth/logout" $r.Status

# ── 10. Login again ─────────────────────────────────────────────
Step 10 "POST $BaseUrl/auth/login (verify logout didn't break account)"
$r = Invoke-Http -Method Post -Url "$BaseUrl/auth/login" -Body @{
    email = $email
    password = $Password
}
Assert-Status 200 "/auth/login (re-login after logout)" $r.Status

# ── Summary ─────────────────────────────────────────────────────
Write-Host ""
Write-Host "============================================================"
Write-Host "  SMOKE TEST SUMMARY"
Write-Host "============================================================"
Write-Host "  PASS: $($script:Pass)"
Write-Host "  FAIL: $($script:Fail)"
Write-Host "============================================================"

if ($script:Fail -eq 0) {
    Write-Host "  Result: ALL PASS" -ForegroundColor Green
    exit 0
} else {
    Write-Host "  Result: FAILURES PRESENT" -ForegroundColor Red
    exit 1
}
