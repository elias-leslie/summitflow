#!/bin/bash
set -euo pipefail

if [ $# -lt 3 ] || [ $# -gt 4 ]; then
    echo "Usage: bootstrap-testbed-runtime.sh <project-id> <frontend-port> <backend-port> [root-path]"
    exit 1
fi

PROJECT_ID="$1"
FRONTEND_PORT="$2"
BACKEND_PORT="$3"
ROOT_DIR="${4:-$HOME/projects/$PROJECT_ID}"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
BACKEND_APP_DIR="$BACKEND_DIR/app"
VENV_DIR="$BACKEND_DIR/.venv"
SYSTEMD_DIR="$HOME/.config/systemd/user"
FRONTEND_URL="${FRONTEND_URL:-http://localhost:${FRONTEND_PORT}}"
API_URL="$FRONTEND_URL"
PATH_PREFIX="$HOME/.local/bin:$VENV_DIR/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

log() {
    printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$*"
}

wait_for_http_ok() {
    local url="$1"
    local attempts="${2:-20}"
    local delay="${3:-0.5}"
    local i

    for i in $(seq 1 "$attempts"); do
        if curl -sf "$url" >/dev/null; then
            return 0
        fi
        sleep "$delay"
    done

    return 1
}

seed_reset_markers() {
    local db_env="${PROJECT_ID^^}_DB_URL"
    local db_url="${!db_env:-}"
    [ -n "$db_url" ] || return 0

    "$VENV_DIR/bin/python" - <<'PY'
from __future__ import annotations

import os

import psycopg

project_id = os.environ["PROJECT_ID"]
db_env = f"{project_id.upper()}_DB_URL"
db_url = os.environ.get(db_env)
if not db_url:
    raise SystemExit(0)

with psycopg.connect(db_url) as conn, conn.cursor() as cur:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS reset_markers (
            label TEXT PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'reset_markers'
        ORDER BY ordinal_position
        """
    )
    columns = {row[0] for row in cur.fetchall()}

    if "label" in columns:
        cur.execute(
            """
            INSERT INTO reset_markers (label)
            VALUES (%s)
            ON CONFLICT (label) DO NOTHING
            """,
            (f"baseline:{project_id}",),
        )
    elif {"marker_id", "note"}.issubset(columns):
        cur.execute(
            """
            INSERT INTO reset_markers (marker_id, note)
            VALUES (%s, %s)
            ON CONFLICT (marker_id) DO NOTHING
            """,
            (f"baseline:{project_id}", "Runtime shell baseline"),
        )
    conn.commit()
PY
}

ensure_testbed_database() {
    local db_env="${PROJECT_ID^^}_DB_URL"
    local db_url="${!db_env:-}"
    local admin_url="${POSTGRES_ADMIN_URL:-${DATABASE_ADMIN_URL:-}}"
    [ -n "$db_url" ] || return 0
    [ -n "$admin_url" ] || return 0

    export PROJECT_ID TESTBED_DB_URL="$db_url" TESTBED_DB_ADMIN_URL="$admin_url"
    "$VENV_DIR/bin/python" - <<'PY'
from __future__ import annotations

import os
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg import sql

project_id = os.environ["PROJECT_ID"]
db_url = os.environ["TESTBED_DB_URL"]
admin_url = os.environ["TESTBED_DB_ADMIN_URL"]

db_parts = urlsplit(db_url)
db_name = db_parts.path.lstrip("/")
app_user = db_parts.username
if not db_name or not app_user:
    raise SystemExit(0)

admin_parts = urlsplit(admin_url)
maintenance_db = admin_parts.path.lstrip("/") or "postgres"
if maintenance_db != "postgres":
    admin_url = urlunsplit(admin_parts._replace(path="/postgres"))

with psycopg.connect(admin_url, autocommit=True) as conn, conn.cursor() as cur:
    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
    exists = cur.fetchone() is not None
    if not exists:
        cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db_name)))

with psycopg.connect(admin_url, autocommit=True) as conn, conn.cursor() as cur:
    cur.execute(sql.SQL("GRANT ALL PRIVILEGES ON DATABASE {} TO {}").format(sql.Identifier(db_name), sql.Identifier(app_user)))

with psycopg.connect(
    urlunsplit(admin_parts._replace(path=f"/{db_name}")),
    autocommit=True,
) as conn, conn.cursor() as cur:
    cur.execute(sql.SQL("GRANT USAGE, CREATE ON SCHEMA public TO {}").format(sql.Identifier(app_user)))
    cur.execute(
        sql.SQL("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO {}").format(sql.Identifier(app_user))
    )
    cur.execute(
        sql.SQL("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO {}").format(sql.Identifier(app_user))
    )
    cur.execute(
        sql.SQL("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON FUNCTIONS TO {}").format(sql.Identifier(app_user))
    )
PY
}

require_bin() {
    command -v "$1" >/dev/null 2>&1 || {
        echo "Missing required command: $1"
        exit 1
    }
}

write_file_if_changed() {
    local target="$1"
    local tmp
    tmp="$(mktemp)"
    cat >"$tmp"
    mkdir -p "$(dirname "$target")"
    if [ ! -f "$target" ] || ! cmp -s "$tmp" "$target"; then
        mv "$tmp" "$target"
    else
        rm -f "$tmp"
    fi
}

require_bin python3
require_bin systemctl

mkdir -p "$BACKEND_APP_DIR" "$FRONTEND_DIR" "$ROOT_DIR/.st" "$SYSTEMD_DIR"

write_file_if_changed "$ROOT_DIR/.gitignore" <<EOF
.index.yaml
.env
.env.local
.env*.local
.dev-tools/
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
htmlcov/
node_modules/
.next/
frontend/.next/
*.tsbuildinfo
.summitflow/
backend/.venv/
backend/__pycache__/
backend/app/__pycache__/
frontend/__pycache__/
EOF

write_file_if_changed "$ROOT_DIR/.st/.gitignore" <<'EOF'
*
!.gitignore
snapshots/
EOF

write_file_if_changed "$ROOT_DIR/.st/services.yaml" <<EOF
services:
  backend:
    name: backend
    command: "$VENV_DIR/bin/uvicorn app.main:app --host 0.0.0.0 --port {port}"
    port: $BACKEND_PORT
    cwd: backend
  frontend:
    name: frontend
    command: "$VENV_DIR/bin/uvicorn server:app --host 0.0.0.0 --port {port}"
    port: $FRONTEND_PORT
    cwd: frontend
EOF

write_file_if_changed "$BACKEND_DIR/requirements.txt" <<EOF
fastapi
uvicorn[standard]
psycopg[binary]
EOF

write_file_if_changed "$BACKEND_APP_DIR/__init__.py" <<'EOF'
# Testbed backend package marker.
EOF

write_file_if_changed "$BACKEND_APP_DIR/main.py" <<'EOF'
from __future__ import annotations

import os
from datetime import UTC, datetime

from fastapi import FastAPI

try:
    import psycopg
except Exception:  # pragma: no cover - runtime dependency installed by bootstrap
    psycopg = None

PROJECT_ID = os.getenv("PROJECT_ID", "testbed")
DB_ENV = f"{PROJECT_ID.upper()}_DB_URL"
DB_URL = os.getenv(DB_ENV)

app = FastAPI(title=f"{PROJECT_ID} backend")


def _db_ok() -> bool:
    if not DB_URL or psycopg is None:
        return False
    try:
        with psycopg.connect(DB_URL) as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
            return cur.fetchone() == (1,)
    except Exception:
        return False


@app.get("/health")
async def health() -> dict[str, object]:
    return {
        "project_id": PROJECT_ID,
        "status": "ok",
        "db_configured": bool(DB_URL),
        "db_ok": _db_ok(),
        "time": datetime.now(UTC).isoformat(),
    }


@app.get("/api/info")
async def info() -> dict[str, object]:
    return {
        "project_id": PROJECT_ID,
        "frontend_url": os.getenv("FRONTEND_URL"),
        "api_url": os.getenv("API_URL"),
        "db_env": DB_ENV,
        "db_configured": bool(DB_URL),
        "db_ok": _db_ok(),
    }
EOF

write_file_if_changed "$FRONTEND_DIR/server.py" <<'EOF'
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

PROJECT_ID = os.getenv("PROJECT_ID", "testbed")
API_URL = os.getenv("API_URL", "").rstrip("/")
BACKEND_URL = os.getenv("BACKEND_URL", "").rstrip("/")
INFO_URL = f"{BACKEND_URL}/api/info" if BACKEND_URL else ""

app = FastAPI(title=f"{PROJECT_ID} frontend")


@app.get("/health")
async def health() -> dict[str, str]:
    return {
        "project_id": PROJECT_ID,
        "status": "ok",
        "time": datetime.now(UTC).isoformat(),
    }


def _fetch_backend_info() -> dict[str, object]:
    if not INFO_URL:
        return {
            "project_id": PROJECT_ID,
            "status": "backend_unconfigured",
            "frontend_url": API_URL or None,
            "api_url": None,
            "db_configured": False,
            "db_ok": False,
        }

    try:
        with urlopen(INFO_URL, timeout=5.0) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError):
        return {
            "project_id": PROJECT_ID,
            "status": "backend_unreachable",
            "frontend_url": API_URL or None,
            "api_url": INFO_URL,
            "db_configured": False,
            "db_ok": False,
        }


@app.get("/api/info")
async def proxy_info() -> JSONResponse:
    return JSONResponse(_fetch_backend_info())


@app.get("/", response_class=HTMLResponse)
async def home() -> str:
    info = _fetch_backend_info()
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{PROJECT_ID} testbed</title>
    <style>
      body {{
        font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
        margin: 0;
        min-height: 100vh;
        display: grid;
        place-items: center;
        background: linear-gradient(135deg, #111827 0%, #1f2937 100%);
        color: #f9fafb;
      }}
      main {{
        width: min(720px, 92vw);
        border: 1px solid rgba(255,255,255,0.15);
        border-radius: 18px;
        padding: 28px;
        background: rgba(17,24,39,0.78);
        box-shadow: 0 18px 50px rgba(0,0,0,0.35);
      }}
      a {{ color: #93c5fd; }}
      code {{
        display: inline-block;
        padding: 2px 6px;
        border-radius: 6px;
        background: rgba(255,255,255,0.08);
      }}
    </style>
  </head>
  <body>
    <main>
      <h1>{PROJECT_ID} testbed shell</h1>
      <p>Public frontend for the SummitFlow proving-ground project.</p>
      <p>API: <a href="/api/info">/api/info</a></p>
      <p>Database: <code>{"connected" if info.get("db_ok") else "unavailable"}</code></p>
      <p>Health: <code>/health</code></p>
    </main>
  </body>
</html>"""
EOF

if [ ! -x "$VENV_DIR/bin/python" ]; then
    log "Creating backend venv..."
    python3 -m venv "$VENV_DIR"
fi

log "Installing backend runtime packages..."
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet -r "$BACKEND_DIR/requirements.txt"

export PROJECT_ID
if [ -f "$HOME/.env.local" ]; then
    set -a
    . "$HOME/.env.local"
    set +a
fi
log "Ensuring database exists with testbed grants..."
ensure_testbed_database

log "Seeding reset markers..."
seed_reset_markers

write_file_if_changed "$SYSTEMD_DIR/${PROJECT_ID}-backend.service" <<EOF
[Unit]
Description=${PROJECT_ID} Backend (Testbed shell)
After=network.target

[Service]
Type=simple
WorkingDirectory=$BACKEND_DIR
Environment="PATH=$PATH_PREFIX"
Environment="HOME=%h"
Environment="PROJECT_ID=$PROJECT_ID"
Environment="FRONTEND_URL=$FRONTEND_URL"
Environment="API_URL=$API_URL"
EnvironmentFile=-%h/.env.local
Environment="PYTHONUNBUFFERED=1"
ExecStart=$VENV_DIR/bin/uvicorn app.main:app --host 0.0.0.0 --port $BACKEND_PORT
Restart=always
RestartSec=5
KillMode=control-group
TimeoutStopSec=20
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${PROJECT_ID}-backend

[Install]
WantedBy=default.target
EOF

write_file_if_changed "$SYSTEMD_DIR/${PROJECT_ID}-frontend.service" <<EOF
[Unit]
Description=${PROJECT_ID} Frontend (Testbed shell)
After=network.target ${PROJECT_ID}-backend.service
Wants=${PROJECT_ID}-backend.service

[Service]
Type=simple
WorkingDirectory=$FRONTEND_DIR
Environment="PATH=$PATH_PREFIX"
Environment="HOME=%h"
Environment="PROJECT_ID=$PROJECT_ID"
Environment="API_URL=$API_URL"
Environment="BACKEND_URL=http://127.0.0.1:$BACKEND_PORT"
EnvironmentFile=-%h/.env.local
Environment="PYTHONUNBUFFERED=1"
ExecStart=$VENV_DIR/bin/uvicorn server:app --host 0.0.0.0 --port $FRONTEND_PORT
Restart=always
RestartSec=5
KillMode=control-group
TimeoutStopSec=20
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${PROJECT_ID}-frontend

[Install]
WantedBy=default.target
EOF

log "Reloading systemd user units..."
systemctl --user daemon-reload
systemctl --user enable --now "${PROJECT_ID}-backend.service" "${PROJECT_ID}-frontend.service" >/dev/null
systemctl --user restart "${PROJECT_ID}-backend.service" "${PROJECT_ID}-frontend.service"

log "Verifying local health..."
wait_for_http_ok "http://localhost:${BACKEND_PORT}/health"
wait_for_http_ok "http://localhost:${FRONTEND_PORT}/health"

log "Regenerating project index..."
curl -sf -X POST "http://localhost:8001/api/projects/${PROJECT_ID}/explorer/regenerate-index" >/dev/null || true

log "Bootstrap complete for ${PROJECT_ID} (frontend ${FRONTEND_PORT}, backend ${BACKEND_PORT})"
