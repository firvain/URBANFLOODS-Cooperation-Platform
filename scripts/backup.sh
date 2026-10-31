#!/usr/bin/env bash
# Back up the Cooperation Platform database and uploaded images.
#
#   ~/backups/cooperation/db_<timestamp>.sql.gz         pg_dump of the database
#   ~/backups/cooperation/uploads_<timestamp>.tar.gz    contents of the uploads volume
# Files older than 14 days are deleted. deploy.sh runs this before every deploy.
#
# Daily at 03:15 from the deploy user's crontab (`crontab -e`, no sudo):
#   15 3 * * * /home/urbanfloods/URBANFLOODS-Cooperation-Platform/scripts/backup.sh >> /home/urbanfloods/backups/cooperation/backup.log 2>&1
#
# Restore (stop the backend first so nothing writes meanwhile:
#   docker compose --env-file .env.prod -f docker-compose.prod.yml stop backend frontend):
#   database, into an EMPTY database (drop and recreate it first if it has data):
#     docker exec urbanfloods-cooperation-db-prod dropdb -U cooperation_prod cooperation_db
#     docker exec urbanfloods-cooperation-db-prod createdb -U cooperation_prod -O cooperation_prod cooperation_db
#     gunzip -c ~/backups/cooperation/db_<timestamp>.sql.gz \
#       | docker exec -i urbanfloods-cooperation-db-prod psql -U cooperation_prod -d cooperation_db -v ON_ERROR_STOP=1
#   uploads:
#     gunzip -c ~/backups/cooperation/uploads_<timestamp>.tar.gz \
#       | docker run --rm -i -v urbanfloods_cooperation_uploads_prod:/uploads alpine:3.20 \
#           sh -c 'tar xf - -C /uploads && chown -R 10001:10001 /uploads'
#   then: docker compose --env-file .env.prod -f docker-compose.prod.yml up -d
# (User and database names as in .env.prod.)
set -euo pipefail

REPO_DIR=$(cd "$(dirname "$0")/.." && pwd)
ENV_FILE="$REPO_DIR/.env.prod"
BACKUP_DIR="${BACKUP_DIR:-$HOME/backups/cooperation}"
DB_CONTAINER=urbanfloods-cooperation-db-prod
UPLOADS_VOLUME=urbanfloods_cooperation_uploads_prod
RETENTION_DAYS=14
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

[ -f "$ENV_FILE" ] || {
    echo "ERROR: $ENV_FILE not found" >&2
    exit 1
}

# Read only the two names needed, never the whole file (it holds secrets, and must not be
# evaluated as shell). Defaults as in docker-compose.prod.yml.
env_value() {
    grep -E "^$1=" "$ENV_FILE" | tail -n 1 | cut -d= -f2- || true
}
POSTGRES_USER=$(env_value POSTGRES_USER)
POSTGRES_DB=$(env_value POSTGRES_DB)
POSTGRES_USER=${POSTGRES_USER:-cooperation_prod}
POSTGRES_DB=${POSTGRES_DB:-cooperation_db}

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
# New files readable by the deploy user only (the dump holds personal data).
umask 077

DB_FILE="$BACKUP_DIR/db_${TIMESTAMP}.sql.gz"
UPLOADS_FILE="$BACKUP_DIR/uploads_${TIMESTAMP}.tar.gz"

log "Dumping database $POSTGRES_DB from $DB_CONTAINER"
# pipefail makes a pg_dump failure fail the pipeline; the partial file is removed.
if ! docker exec "$DB_CONTAINER" pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > "$DB_FILE"; then
    rm -f "$DB_FILE"
    echo "ERROR: database backup failed" >&2
    exit 1
fi

log "Archiving volume $UPLOADS_VOLUME"
# The archive is streamed to stdout and written here, so the file belongs to the deploy user
# (umask above) rather than to root inside the throwaway container.
if ! docker run --rm --quiet -v "$UPLOADS_VOLUME:/uploads:ro" alpine:3.20 \
    tar czf - -C /uploads . > "$UPLOADS_FILE"; then
    rm -f "$UPLOADS_FILE"
    echo "ERROR: uploads backup failed" >&2
    exit 1
fi

log "Created $(du -h "$DB_FILE" | cut -f1)  $DB_FILE"
log "Created $(du -h "$UPLOADS_FILE" | cut -f1)  $UPLOADS_FILE"

log "Deleting backups older than $RETENTION_DAYS days"
find "$BACKUP_DIR" -maxdepth 1 -type f \( -name 'db_*.sql.gz' -o -name 'uploads_*.tar.gz' \) \
    -mtime +"$RETENTION_DAYS" -print -delete

log "Backup complete ($(du -sh "$BACKUP_DIR" | cut -f1) in $BACKUP_DIR)"
