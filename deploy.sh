#!/usr/bin/env bash
# Deploy or update the Cooperation Platform on the production server.
#
#   cd ~/URBANFLOODS-Cooperation-Platform && ./deploy.sh [--no-pull] [--no-backup]
#
# Runs as the deploy user (docker group, no sudo) from the repository root:
#   1. checks .env.prod exists and is mode 600
#   2. git pull --ff-only origin main            (skip with --no-pull)
#   3. scripts/backup.sh if the database runs    (skip with --no-backup)
#   4. builds the images and starts them with `up -d --remove-orphans`
#   5. waits for the backend and frontend healthchecks, then curls both
#
# It never runs `docker compose down`: the volumes (database, uploads) must survive, and only this
# project's containers are ever touched (the urbanfloods-knowbase-*-prod containers on the same
# host belong to another project). Database migrations run in the backend entrypoint.
set -euo pipefail

cd "$(dirname "$0")"

COMPOSE=(docker compose --env-file .env.prod -f docker-compose.prod.yml)
DB_CONTAINER=urbanfloods-cooperation-db-prod
BACKEND_CONTAINER=urbanfloods-cooperation-backend-prod
FRONTEND_CONTAINER=urbanfloods-cooperation-frontend-prod
HEALTH_TIMEOUT=120

pull=1
backup=1
for arg in "$@"; do
    case "$arg" in
        --no-pull) pull=0 ;;
        --no-backup) backup=0 ;;
        -h | --help)
            sed -n '2,15p' "$0"
            exit 0
            ;;
        *)
            echo "Unknown option: $arg (use --no-pull, --no-backup)" >&2
            exit 2
            ;;
    esac
done

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
fail() {
    echo "ERROR: $*" >&2
    exit 1
}

# --- 1. secrets file ---------------------------------------------------------------------------
[ -f .env.prod ] || fail ".env.prod not found. Copy .env.prod.example to .env.prod, fill it in, chmod 600 .env.prod."
mode=$(stat -c '%a' .env.prod 2>/dev/null || stat -f '%Lp' .env.prod)
[ "$mode" = "600" ] || fail ".env.prod has mode $mode; run: chmod 600 .env.prod"

# --- 2. code -----------------------------------------------------------------------------------
if [ "$pull" -eq 1 ]; then
    log "Pulling origin/main (fast-forward only)"
    git pull --ff-only origin main
else
    log "Skipping git pull (--no-pull)"
fi
log "Deploying commit $(git rev-parse --short HEAD 2>/dev/null || echo unknown)"

# --- 3. backup before anything changes -----------------------------------------------------------
if [ "$backup" -eq 1 ]; then
    if [ "$(docker inspect -f '{{.State.Running}}' "$DB_CONTAINER" 2>/dev/null || true)" = "true" ]; then
        log "Backing up the database and uploads"
        ./scripts/backup.sh
    else
        log "Database container not running (first deploy?); no backup taken"
    fi
else
    log "Skipping backup (--no-backup)"
fi

# --- 4. build and start ------------------------------------------------------------------------
log "Building images (pulling newer base images)"
"${COMPOSE[@]}" build --pull

log "Starting containers"
"${COMPOSE[@]}" up -d --remove-orphans

# --- 5. health ---------------------------------------------------------------------------------
# Polls the container's healthcheck status ("starting" -> "healthy") until HEALTH_TIMEOUT.
wait_healthy() {
    local container=$1 waited=0 status
    while :; do
        status=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}' "$container" 2>/dev/null || echo missing)
        if [ "$status" = "healthy" ]; then
            log "$container is healthy"
            return 0
        fi
        if [ "$status" = "missing" ] || [ "$status" = "no-healthcheck" ] || [ "$waited" -ge "$HEALTH_TIMEOUT" ]; then
            break
        fi
        sleep 5
        waited=$((waited + 5))
    done
    echo "ERROR: $container is '$status' after ${waited}s. Last log lines:" >&2
    docker logs --tail 50 "$container" >&2 || true
    return 1
}

log "Waiting up to ${HEALTH_TIMEOUT}s for the healthchecks"
wait_healthy "$BACKEND_CONTAINER"
wait_healthy "$FRONTEND_CONTAINER"

log "Checking http://127.0.0.1:8002/health/ready"
curl -fsS --max-time 10 http://127.0.0.1:8002/health/ready
echo
log "Checking http://127.0.0.1:3002/"
curl -fsS --max-time 10 -o /dev/null http://127.0.0.1:3002/
log "Frontend responds"

"${COMPOSE[@]}" ps

log "Removing dangling images"
docker image prune -f

log "Deployment complete"
