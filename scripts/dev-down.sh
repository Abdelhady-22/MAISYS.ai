#!/bin/sh
# MAISYS dev-down — tear down the local stack.
#
# Usage:
#   ./scripts/dev-down.sh          # stop containers, keep volumes
#   ./scripts/dev-down.sh -v       # also remove postgres/redis/qdrant/rabbitmq/minio volumes
#   ./scripts/dev-down.sh --volumes
#
# POSIX sh-compatible.

set -eu

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# Pick compose command
if docker compose version >/dev/null 2>&1; then
    DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    DC="docker-compose"
else
    printf 'ERROR: docker compose is not available.\n' >&2
    exit 1
fi

WIPE_VOLUMES=false
if [ "${1:-}" = "-v" ] || [ "${1:-}" = "--volumes" ]; then
    WIPE_VOLUMES=true
fi

if [ "$WIPE_VOLUMES" = "true" ]; then
    printf 'Stopping stack and REMOVING volumes (all data will be lost):\n'
    printf '  postgres_data, redis_data, qdrant_data, rabbitmq_data, minio_data\n'
    printf 'Continue? [y/N]: '
    read -r answer
    case "$answer" in
        y|Y|yes|YES) ;;
        *) printf 'Aborted.\n'; exit 0 ;;
    esac
    $DC down --volumes --remove-orphans
    printf '\nStack stopped, volumes removed.\n'
else
    $DC down --remove-orphans
    printf '\nStack stopped. Volumes preserved.\n'
    printf 'To also remove volumes: ./scripts/dev-down.sh -v\n'
fi
