#!/usr/bin/env bash
# Runs on the CI runner (in this checkout) before each offloaded job, after
# locked dependencies are installed. Keeps the runner's own shared test
# database bootstrapped and at the current migration head.
set -euo pipefail
cd "$(dirname "$0")/../../backend"
export DATABASE_URL="${TEST_DATABASE_URL:?TEST_DATABASE_URL required on the runner}"
.venv/bin/python - <<'PY'
import os

import psycopg

from scripts.verify_bootstrap_schema import restore_snapshot

with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
    if connection.execute("SELECT count(*) FROM pg_tables WHERE schemaname = 'public'").fetchone() == (0,):
        restore_snapshot(connection)
PY
.venv/bin/alembic upgrade head >/dev/null
