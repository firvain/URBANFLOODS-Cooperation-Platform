#!/usr/bin/env bash
# Apply database migrations, then hand over to the container command (the API server by default).
set -euo pipefail

alembic upgrade head

exec "$@"
