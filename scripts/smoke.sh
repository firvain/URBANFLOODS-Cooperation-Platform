#!/usr/bin/env bash
# Production-mode smoke test: build and start the REAL production stack (docker-compose.prod.yml:
# nginx + built SPA, backend, Postgres) with test settings (docker-compose.smoke.yml +
# .env.smoke: Mailpit for email, Cloudflare's Turnstile test keys), run the Playwright smoke suite
# (frontend/e2e/smoke) against http://localhost:3002, then delete everything again.
#
#   scripts/smoke.sh                      # from anywhere; needs Docker, Node 22 and
#                                         # `npx playwright install chromium` in frontend/
#   scripts/smoke.sh -- auth              # extra arguments after -- go to `npm run e2e:smoke`
#   SMOKE_KEEP=1 scripts/smoke.sh         # leave the stack running afterwards (debugging);
#                                         # remove it later with: scripts/smoke.sh --down
#   scripts/smoke.sh --down               # only tear a kept stack down
#
# Isolation: its own compose project (ufsmoke) with its own container, image, volume and network
# names, so it never touches the development stack, the production stack or anything else. It
# publishes the production host ports (127.0.0.1:3002, 127.0.0.1:8002) plus Mailpit's API on
# 127.0.0.1:${SMOKE_MAILPIT_PORT:-8026}, and refuses to start if any of them is taken.
# NEVER run it on the production server (the port check stops it there anyway).
#
# Always tears down with `down -v --remove-orphans` (trap), unless SMOKE_KEEP=1. On failure it
# prints the container logs; with SMOKE_LOG_DIR set it also writes them there (CI artifact).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PROJECT=ufsmoke
COMPOSE=(docker compose -p "$PROJECT" -f docker-compose.prod.yml -f docker-compose.smoke.yml --env-file .env.smoke)
MAILPIT_PORT="${SMOKE_MAILPIT_PORT:-8026}"
BASE_URL=http://localhost:3002
MAILPIT_URL="http://localhost:${MAILPIT_PORT}"
HEALTH_TIMEOUT="${SMOKE_HEALTH_TIMEOUT:-180}"

ADMIN_EMAIL=smoke-admin@example.org
ADMIN_NAME="Smoke Admin"
# A fresh password per run, never written to disk: the stack is deleted at the end anyway.
ADMIN_PASSWORD="Smoke-$(openssl rand -hex 16)"

log() { echo "[smoke $(date '+%H:%M:%S')] $*"; }

teardown() {
    log "Tearing down (docker compose -p $PROJECT down -v --remove-orphans)"
    "${COMPOSE[@]}" down -v --remove-orphans --timeout 10 || true
}

dump_logs() {
    log "Container status and logs"
    "${COMPOSE[@]}" ps -a || true
    "${COMPOSE[@]}" logs --no-color --tail 200 || true
    if [ -n "${SMOKE_LOG_DIR:-}" ]; then
        mkdir -p "$SMOKE_LOG_DIR"
        "${COMPOSE[@]}" logs --no-color --timestamps >"$SMOKE_LOG_DIR/compose.log" 2>&1 || true
        "${COMPOSE[@]}" ps -a >"$SMOKE_LOG_DIR/compose-ps.txt" 2>&1 || true
    fi
}

if [ "${1:-}" = "--down" ]; then
    teardown
    exit 0
fi
if [ "${1:-}" = "--" ]; then shift; fi

# --- refuse to collide with anything already running --------------------------------------------
if [ -n "$(docker ps -aq --filter "label=com.docker.compose.project=$PROJECT")" ]; then
    echo "ERROR: a '$PROJECT' stack already exists (a kept or interrupted run?). Remove it first: scripts/smoke.sh --down" >&2
    exit 1
fi
for port in 3002 8002 "$MAILPIT_PORT"; do
    if (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
        echo "ERROR: 127.0.0.1:$port is already in use; the smoke stack needs it free (never run this on the production server)." >&2
        exit 1
    fi
done

status=1
on_exit() {
    if [ "$status" -ne 0 ]; then dump_logs; fi
    if [ "${SMOKE_KEEP:-0}" = "1" ]; then
        log "SMOKE_KEEP=1: the stack keeps running ($BASE_URL, Mailpit $MAILPIT_URL). Remove it with: scripts/smoke.sh --down"
    else
        teardown
    fi
    exit "$status"
}
trap on_exit EXIT
trap 'exit 130' INT TERM

# --- build and start -----------------------------------------------------------------------------
started=$(date +%s)
log "Building and starting the production stack with the smoke settings"
"${COMPOSE[@]}" up -d --build --wait --wait-timeout "$HEALTH_TIMEOUT"
log "Stack healthy after $(($(date +%s) - started))s"

curl -fsS --max-time 10 http://127.0.0.1:8002/health/ready >/dev/null
curl -fsS --max-time 10 -o /dev/null "$BASE_URL/"
curl -fsS --max-time 10 -o /dev/null "$MAILPIT_URL/api/v1/info"

# --- superadmin (the backend CLI, as in production) ----------------------------------------------
log "Creating the superadmin $ADMIN_EMAIL"
"${COMPOSE[@]}" exec -T backend python -m app.cli create-superadmin \
    --email "$ADMIN_EMAIL" --display-name "$ADMIN_NAME" --password "$ADMIN_PASSWORD"

# --- the suite -----------------------------------------------------------------------------------
log "Running the Playwright smoke suite against $BASE_URL"
cd "$ROOT/frontend"
set +e
E2E_BASE_URL="$BASE_URL" \
    E2E_MAILPIT_URL="$MAILPIT_URL" \
    E2E_SMOKE_ADMIN_EMAIL="$ADMIN_EMAIL" \
    E2E_SMOKE_ADMIN_PASSWORD="$ADMIN_PASSWORD" \
    E2E_SMOKE_ADMIN_NAME="$ADMIN_NAME" \
    npm run e2e:smoke -- "$@"
status=$?
set -e
cd "$ROOT"

if [ "$status" -eq 0 ]; then
    log "Smoke suite passed ($(($(date +%s) - started))s in total)"
else
    log "Smoke suite FAILED (exit $status); report: frontend/playwright-report/index.html"
fi
