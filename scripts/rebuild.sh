#!/bin/bash
#
# rebuild.sh <project> — rebuild and restart a project
#
# Usage:
#   rebuild.sh summitflow       # Rebuild summitflow (frontend + backend + worker)
#   rebuild.sh agent-hub        # Rebuild agent-hub
#   rebuild.sh terminal         # Rebuild terminal
#   rebuild.sh portfolio-ai     # Rebuild portfolio-ai
#   rebuild.sh monkey-fight     # Rebuild monkey-fight
#   rebuild.sh                  # No args = show available projects
#
# Always rebuilds everything (frontend build + backend restart + worker restart).
# Project name is required — no auto-detection from cwd.
#

set -eo pipefail

# ─── Colors & logging ────────────────────────────────────────────
GREEN='\033[0;32m' RED='\033[0;31m' YELLOW='\033[1;33m' NC='\033[0m'
log()         { printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$*"; }
log_success() { printf "${GREEN}[%s] ✓ %s${NC}\n" "$(date '+%H:%M:%S')" "$*"; }
log_error()   { printf "${RED}[%s] ✗ %s${NC}\n" "$(date '+%H:%M:%S')" "$*"; }
log_warn()    { printf "${YELLOW}[%s] ⚠ %s${NC}\n" "$(date '+%H:%M:%S')" "$*"; }

# ─── Project registry ────────────────────────────────────────────
# Each project: root_dir, backend_service, frontend_service, worker_services,
#               backend_port, frontend_port, backend_dir, frontend_dir
declare -A PROJECTS
PROJECTS=(
    [summitflow]="/home/kasadis/summitflow|summitflow-backend.service|summitflow-frontend.service|summitflow-hatchet-worker.service|8001|3001|backend|frontend"
    [agent-hub]="/home/kasadis/agent-hub|agent-hub-backend.service|agent-hub-frontend.service|agent-hub-hatchet-worker.service|8003|3003|backend|frontend"
    [portfolio-ai]="/home/kasadis/portfolio-ai|portfolio-backend.service|portfolio-frontend.service|portfolio-hatchet-worker.service|8000|3000|backend|frontend"
    [terminal]="/home/kasadis/terminal|summitflow-terminal.service|summitflow-terminal-frontend.service||8002|3002|.|frontend"
    [monkey-fight]="/home/kasadis/monkey-fight||monkey-fight.service||0|4001|.|."
)

parse_project() {
    IFS='|' read -r ROOT_DIR BACKEND_SVC FRONTEND_SVC WORKER_SVCS BACKEND_PORT FRONTEND_PORT BACKEND_SUBDIR FRONTEND_SUBDIR <<< "${PROJECTS[$1]}"
    BACKEND_DIR="$ROOT_DIR/$BACKEND_SUBDIR"
    FRONTEND_DIR="$ROOT_DIR/$FRONTEND_SUBDIR"
    if [ "$BACKEND_SUBDIR" = "." ]; then BACKEND_DIR="$ROOT_DIR"; fi
    if [ "$FRONTEND_SUBDIR" = "." ]; then FRONTEND_DIR="$ROOT_DIR"; fi
}

show_projects() {
    echo "Usage: rebuild.sh <project>"
    echo ""
    echo "Available projects:"
    for p in summitflow agent-hub portfolio-ai terminal monkey-fight; do
        [ -n "${PROJECTS[$p]}" ] || continue
        IFS='|' read -r root _ _ _ bp fp _ _ <<< "${PROJECTS[$p]}"
        printf "  %-15s %s" "$p" "$root"
        [ "$bp" != "0" ] && printf "  (:%s/:%s)" "$bp" "$fp" || printf "  (:%s)" "$fp"
        echo ""
    done
}

# ─── Core operations ─────────────────────────────────────────────

port_pids() { ss -ltnp "( sport = :$1 )" 2>/dev/null | grep -oP 'pid=\K[0-9]+' | sort -u; }

kill_port() {
    local port="$1" pids
    pids=$(port_pids "$port")
    [ -z "$pids" ] && return 0
    log_warn "Clearing port $port listeners"
    echo "$pids" | xargs -r kill 2>/dev/null || true
    for _ in $(seq 1 10); do
        [ -z "$(port_pids "$port")" ] && return 0
        sleep 1
    done
    echo "$pids" | xargs -r kill -9 2>/dev/null || true
    sleep 1
}

restart_svc() {
    local svc="$1" port="${2:-}"
    [ -z "$svc" ] && return 0
    systemctl --user cat "$svc" &>/dev/null || { log_warn "$svc not found, skipping"; return 0; }
    log "Restarting $svc..."
    systemctl --user stop "$svc" 2>/dev/null || true
    [ -n "$port" ] && [ "$port" -gt 0 ] 2>/dev/null && kill_port "$port"
    systemctl --user start "$svc" && log_success "$svc" || { log_error "$svc failed"; return 1; }
}

ensure_infra() {
    local compose_dir="/home/kasadis/summitflow/docker/compose"
    local compose_file="$compose_dir/docker-compose.yml"
    [ ! -f "$compose_file" ] && return 0

    # Check if postgres, redis, hatchet are running
    local missing=false
    for svc in postgres redis hatchet; do
        if ! docker ps --filter "label=com.docker.compose.project=summitflow-stack" \
                       --filter "label=com.docker.compose.service=$svc" \
                       --format '{{.ID}}' 2>/dev/null | grep -q .; then
            missing=true
            break
        fi
    done
    [ "$missing" = false ] && return 0

    log "Starting Docker infra (postgres, redis, hatchet)..."

    # Sanitize env to avoid Docker Compose conflicts
    unset PORT HATCHET_CLIENT_TOKEN HATCHET_COOKIE_SECRET \
          DATABASE_URL REDIS_URL AGENT_HUB_DB_URL \
          AGENT_HUB_REDIS_URL PORTFOLIO_DB_URL INTERNAL_SERVICE_SECRET \
          AGENT_HUB_SECRET_KEY 2>/dev/null || true

    docker compose --env-file "$compose_dir/.env" -f "$compose_file" \
        up -d postgres redis hatchet-migrate hatchet-setup-config hatchet 2>&1

    # Wait for readiness
    for _ in $(seq 1 45); do
        if pg_isready -h localhost -p 5432 -U admin >/dev/null 2>&1 && \
           curl -sf http://localhost:8888/ready >/dev/null 2>&1; then
            log_success "Docker infra ready"
            return 0
        fi
        sleep 2
    done
    log_error "Docker infra not ready after 90s"
    return 1
}

run_migrations() {
    [ -z "$BACKEND_SVC" ] && return 0
    [ ! -f "$BACKEND_DIR/alembic.ini" ] && return 0
    local venv="$BACKEND_DIR/.venv"
    [ ! -d "$venv" ] && venv="$ROOT_DIR/.venv"
    [ ! -x "$venv/bin/alembic" ] && return 0

    log "Running migrations..."
    (
        cd "$BACKEND_DIR" &&
        env -u DATABASE_URL -u REDIS_URL -u AGENT_HUB_DB_URL -u AGENT_HUB_REDIS_URL \
            -u PORTFOLIO_DB_URL -u PORTFOLIO_AI_DB_URL -u HATCHET_CLIENT_TOKEN \
            "$venv/bin/alembic" upgrade head
    ) 2>&1 | tail -5
    [ ${PIPESTATUS[0]} -eq 0 ] && log_success "Migrations applied" || log_warn "Migration returned non-zero"
}

build_frontend() {
    [ ! -f "$FRONTEND_DIR/package.json" ] && return 0
    log "Building frontend..."
    rm -rf "$FRONTEND_DIR/.next" "$FRONTEND_DIR/dist" 2>/dev/null || true

    # Install deps if missing
    if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
        log "Installing dependencies..."
        (cd "$FRONTEND_DIR" && pnpm install) 2>&1 | tail -10
    fi

    (cd "$FRONTEND_DIR" && pnpm build) 2>&1 | tail -10
    [ ${PIPESTATUS[0]} -eq 0 ] && log_success "Frontend built" || { log_error "Frontend build failed"; return 1; }
}

sync_seeds() {
    local export_script="$BACKEND_DIR/scripts/export_seeds.py"
    [ ! -f "$export_script" ] && return 0
    local venv="$BACKEND_DIR/.venv"
    [ ! -x "$venv/bin/python" ] && return 0
    log "Syncing seed data..."
    (cd "$BACKEND_DIR" && env -u DATABASE_URL -u REDIS_URL "$venv/bin/python" -m scripts.export_seeds) 2>&1 | tail -5
    [ ${PIPESTATUS[0]} -eq 0 ] && log_success "Seed data synced" || true
}

verify_health() {
    local errors=0
    if [ -n "$BACKEND_SVC" ] && [ "$BACKEND_PORT" -gt 0 ] 2>/dev/null; then
        log "Checking backend (:$BACKEND_PORT)..."
        local ok=false
        for _ in $(seq 1 15); do
            curl -sf "http://localhost:$BACKEND_PORT/health" &>/dev/null && { ok=true; break; }
            sleep 1
        done
        [ "$ok" = true ] && log_success "Backend OK" || { log_error "Backend not healthy"; ((errors++)); }
    fi
    if [ "$FRONTEND_PORT" -gt 0 ] 2>/dev/null; then
        log "Checking frontend (:$FRONTEND_PORT)..."
        local ok=false
        for _ in $(seq 1 30); do
            local code
            code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 "http://localhost:$FRONTEND_PORT/" 2>/dev/null)
            [[ "$code" =~ ^(2|3)[0-9][0-9]$ ]] && { ok=true; break; }
            sleep 1
        done
        [ "$ok" = true ] && log_success "Frontend OK ($code)" || { log_error "Frontend not healthy"; ((errors++)); }
    fi
    return $errors
}

