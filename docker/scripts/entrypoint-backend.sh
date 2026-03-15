#!/bin/bash
set -e

# Run database migrations if enabled (default: true)
# On fresh Docker deployments, init-db.sh creates the schema from dumps
# and stamps alembic_version. Alembic then only runs incremental upgrades.
if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
  echo "Running database migrations..."
  if ! alembic upgrade head 2>&1; then
    echo "ERROR: Alembic migrations failed."
    echo "This may indicate a schema mismatch. Check database state and migration history."
    echo "To skip migrations, set RUN_MIGRATIONS=false"
    exit 1
  fi
fi

# If CMD args provided (e.g. worker command), run those instead of uvicorn
if [ $# -gt 0 ]; then
  exec "$@"
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8001}"
