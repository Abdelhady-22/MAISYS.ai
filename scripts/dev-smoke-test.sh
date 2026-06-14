#!/bin/sh
# MAISYS auth-service smoke test.
#
# Walks one user through the full lifecycle against the running stack
# brought up by ./scripts/dev-up.sh.
#
# Requires: curl, jq, docker. No sudo.
#
# OTP handling: registration generates a random OTP. The plaintext code
# is logged inside the auth-service container, but `shared.logger.
# scrub_sensitive` may redact it. To work regardless, the smoke test
# injects a KNOWN OTP into the auth database via `docker exec` and uses
# that code for the verify-otp step. This tests the verify-otp endpoint
# without depending on log-scrubbing behaviour.
#
# Usage:  ./scripts/dev-smoke-test.sh
# Exit:   0 on all-pass, non-zero on any failure.

set -u

BASE_URL="${BASE_URL:-http://localhost:8001}"
CONTAINER="${AUTH_SERVICE_CONTAINER:-maisys-auth-service}"
PASSWORD='SmokeT@st-Pass-1'
KNOWN_OTP='123456'

pass=0
fail=0

# ── Helpers ─────────────────────────────────────────────────────
say()  { printf '  %s\n' "$*"; }
step() { printf '\n[%d] %s\n' "$1" "$2"; }
ok()   { pass=$((pass + 1)); printf '  PASS: %s\n' "$*"; }
ko()   { fail=$((fail + 1)); printf '  FAIL: %s\n' "$*" >&2; }

# Assert HTTP status code; expects $1=expected_code, $2=description, $3=actual_code
assert_status() {
    expected="$1"; desc="$2"; actual="$3"
    if [ "$actual" = "$expected" ]; then
        ok "$desc -> HTTP $actual"
    else
        ko "$desc -> expected HTTP $expected, got $actual"
    fi
}

# ── Pre-flight ──────────────────────────────────────────────────
command -v curl >/dev/null 2>&1 || { printf 'ERROR: curl not found.\n' >&2; exit 1; }
command -v jq   >/dev/null 2>&1 || { printf 'ERROR: jq not found.\n' >&2; exit 1; }
command -v docker >/dev/null 2>&1 || { printf 'ERROR: docker not found.\n' >&2; exit 1; }

if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    printf 'ERROR: container "%s" is not running. Bring the stack up first:\n  ./scripts/dev-up.sh\n' "$CONTAINER" >&2
    exit 1
fi

EMAIL="smoke-test-$(date +%s)@example.com"
printf 'Smoke test against %s\n' "$BASE_URL"
printf 'Test email: %s\n' "$EMAIL"

# ── 1. Health ───────────────────────────────────────────────────
step 1 "GET $BASE_URL/health"
code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE_URL/health")
assert_status 200 "/health" "$code"

# ── 2. Generate test email (already done above) ─────────────────
step 2 "Generated unique test email"
ok "email=$EMAIL"

# ── 3. Register ─────────────────────────────────────────────────
step 3 "POST $BASE_URL/auth/register"
register_resp=$(curl -s -w '\n%{http_code}' \
    -H 'Content-Type: application/json' \
    -X POST "$BASE_URL/auth/register" \
    -d "$(jq -nc --arg e "$EMAIL" --arg p "$PASSWORD" \
        '{email: $e, password: $p, language_preference: "en"}')")
register_code=$(printf '%s\n' "$register_resp" | tail -n1)
register_body=$(printf '%s\n' "$register_resp" | sed '$d')
assert_status 201 "/auth/register" "$register_code"

if [ "$register_code" != "201" ]; then
    say "Response body: $register_body"
    printf '\nSmoke test ABORTED (cannot proceed past register).\n' >&2
    printf 'Summary: %d PASS / %d FAIL\n' "$pass" "$fail" >&2
    exit 1
fi

USER_ID=$(printf '%s' "$register_body" | jq -r '.data.user_id')
say "user_id=$USER_ID"

