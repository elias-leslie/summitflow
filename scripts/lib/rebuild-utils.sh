#!/bin/bash
#
# Rebuild Utilities — shared by rebuild.sh, restart.sh, etc.
# Service discovery is dynamic: compose file is the single source of truth.
#
export GREEN='\033[0;32m' YELLOW='\033[1;33m' RED='\033[0;31m' BLUE='\033[0;34m' NC='\033[0m'
export IS_WORKTREE=false WORKTREE_TASK_ID=""
if [ -z "$PROJECT_DIR" ]; then
    PROJECT_DIR=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
    if [[ "$PROJECT_DIR" == *"/worktrees/"* ]]; then
        IS_WORKTREE=true
        PROJECT_NAME=$(echo "$PROJECT_DIR" | sed -E 's|.*/worktrees/([^/]+)/.*|\1|')
        WORKTREE_TASK_ID=$(echo "$PROJECT_DIR" | sed -E 's|.*/worktrees/[^/]+/([^/]+).*|\1|')
        [ "$WORKTREE_TASK_ID" = "$PROJECT_DIR" ] && WORKTREE_TASK_ID=""
    else
        PROJECT_NAME=$(basename "$PROJECT_DIR")
    fi
fi
export PROJECT_DIR PROJECT_NAME IS_WORKTREE WORKTREE_TASK_ID

# ─── Sanitize environment for Docker Compose ──────────────────
# Unset vars that leak from .env.local / systemd and conflict with
# container-level PORT, HATCHET_CLIENT_TOKEN, etc.
unset PORT HATCHET_CLIENT_TOKEN HATCHET_COOKIE_SECRET \
      DATABASE_URL REDIS_URL AGENT_HUB_DB_URL \
      AGENT_HUB_REDIS_URL PORTFOLIO_DB_URL INTERNAL_SERVICE_SECRET \
      AGENT_HUB_SECRET_KEY 2>/dev/null || true

# ─── Compose paths ──────────────────────────────────────────────
_COMPOSE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/docker/compose"
_COMPOSE_FILE="$_COMPOSE_DIR/docker-compose.yml"
_COMPOSE_DEV_FILE="$_COMPOSE_DIR/docker-compose.dev.yml"
export _COMPOSE_DIR _COMPOSE_FILE _COMPOSE_DEV_FILE

# ─── Dynamic service discovery from compose ─────────────────────
# The compose file is the single source of truth. No hardcoded service names.
# Convention: {prefix}-api, {prefix}-web, {prefix}-worker, or standalone (e.g., monkey-fight)

# Map project name → compose service prefix (only projects that differ from their prefix)
_project_to_prefix() {
    case "$1" in
        portfolio-ai) echo "portfolio" ;;
        *)            echo "$1" ;;
    esac
}

# List all compose services for a project, from running containers (no env vars needed)
_compose_all_services() {
    [ ! -f "$_COMPOSE_FILE" ] && return
    local prefix
    prefix=$(_project_to_prefix "${1:-$PROJECT_NAME}")
    # Query running containers' service labels — no config parsing, no env vars required
    docker ps --filter "label=com.docker.compose.project=summitflow-stack" \
              --format '{{.Label "com.docker.compose.service"}}' 2>/dev/null \
        | grep "^${prefix}" | sort -u | tr '\n' ' '
}

_compose_api_service() {
    _compose_all_services "$@" | tr ' ' '\n' | grep -E '\-api$' | head -1
}

_compose_web_service() {
    local services
    services=$(_compose_all_services "$@")
    local web
    web=$(echo "$services" | tr ' ' '\n' | grep -E '\-web$' | head -1)
    # Standalone services (e.g. monkey-fight) have no -web suffix
    if [ -z "$web" ]; then
        web=$(echo "$services" | tr ' ' '\n' | head -1)
    fi
    echo "$web"
}

# Get published port for a compose service from running container
_compose_service_port() {
    local svc="$1"
    docker compose -f "$_COMPOSE_FILE" port "$svc" "${2:-8001}" 2>/dev/null | cut -d: -f2
}

