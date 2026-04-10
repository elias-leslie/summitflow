#!/bin/bash
set -e

stamp_imported_schema_if_needed() {
  set +e
  python - <<'PY'
import os
import sys

from sqlalchemy import create_engine, text

database_url = os.environ.get("DATABASE_URL")
if not database_url:
    sys.exit(0)

engine = create_engine(database_url)
with engine.connect() as conn:
    version_table = conn.execute(text("SELECT to_regclass('public.alembic_version')")).scalar()
    if not version_table:
        sys.exit(0)

    version_count = conn.execute(text("SELECT COUNT(*) FROM public.alembic_version")).scalar_one()
    imported_table_count = conn.execute(
        text(
            """
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_type = 'BASE TABLE'
              AND table_name != 'alembic_version'
            """
        )
    ).scalar_one()
    if version_count == 0 and imported_table_count > 0:
        sys.exit(2)

sys.exit(0)
PY
  local stamp_status=$?
  set -e

  if [ "$stamp_status" -eq 2 ]; then
    echo "Imported schema has an empty alembic_version table; stamping Alembic heads..."
    alembic stamp heads
  elif [ "$stamp_status" -ne 0 ]; then
    echo "WARNING: Could not inspect imported schema stamp state; continuing with Alembic upgrade."
  fi
}

# Run database migrations if enabled (default: true)
# On fresh Docker deployments, init-db.sh creates the schema from dumps
# with an empty alembic_version table. Stamp imported schemas before upgrade
# so Alembic only runs incremental migrations.
if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
  stamp_imported_schema_if_needed
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
