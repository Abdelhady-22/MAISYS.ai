#!/bin/sh
# MAISYS dev-up — bring the local stack up and wait for healthy.
#
# Usage:
#   ./scripts/dev-up.sh           # up and wait for healthy
#   ./scripts/dev-up.sh logs      # up, then tail logs from all services
#
# POSIX sh-compatible. No bash-isms.

set -eu

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-180}"
HEALTH_POLL_INTERVAL=3

# ── 1. Docker running? ──────────────────────────────────────────
if ! docker info >/dev/null 2>&1; then
    printf 'ERROR: Docker is not running. Start Docker Desktop / dockerd and try again.\n' >&2
    exit 1
fi

# ── 2. .env present? ────────────────────────────────────────────
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        cp .env.example .env
        printf 'WARN: .env did not exist; copied .env.example -> .env. Review before committing anything.\n' >&2
    else
        printf 'ERROR: neither .env nor .env.example found. Cannot continue.\n' >&2
        exit 1
    fi
fi

# ── 3. Pick the compose command (docker compose vs docker-compose) ──
if docker compose version >/dev/null 2>&1; then
    DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    DC="docker-compose"
else
    printf 'ERROR: neither "docker compose" nor "docker-compose" is available.\n' >&2
    exit 1
fi

# ── 4. Bring it up ──────────────────────────────────────────────
printf 'Bringing up the stack (this builds the auth-service image on first run)...\n'
$DC up --build -d

# ── 5. Wait for every service that has a healthcheck to report healthy ──
SERVICES_WITH_HEALTH="postgres redis qdrant rabbitmq minio auth-service"

printf 'Waiting (up to %ss) for services to be healthy...\n' "$HEALTH_TIMEOUT"
START=$(date +%s)
while :; do
    ALL_HEALTHY=true
    for svc in $SERVICES_WITH_HEALTH; do
        cid=$($DC ps -q "$svc" 2>/dev/null || true)
        if [ -z "$cid" ]; then
            ALL_HEALTHY=false
            break
        fi
        status=$(docker inspect --format='{{.State.Health.Status}}' "$cid" 2>/dev/null || echo "starting")
        if [ "$status" != "healthy" ]; then
            ALL_HEALTHY=false
            break
        fi
    done

    if [ "$ALL_HEALTHY" = "true" ]; then
        break
    fi

    NOW=$(date +%s)
    ELAPSED=$((NOW - START))
    if [ "$ELAPSED" -ge "$HEALTH_TIMEOUT" ]; then
        printf 'ERROR: healthcheck timed out after %ss.\n' "$HEALTH_TIMEOUT" >&2
        printf 'Service status:\n' >&2
        $DC ps >&2 || true
        printf '\nLast 30 log lines from each unhealthy service:\n' >&2
        for svc in $SERVICES_WITH_HEALTH; do
            cid=$($DC ps -q "$svc" 2>/dev/null || true)
            if [ -n "$cid" ]; then
                st=$(docker inspect --format='{{.State.Health.Status}}' "$cid" 2>/dev/null || echo "unknown")
                if [ "$st" != "healthy" ]; then
                    printf '\n--- %s (%s) ---\n' "$svc" "$st" >&2
                    docker logs --tail 30 "$cid" >&2 || true
                fi
            fi
        done
        exit 1
    fi

    sleep "$HEALTH_POLL_INTERVAL"
done

# ── 6. Print the summary ────────────────────────────────────────
printf '\nAll services healthy in %ss.\n\n' "$((ELAPSED))"
printf '%-22s %-12s %-12s %-s\n' "SERVICE" "PORTS" "HEALTH" "IMAGE"
printf '%-22s %-12s %-12s %-s\n' "----------------------" "------------" "------------" "-----"

# postgres / redis / qdrant / rabbitmq / minio / auth-service
for svc in postgres redis qdrant rabbitmq minio auth-service; do
    cid=$($DC ps -q "$svc" 2>/dev/null || true)
    if [ -z "$cid" ]; then
        printf '%-22s %-12s %-12s %-s\n' "$svc" "-" "absent" "-"
        continue
    fi
    name=$(docker inspect --format='{{.Name}}' "$cid" | sed 's|^/||')
    image=$(docker inspect --format='{{.Config.Image}}' "$cid")
    status=$(docker inspect --format='{{.State.Health.Status}}' "$cid" 2>/dev/null || echo "n/a")
    ports=$(docker inspect --format='{{range $p, $conf := .NetworkSettings.Ports}}{{if $conf}}{{(index $conf 0).HostPort}} {{end}}{{end}}' "$cid" | tr -s ' ')
    printf '%-22s %-12s %-12s %-s\n' "$name" "$ports" "$status" "$image"
done

printf '\nOpenAPI docs:   http://localhost:8001/docs\n'
printf 'Metrics:        http://localhost:8001/metrics\n'
printf 'RabbitMQ UI:    http://localhost:15672  (guest/guest)\n'
printf 'MinIO console:  http://localhost:9001   (minioadmin/minioadmin)\n'
printf '\nRun ./scripts/dev-smoke-test.sh to exercise the auth-service end-to-end.\n'

# ── 7. Optional logs subcommand ─────────────────────────────────
if [ "${1:-}" = "logs" ]; then
    printf '\nTailing logs (Ctrl-C to detach)...\n\n'
    exec $DC logs -f
fi