# Resolve ports from running containers
# Publishers format: [{0.0.0.0 8001 8001 tcp} ...]
_resolve_ports() {
    local api_svc web_svc port
    api_svc=$(_compose_api_service)
    web_svc=$(_compose_web_service)
    if [ -n "$api_svc" ]; then
        port=$(docker compose -f "$_COMPOSE_FILE" ps --format '{{.Publishers}}' "$api_svc" 2>/dev/null \
            | grep -oP '\{0\.0\.0\.0 \K[0-9]+' | head -1)
        [ -n "$port" ] && BACKEND_PORT="$port"
    fi
    if [ -n "$web_svc" ]; then
        port=$(docker compose -f "$_COMPOSE_FILE" ps --format '{{.Publishers}}' "$web_svc" 2>/dev/null \
            | grep -oP '\{0\.0\.0\.0 \K[0-9]+' | head -1)
        [ -n "$port" ] && FRONTEND_PORT="$port"
    fi
    export BACKEND_PORT="${BACKEND_PORT:-0}" FRONTEND_PORT="${FRONTEND_PORT:-0}"
    if [ "$BACKEND_PORT" = "0" ] || [ -z "$BACKEND_PORT" ]; then
        export HAS_BACKEND=false BACKEND_PORT=0
    fi
}

# ─── Systemd service mapping (legacy native mode) ───────────────
_resolve_systemd_services() {
    local prefix
    prefix=$(_project_to_prefix "$PROJECT_NAME")
    export SERVICE_PREFIX="$prefix"
    export BACKEND_SERVICE="${prefix}-backend"
    export FRONTEND_SERVICE="${prefix}-frontend"
    # Special cases that predate this convention
    [ "$PROJECT_NAME" = "terminal" ] && export BACKEND_SERVICE="summitflow-terminal" FRONTEND_SERVICE="summitflow-terminal-frontend"
    [ "$PROJECT_NAME" = "monkey-fight" ] && export FRONTEND_SERVICE="monkey-fight"
    export MANAGED_SERVICES="$BACKEND_SERVICE $FRONTEND_SERVICE"
}
_resolve_systemd_services

# ─── Runtime detection ───────────────────────────────────────────

detect_docker() {
    export RUNTIME_MODE="native" DOCKER_DEV=false DOCKER_IMAGE_STALE=false
    [ ! -f "$_COMPOSE_FILE" ] && return
    local running
    running=$(docker compose -f "$_COMPOSE_FILE" ps --status running -q 2>/dev/null)
    [ -z "$running" ] && return
    export RUNTIME_MODE="docker"

    # Resolve ports from compose config
    _resolve_ports

    # Detect dev overlay (any bind mount under /app/ = dev mode)
    local api_svc container
    api_svc=$(_compose_api_service)
    [ -z "$api_svc" ] && return
    container=$(docker compose -f "$_COMPOSE_FILE" ps -q "$api_svc" 2>/dev/null | head -1)
    [ -z "$container" ] && return
    if docker inspect "$container" --format '{{range .Mounts}}{{.Destination}}{{"\n"}}{{end}}' 2>/dev/null | grep -qE '^/app/.+'; then
        export DOCKER_DEV=true
    fi

    # Check if image is stale (infrastructure files changed since image was built)
    _detect_stale_image "$container"
}

# Check if Dockerfile or dependency files changed after the running image was built.
# Sets DOCKER_IMAGE_STALE=true if a rebuild is needed.
_detect_stale_image() {
    local container="$1"
    [ -z "$container" ] && return

    # Get image creation timestamp (epoch seconds)
    local image_id image_created
    image_id=$(docker inspect "$container" --format '{{.Image}}' 2>/dev/null)
    [ -z "$image_id" ] && return
    image_created=$(docker inspect "$image_id" --format '{{.Created}}' 2>/dev/null)
    [ -z "$image_created" ] && return
    local image_epoch
    image_epoch=$(date -d "$image_created" +%s 2>/dev/null) || return

    # Infrastructure files that require an image rebuild when changed
    local infra_files=(
        "docker/backend.Dockerfile"
        "docker/frontend.Dockerfile"
        "pyproject.toml"
        "uv.lock"
        "package.json"
        "pnpm-lock.yaml"
        "requirements.txt"
        "requirements-dev.txt"
    )

    for f in "${infra_files[@]}"; do
        local fpath="$PROJECT_DIR/$f"
        [ -f "$fpath" ] || continue
        local file_epoch
        file_epoch=$(stat -c %Y "$fpath" 2>/dev/null) || continue
        if [ "$file_epoch" -gt "$image_epoch" ]; then
            export DOCKER_IMAGE_STALE=true
            log_warn "Image stale: $f changed after image was built"
            return
        fi
    done
}

# ─── Docker operations ───────────────────────────────────────────