# ─── Status mode ─────────────────────────────────────────────────

show_status() {
    local project="$1"
    parse_project "$project"
    local all_active=true
    printf "  %-15s" "$project"
    for svc in $BACKEND_SVC $FRONTEND_SVC $WORKER_SVCS; do
        [ -z "$svc" ] && continue
        local state
        state=$(systemctl --user is-active "$svc" 2>/dev/null || echo "stopped")
        if [ "$state" = "active" ]; then
            printf " ${GREEN}%s${NC}" "$svc"
        else
            printf " ${RED}%s(%s)${NC}" "$svc" "$state"
            all_active=false
        fi
    done
    echo ""
    $all_active
}

# ─── Main ─────────────────────────────────────────────────────────

# Handle --status mode
if [ "${1:-}" = "--status" ]; then
    PROJECT="${2:-}"
    if [ -n "$PROJECT" ]; then
        if [ -z "${PROJECTS[$PROJECT]}" ]; then
            echo "Unknown project: $PROJECT"
            echo ""
            show_projects
            exit 1
        fi
        show_status "$PROJECT"
        exit $?
    fi
    # All projects
    errors=0
    for p in summitflow agent-hub portfolio-ai terminal monkey-fight; do
        show_status "$p" || ((errors++))
    done
    exit $errors