# ── 4. Inject known OTP into auth DB via docker exec ────────────
step 4 "Inject known OTP into auth database"
say "Bypassing scrub_sensitive by overwriting the active OTP's code_hash"
inject_output=$(docker exec -e USER_ID="$USER_ID" -e KNOWN_OTP="$KNOWN_OTP" "$CONTAINER" \
    python -c "
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
" 2>&1)
inject_exit=$?
if [ "$inject_exit" -ne 0 ]; then
    ko "OTP injection failed (exit $inject_exit): $inject_output"
    printf '\nSmoke test ABORTED (no active OTP after registration).\n' >&2
    exit 1
fi
ok "Active OTP overwritten with code=$KNOWN_OTP"

# ── 5. Verify OTP ───────────────────────────────────────────────
step 5 "POST $BASE_URL/auth/verify-otp"
code=$(curl -s -o /dev/null -w '%{http_code}' \
    -H 'Content-Type: application/json' \
    -X POST "$BASE_URL/auth/verify-otp" \
    -d "$(jq -nc --arg u "$USER_ID" --arg c "$KNOWN_OTP" \
        '{user_id: $u, code: $c, purpose: "email_verify"}')")
assert_status 200 "/auth/verify-otp" "$code"

# ── 6. Login ────────────────────────────────────────────────────
step 6 "POST $BASE_URL/auth/login"
login_resp=$(curl -s -w '\n%{http_code}' \
    -H 'Content-Type: application/json' \
    -X POST "$BASE_URL/auth/login" \
    -d "$(jq -nc --arg e "$EMAIL" --arg p "$PASSWORD" \
        '{email: $e, password: $p}')")
login_code=$(printf '%s\n' "$login_resp" | tail -n1)
login_body=$(printf '%s\n' "$login_resp" | sed '$d')
assert_status 200 "/auth/login" "$login_code"

if [ "$login_code" != "200" ]; then
    say "Response body: $login_body"
    printf '\nSmoke test ABORTED (cannot proceed past login).\n' >&2
    exit 1
fi

ACCESS_TOKEN=$(printf '%s' "$login_body" | jq -r '.data.access_token')
REFRESH_TOKEN=$(printf '%s' "$login_body" | jq -r '.data.refresh_token')
say "access_token captured (length=$(printf '%s' "$ACCESS_TOKEN" | wc -c | tr -d ' '))"
say "refresh_token captured (length=$(printf '%s' "$REFRESH_TOKEN" | wc -c | tr -d ' '))"

# ── 7. GET /auth/me ─────────────────────────────────────────────
step 7 "GET $BASE_URL/auth/me (Bearer token)"
me_resp=$(curl -s -w '\n%{http_code}' \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    "$BASE_URL/auth/me")
me_code=$(printf '%s\n' "$me_resp" | tail -n1)
me_body=$(printf '%s\n' "$me_resp" | sed '$d')
assert_status 200 "/auth/me" "$me_code"

if [ "$me_code" = "200" ]; then
    me_email=$(printf '%s' "$me_body" | jq -r '.data.email')
    if [ "$me_email" = "$EMAIL" ]; then
        ok "/auth/me returned the registered email"
    else
        ko "/auth/me returned email='$me_email', expected '$EMAIL'"
    fi
fi

# ── 8. Refresh ──────────────────────────────────────────────────
step 8 "POST $BASE_URL/auth/refresh"
refresh_resp=$(curl -s -w '\n%{http_code}' \
    -H 'Content-Type: application/json' \
    -X POST "$BASE_URL/auth/refresh" \
    -d "$(jq -nc --arg t "$REFRESH_TOKEN" '{refresh_token: $t}')")
refresh_code=$(printf '%s\n' "$refresh_resp" | tail -n1)
refresh_body=$(printf '%s\n' "$refresh_resp" | sed '$d')
assert_status 200 "/auth/refresh" "$refresh_code"

if [ "$refresh_code" = "200" ]; then
    NEW_ACCESS=$(printf '%s' "$refresh_body" | jq -r '.data.access_token')
    NEW_REFRESH=$(printf '%s' "$refresh_body" | jq -r '.data.refresh_token')
    if [ "$NEW_REFRESH" != "$REFRESH_TOKEN" ] && [ -n "$NEW_REFRESH" ]; then
        ok "Refresh token rotated"
    else
        ko "Refresh did not rotate the token"
    fi
fi

# ── 9. Logout ───────────────────────────────────────────────────
# NOTE: brief says expect 204; actual main.py + routes/logout.py
# returns 200 with APIResponse envelope. See Conflict 1.5 in
# MAISYS_conflicts_and_decisions_log.md.
step 9 "POST $BASE_URL/auth/logout"
code=$(curl -s -o /dev/null -w '%{http_code}' \
    -H "Authorization: Bearer ${NEW_ACCESS:-$ACCESS_TOKEN}" \
    -X POST "$BASE_URL/auth/logout")
assert_status 200 "/auth/logout" "$code"

# ── 10. Login again with original creds ─────────────────────────
step 10 "POST $BASE_URL/auth/login (verify logout didn't break account)"
code=$(curl -s -o /dev/null -w '%{http_code}' \
    -H 'Content-Type: application/json' \
    -X POST "$BASE_URL/auth/login" \
    -d "$(jq -nc --arg e "$EMAIL" --arg p "$PASSWORD" \
        '{email: $e, password: $p}')")
assert_status 200 "/auth/login (re-login after logout)" "$code"

# ── Summary ─────────────────────────────────────────────────────
printf '\n============================================================\n'
printf '  SMOKE TEST SUMMARY\n'
printf '============================================================\n'
printf '  PASS: %d\n' "$pass"
printf '  FAIL: %d\n' "$fail"
printf '============================================================\n'

if [ "$fail" -eq 0 ]; then
    printf '  Result: ALL PASS\n'
    exit 0
else
    printf '  Result: FAILURES PRESENT\n'
    exit 1
fi