docker_build_and_recreate() {
    local services="$1"
    [ -z "$services" ] && { log_error "No compose services for $PROJECT_NAME"; return 1; }

    # Use dev overlay for build only (has build: context directives)
    local build_files=("-f" "$_COMPOSE_FILE")
    [ -f "$_COMPOSE_DEV_FILE" ] && build_files+=("-f" "$_COMPOSE_DEV_FILE")

    log "Building images for: $services"
    # --no-cache ensures source changes are always picked up (COPY layers don't
    # invalidate on content changes when the build context is large)
    # shellcheck disable=SC2086
    docker compose "${build_files[@]}" build --no-cache $services 2>&1 | tail -20
    [ ${PIPESTATUS[0]} -ne 0 ] && { log_error "Build failed"; return 1; }
    log_success "Images built"

    # Recreate with prod compose only (dev overlay changes CMD/volumes)
    log "Recreating containers..."
    # shellcheck disable=SC2086
    docker compose -f "$_COMPOSE_FILE" up -d --no-deps $services 2>&1
    log_success "Containers recreated"
}

docker_restart_services() {
    local services="$1"
    [ -z "$services" ] && return 0
    log "Restarting: $services"
    # shellcheck disable=SC2086
    docker compose -f "$_COMPOSE_FILE" restart $services 2>&1
    log_success "Restarted"
}

docker_run_migration() {
    local api_svc
    api_svc=$(_compose_api_service)
    [ -z "$api_svc" ] && return 0
    log "Running migrations ($api_svc)..."
    docker compose -f "$_COMPOSE_FILE" exec -T "$api_svc" alembic upgrade head 2>&1 | tail -5
    [ ${PIPESTATUS[0]} -eq 0 ] && log_success "Migrations applied" || log_warn "Migration returned non-zero (may already be up to date)"
}

# ─── Logging ─────────────────────────────────────────────────────
log() { printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$*"; }
log_success() { printf "${GREEN}[%s] ✓ %s${NC}\n" "$(date '+%H:%M:%S')" "$*"; }
log_warn() { printf "${YELLOW}[%s] ⚠ %s${NC}\n" "$(date '+%H:%M:%S')" "$*"; }
log_error() { printf "${RED}[%s] ✗ %s${NC}\n" "$(date '+%H:%M:%S')" "$*"; }
log_info() { printf "${BLUE}[%s] ℹ %s${NC}\n" "$(date '+%H:%M:%S')" "$*"; }

# ─── Systemd functions ───────────────────────────────────────────
service_exists() { systemctl --user cat "$1" &>/dev/null; }
restart_service() { local s="$1"; service_exists "$s" || { log_info "$s not found"; return 0; }; log "Restarting $s..."; systemctl --user restart "$s" && log_success "$s restarted" || { log_error "$s failed"; return 1; }; }
clear_build_cache() { local d="$PROJECT_DIR/frontend"; [ ! -d "$d" ] && d="$PROJECT_DIR"; rm -rf "$d/.next" "$d/dist" "$d/node_modules/.vite" 2>/dev/null; log_success "Cache cleared"; }
clear_nextjs_cache() { clear_build_cache; }
build_frontend() { local d="$PROJECT_DIR/frontend"; [ ! -d "$d" ] && d="$PROJECT_DIR"; cd "$d" || return 1; log "Building..."; pnpm build 2>&1 | tail -15 && log_success "Built" || { log_error "Build failed"; return 1; }; }
verify_backend() { local p="${1:-$BACKEND_PORT}"; [ "$p" -eq 0 ] 2>/dev/null && return 0; log "Checking backend ($p)..."; for i in $(seq 1 10); do curl -s "http://localhost:$p/health" &>/dev/null && { log_success "Backend OK"; return 0; }; sleep 1; done; log_error "Backend failed"; return 1; }
verify_frontend() { local p="${1:-$FRONTEND_PORT}"; [ "$p" -eq 0 ] 2>/dev/null && return 0; log "Checking frontend ($p)..."; for i in $(seq 1 30); do local s=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 "http://localhost:$p/" 2>/dev/null); [[ "$s" =~ ^(2|3)[0-9][0-9]$ ]] && { log_success "Frontend OK ($s)"; return 0; }; sleep 1; done; log_error "Frontend failed"; return 1; }

export -f log log_success log_warn log_error log_info
export -f service_exists restart_service clear_build_cache clear_nextjs_cache build_frontend verify_backend verify_frontend
export -f detect_docker _detect_stale_image _project_to_prefix _compose_all_services _compose_api_service _compose_web_service _compose_service_port _resolve_ports docker_build_and_recreate docker_restart_services docker_run_migration