fi

PROJECT="${1:-}"

if [ -z "$PROJECT" ] || [ "$PROJECT" = "--help" ] || [ "$PROJECT" = "-h" ]; then
    show_projects
    exit 0
fi

if [ -z "${PROJECTS[$PROJECT]}" ]; then
    echo "Unknown project: $PROJECT"
    echo ""
    show_projects
    exit 1
fi

parse_project "$PROJECT"
start_time=$(date +%s)
errors=0

echo ""
echo "========================================"
echo "Rebuilding $PROJECT"
echo "========================================"
echo ""

# 1. Ensure Docker infra
ensure_infra || ((errors++))

# 2. Build frontend
build_frontend || ((errors++))

# 3. Run migrations
run_migrations || ((errors++))

# 4. Restart all services
[ -n "$BACKEND_SVC" ] && { restart_svc "$BACKEND_SVC" "$BACKEND_PORT" || ((errors++)); }
for svc in $WORKER_SVCS; do
    [ -n "$svc" ] && { restart_svc "$svc" || ((errors++)); }
done
restart_svc "$FRONTEND_SVC" "$FRONTEND_PORT" || ((errors++))

# 5. Verify health
echo ""
verify_health || ((errors++))

# 6. Post-rebuild sync
if [ $errors -eq 0 ]; then
    sync_seeds
    # Regenerate project index for summitflow
    if [ "$PROJECT" = "summitflow" ]; then
        curl -s -X POST "http://localhost:8001/api/projects/$PROJECT/explorer/regenerate-index" >/dev/null 2>&1 || true
    fi
fi

duration=$(( $(date +%s) - start_time ))
echo ""
echo "========================================"
if [ $errors -eq 0 ]; then
    log_success "Rebuild complete (${duration}s)"
else
    log_error "Rebuild completed with $errors error(s) (${duration}s)"
fi
echo "========================================"
echo ""
echo "URLs:"
[ "$BACKEND_PORT" -gt 0 ] 2>/dev/null && echo "  Backend:  http://localhost:$BACKEND_PORT"
[ "$FRONTEND_PORT" -gt 0 ] 2>/dev/null && echo "  Frontend: http://localhost:$FRONTEND_PORT"
echo ""

exit $errors
