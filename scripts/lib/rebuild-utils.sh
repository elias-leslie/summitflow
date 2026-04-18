#!/bin/bash
#
# Rebuild Utilities — shared by rebuild.sh, restart.sh, etc.
# Service discovery is dynamic: compose file is the single source of truth.
#
export GREEN='\033[0;32m' YELLOW='\033[1;33m' RED='\033[0;31m' BLUE='\033[0;34m' NC='\033[0m'
export TASK_CONTEXT_ID=""
if [ -z "${PROJECT_DIR:-}" ]; then
    PROJECT_DIR=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
    PROJECT_NAME=$(basename "$PROJECT_DIR")
fi
export PROJECT_DIR PROJECT_NAME TASK_CONTEXT_ID

# ─── Sanitize environment for Docker Compose ──────────────────
# Unset vars that leak from .env.local / systemd and conflict with
# container-level PORT, HATCHET_CLIENT_TOKEN, etc.
unset PORT HATCHET_CLIENT_TOKEN HATCHET_COOKIE_SECRET \
      DATABASE_URL REDIS_URL AGENT_HUB_DB_URL \
      AGENT_HUB_REDIS_URL PORTFOLIO_DB_URL INTERNAL_SERVICE_SECRET \
      AGENT_HUB_SECRET_KEY 2>/dev/null || true

# ─── Compose paths ──────────────────────────────────────────────
_SUMMITFLOW_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
_COMPOSE_DIR="$_SUMMITFLOW_ROOT/docker/compose"
_COMPOSE_FILE="$_COMPOSE_DIR/docker-compose.yml"
_COMPOSE_DEV_FILE="$_COMPOSE_DIR/docker-compose.dev.yml"
_COMPOSE_ENV_FILE="$_COMPOSE_DIR/.env"
_RUNTIME_MODE_FILE="$_COMPOSE_DIR/.runtime-mode"
_DEFAULT_RUNTIME_MODE="${SUMMITFLOW_DOCKER_DEFAULT_MODE:-dev}"
[ "$_DEFAULT_RUNTIME_MODE" = "prod" ] || _DEFAULT_RUNTIME_MODE="dev"
export _SUMMITFLOW_ROOT _COMPOSE_DIR _COMPOSE_FILE _COMPOSE_DEV_FILE _COMPOSE_ENV_FILE _RUNTIME_MODE_FILE _DEFAULT_RUNTIME_MODE

_compose_env_var_names() {
    [ -f "$_COMPOSE_ENV_FILE" ] || return 0
    awk -F= '
        /^[[:space:]]*#/ { next }
        /^[[:space:]]*$/ { next }
        /^[A-Za-z_][A-Za-z0-9_]*=/ { print $1 }
    ' "$_COMPOSE_ENV_FILE"
}

_sanitize_compose_process_env() {
    local key
    while IFS= read -r key; do
        [ -n "$key" ] && unset "$key"
    done < <(_compose_env_var_names)
}

_docker_compose() {
    local -a cmd=(docker compose)
    if [ -f "$_COMPOSE_ENV_FILE" ]; then
        cmd+=(--env-file "$_COMPOSE_ENV_FILE")
    fi
    cmd+=("$@")
    "${cmd[@]}"
}

_sanitize_compose_process_env

_runtime_mode_from_disk() {
    if [ -f "$_RUNTIME_MODE_FILE" ]; then
        local mode
        mode=$(tr -d '[:space:]' < "$_RUNTIME_MODE_FILE")
        if [ "$mode" = "dev" ] || [ "$mode" = "prod" ]; then
            echo "$mode"
            return
        fi
    fi
    echo "$_DEFAULT_RUNTIME_MODE"
}

_set_docker_mode() {
    if [ "$1" = "dev" ]; then
        export DOCKER_DEV=true
    else
        export DOCKER_DEV=false
    fi
}

# Return compose file flags appropriate for current mode.
# In dev mode (DOCKER_DEV=true), includes the dev overlay so bind mounts
# and CMD overrides are preserved across rebuilds and restarts.
_compose_files() {
    local files=("-f" "$_COMPOSE_FILE")
    if [ "$DOCKER_DEV" = "true" ] && [ -f "$_COMPOSE_DEV_FILE" ]; then
        files+=("-f" "$_COMPOSE_DEV_FILE")
    fi
    echo "${files[@]}"
}

# Persist runtime mode (dev/prod) so detect_docker can recover after stop
_persist_runtime_mode() {
    mkdir -p "$_COMPOSE_DIR"
    if [ "$DOCKER_DEV" = "true" ]; then
        echo "dev" > "$_RUNTIME_MODE_FILE"
    else
        echo "prod" > "$_RUNTIME_MODE_FILE"
    fi
}

# Bring up a stopped Docker stack using persisted mode
docker_start_stack() {
    [ ! -f "$_COMPOSE_FILE" ] && { log_error "No compose file found"; return 1; }

    _set_docker_mode "$(_runtime_mode_from_disk)"
    docker_validate_hatchet_token || return 1

    local compose_args
    read -ra compose_args <<< "$(_compose_files)"

    log "Starting Docker stack (mode: $([ "$DOCKER_DEV" = "true" ] && echo dev || echo prod))..."
    _docker_compose "${compose_args[@]}" up -d 2>&1
    log_success "Stack started"
    _persist_runtime_mode
}

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
    # Query project containers directly so stopped stacks still resolve services.
    docker ps --all --filter "label=com.docker.compose.project=summitflow-stack" \
              --format '{{.Label "com.docker.compose.service"}}' 2>/dev/null \
        | { grep "^${prefix}" || true; } | sort -u | tr '\n' ' '
}

_compose_running_services() {
    [ ! -f "$_COMPOSE_FILE" ] && return
    local prefix
    prefix=$(_project_to_prefix "${1:-$PROJECT_NAME}")
    docker ps --filter "label=com.docker.compose.project=summitflow-stack" \
              --format '{{.Label "com.docker.compose.service"}}' 2>/dev/null \
        | { grep "^${prefix}" || true; } | sort -u | tr '\n' ' '
}

_compose_stack_services() {
    [ ! -f "$_COMPOSE_FILE" ] && return
    docker ps --all --filter "label=com.docker.compose.project=summitflow-stack" \
              --format '{{.Label "com.docker.compose.service"}}' 2>/dev/null \
        | grep -vE '^(postgres|redis|hatchet|hatchet-migrate|hatchet-setup-config)$' \
        | sort -u | tr '\n' ' '
}

_compose_api_service() {
    _compose_all_services "$@" | tr ' ' '\n' | grep -E '\-api$' | head -1 || true
}

_compose_web_service() {
    local services
    services=$(_compose_all_services "$@")
    local web
    web=$(echo "$services" | tr ' ' '\n' | grep -E '\-web$' | head -1 || true)
    # Standalone services (e.g. monkey-fight) have no -web suffix
    if [ -z "$web" ]; then
        web=$(echo "$services" | tr ' ' '\n' | head -1)
    fi
    echo "$web"
}

_compose_mode_probe_service() {
    local probe
    probe=$(_compose_api_service "$@")
    if [ -n "$probe" ]; then
        echo "$probe"
        return
    fi

    probe=$(_compose_web_service "$@")
    if [ -n "$probe" ]; then
        echo "$probe"
        return
    fi

    _compose_all_services "$@" | tr ' ' '\n' | head -1
}

# Get published port for a compose service from running container
_compose_service_port() {
    local svc="$1"
    _docker_compose -f "$_COMPOSE_FILE" port "$svc" "${2:-8001}" 2>/dev/null | cut -d: -f2
}

# Resolve ports from running containers
# Publishers format: [{0.0.0.0 8001 8001 tcp} ...]
_resolve_ports() {
    local api_svc web_svc port
    api_svc=$(_compose_api_service)
    web_svc=$(_compose_web_service)
    if [ -n "$api_svc" ]; then
        port=$(_docker_compose -f "$_COMPOSE_FILE" ps --format '{{.Publishers}}' "$api_svc" 2>/dev/null \
            | grep -oP '\{0\.0\.0\.0 \K[0-9]+' | head -1 || true)
        [ -n "$port" ] && BACKEND_PORT="$port"
    fi
    if [ -n "$web_svc" ]; then
        port=$(_docker_compose -f "$_COMPOSE_FILE" ps --format '{{.Publishers}}' "$web_svc" 2>/dev/null \
            | grep -oP '\{0\.0\.0\.0 \K[0-9]+' | head -1 || true)
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
    export BACKEND_SERVICE="${prefix}-backend.service"
    export FRONTEND_SERVICE="${prefix}-frontend.service"
    export DEFAULT_WORKER_SERVICES=""
    export OPTIONAL_WORKER_SERVICES=""
    export WORKER_SERVICES=""
    export ALL_WORKER_SERVICES=""
    export AUXILIARY_SERVICES=""
    export HAS_BACKEND=true
    export BACKEND_DIR="$PROJECT_DIR/backend"
    export FRONTEND_DIR="$PROJECT_DIR/frontend"

    case "$PROJECT_NAME" in
        summitflow)
            export DEFAULT_WORKER_SERVICES="summitflow-hatchet-worker.service"
            export BACKEND_PORT=8001 FRONTEND_PORT=3001
            ;;
        agent-hub)
            export DEFAULT_WORKER_SERVICES="agent-hub-hatchet-ops-worker.service"
            export OPTIONAL_WORKER_SERVICES="agent-hub-hatchet-agent-worker.service"
            export BACKEND_PORT=8003 FRONTEND_PORT=3003
            ;;
        portfolio-ai)
            export BACKEND_SERVICE="portfolio-backend.service"
            export FRONTEND_SERVICE="portfolio-frontend.service"
            export DEFAULT_WORKER_SERVICES="portfolio-hatchet-worker.service"
            export BACKEND_PORT=8000 FRONTEND_PORT=3000
            ;;
        a-term)
            export BACKEND_SERVICE="a-term-backend.service"
            export FRONTEND_SERVICE="a-term-frontend.service"
            export BACKEND_DIR="$PROJECT_DIR"
            export BACKEND_PORT=8002 FRONTEND_PORT=3002
            ;;
        monkey-fight)
            export BACKEND_SERVICE=""
            export FRONTEND_SERVICE="monkey-fight.service"
            export HAS_BACKEND=false
            export BACKEND_PORT=0 FRONTEND_PORT=4001
            export BACKEND_DIR="$PROJECT_DIR"
            export FRONTEND_DIR="$PROJECT_DIR"
            ;;
        *)
            export BACKEND_PORT=8000 FRONTEND_PORT=3000
            ;;
    esac

    export WORKER_SERVICES="$DEFAULT_WORKER_SERVICES"
    if [ "${REBUILD_INCLUDE_ALL_WORKERS:-false}" = "true" ] && [ -n "$OPTIONAL_WORKER_SERVICES" ]; then
        export WORKER_SERVICES="$DEFAULT_WORKER_SERVICES $OPTIONAL_WORKER_SERVICES"
    fi
    export ALL_WORKER_SERVICES="$DEFAULT_WORKER_SERVICES $OPTIONAL_WORKER_SERVICES"
    export MANAGED_SERVICES="$BACKEND_SERVICE $ALL_WORKER_SERVICES $AUXILIARY_SERVICES $FRONTEND_SERVICE"
}
_resolve_systemd_services

# ─── Runtime detection ───────────────────────────────────────────

detect_docker() {
    export RUNTIME_MODE="native" DOCKER_DEV=false DOCKER_IMAGE_STALE=false
    [ ! -f "$_COMPOSE_FILE" ] && return
    local running_services
    running_services=$(_compose_running_services)
    if [ -z "$running_services" ]; then
        return
    fi
    export RUNTIME_MODE="docker"

    # Resolve ports from compose config
    _resolve_ports

    # Detect dev overlay from whichever project container is available first.
    # Named volumes such as /app/.cache are valid in production and must not
    # trigger hot-reload mode.
    local probe_svc container
    probe_svc=$(_compose_mode_probe_service)
    if [ -z "$probe_svc" ]; then
        _set_docker_mode "$(_runtime_mode_from_disk)"
        return
    fi
    container=$(_docker_compose -f "$_COMPOSE_FILE" ps -q "$probe_svc" 2>/dev/null | head -1)
    if [ -z "$container" ]; then
        _set_docker_mode "$(_runtime_mode_from_disk)"
        return
    fi
    if docker inspect "$container" --format '{{range .Mounts}}{{.Type}} {{.Destination}}{{"\n"}}{{end}}' 2>/dev/null | grep -qE '^bind /app/.+'; then
        export DOCKER_DEV=true
    fi

    # Check if image is stale (infrastructure files changed since image was built)
    _detect_stale_image "$container"
}

docker_ensure_infra() {
    [ ! -f "$_COMPOSE_FILE" ] && return 0

    local required_services=(postgres redis hatchet)
    local missing_services=()
    local svc

    for svc in "${required_services[@]}"; do
        if ! docker ps --filter "label=com.docker.compose.project=summitflow-stack" \
                       --filter "label=com.docker.compose.service=$svc" \
                       --format '{{.ID}}' 2>/dev/null | grep -q .; then
            missing_services+=("$svc")
        fi
    done

    [ ${#missing_services[@]} -eq 0 ] && return 0

    log "Starting Docker infra: postgres redis hatchet"
    _docker_compose -f "$_COMPOSE_FILE" up -d postgres redis hatchet-migrate hatchet-setup-config hatchet 2>&1
    log_success "Docker infra started"

    local pg_ready=false
    local hatchet_ready=false
    local _i
    for _i in $(seq 1 45); do
        if pg_isready -h localhost -p 5432 -U admin >/dev/null 2>&1; then
            pg_ready=true
        fi
        if curl -sf http://localhost:8888/ready >/dev/null 2>&1; then
            hatchet_ready=true
        fi
        if [ "$pg_ready" = true ] && [ "$hatchet_ready" = true ]; then
            log_success "Docker infra healthy"
            return 0
        fi
        sleep 2
    done

    [ "$pg_ready" = false ] && log_error "PostgreSQL did not become ready"
    [ "$hatchet_ready" = false ] && log_error "Hatchet did not become ready"
    return 1
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
    docker_validate_hatchet_token || return 1

    # Always use dev overlay for build (has build: context directives)
    local build_files=("-f" "$_COMPOSE_FILE")
    [ -f "$_COMPOSE_DEV_FILE" ] && build_files+=("-f" "$_COMPOSE_DEV_FILE")

    log "Building images for: $services"
    # --no-cache ensures source changes are always picked up (COPY layers don't
    # invalidate on content changes when the build context is large)
    # shellcheck disable=SC2086
    _docker_compose "${build_files[@]}" build --no-cache $services 2>&1 | tail -20
    [ ${PIPESTATUS[0]} -ne 0 ] && { log_error "Build failed"; return 1; }
    log_success "Images built"

    # Recreate with mode-appropriate compose files — dev overlay preserves
    # bind mounts and CMD overrides when DOCKER_DEV=true
    local compose_args
    read -ra compose_args <<< "$(_compose_files)"
    log "Recreating containers (mode: $([ "$DOCKER_DEV" = "true" ] && echo dev || echo prod))..."
    # shellcheck disable=SC2086
    _docker_compose "${compose_args[@]}" up -d --no-deps $services 2>&1
    log_success "Containers recreated"
    _persist_runtime_mode
}

docker_restart_services() {
    local services="$1"
    [ -z "$services" ] && return 0

    local compose_args
    read -ra compose_args <<< "$(_compose_files)"
    log "Restarting: $services"
    # shellcheck disable=SC2086
    _docker_compose "${compose_args[@]}" restart $services 2>&1
    log_success "Restarted"
}

docker_recreate_services() {
    local services="$1"
    local build_first="${2:-false}"
    [ -z "$services" ] && return 0
    docker_validate_hatchet_token || return 1

    local compose_args
    read -ra compose_args <<< "$(_compose_files)"
    log "Recreating containers (mode: $([ "$DOCKER_DEV" = "true" ] && echo dev || echo prod))..."
    if [ "$build_first" = "true" ]; then
        # Dev mode needs local build contexts; this uses cache unless infra changed.
        # shellcheck disable=SC2086
        _docker_compose "${compose_args[@]}" up -d --build --force-recreate --no-deps $services 2>&1
    else
        # shellcheck disable=SC2086
        _docker_compose "${compose_args[@]}" up -d --force-recreate --no-deps $services 2>&1
    fi
    log_success "Containers recreated"
    _persist_runtime_mode
}

docker_run_migration() {
    local api_svc
    api_svc=$(_compose_api_service)
    [ -z "$api_svc" ] && return 0

    local compose_args
    read -ra compose_args <<< "$(_compose_files)"
    log "Running migrations ($api_svc)..."
    _docker_compose "${compose_args[@]}" exec -T "$api_svc" alembic upgrade head 2>&1 | tail -5
    [ ${PIPESTATUS[0]} -eq 0 ] && log_success "Migrations applied" || log_warn "Migration returned non-zero (may already be up to date)"
}

docker_validate_hatchet_token() {
    [ "$PROJECT_NAME" != "summitflow" ] && return 0
    [ ! -f "$_SUMMITFLOW_ROOT/scripts/validate-hatchet-token.py" ] && return 0
    local validation_output
    validation_output=$(python3 "$_SUMMITFLOW_ROOT/scripts/validate-hatchet-token.py" 2>&1) || {
        log_error "${validation_output:-Hatchet token validation failed}"
        return 1
    }
}

docker_reapply_hatchet_tuning() {
    [ "$PROJECT_NAME" != "summitflow" ] && return 0
    [ ! -f "$_SUMMITFLOW_ROOT/scripts/tune-hatchet-config.py" ] && return 0
    [ ! -d "$_COMPOSE_DIR/hatchet-config" ] && return 0

    local hatchet_id
    hatchet_id=$(_docker_compose -f "$_COMPOSE_FILE" ps -q hatchet 2>/dev/null | head -1)
    [ -z "$hatchet_id" ] && return 0

    local tune_output
    tune_output=$(python3 "$_SUMMITFLOW_ROOT/scripts/tune-hatchet-config.py") || {
        log_warn "Hatchet config tuning failed"
        return 1
    }

    if printf '%s\n' "$tune_output" | grep -q ': updated'; then
        log "Recreating Hatchet with tuned runtime config..."
        _docker_compose -f "$_COMPOSE_FILE" up -d --force-recreate hatchet 2>&1 | tail -20
        [ ${PIPESTATUS[0]} -ne 0 ] && { log_error "Hatchet recreate failed"; return 1; }
        log_success "Hatchet recreated"

        local ready_url="http://localhost:8888/ready"
        for _i in $(seq 1 45); do
            curl -sf "$ready_url" &>/dev/null && { log_success "Hatchet OK"; return 0; }
            sleep 2
        done

        log_error "Hatchet health verification failed"
        return 1
    fi

    return 0
}

# ─── Logging ─────────────────────────────────────────────────────
log() { printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$*"; }
log_success() { printf "${GREEN}[%s] ✓ %s${NC}\n" "$(date '+%H:%M:%S')" "$*"; }
log_warn() { printf "${YELLOW}[%s] ⚠ %s${NC}\n" "$(date '+%H:%M:%S')" "$*"; }
log_error() { printf "${RED}[%s] ✗ %s${NC}\n" "$(date '+%H:%M:%S')" "$*"; }
log_info() { printf "${BLUE}[%s] ℹ %s${NC}\n" "$(date '+%H:%M:%S')" "$*"; }

# ─── Systemd functions ───────────────────────────────────────────
service_exists() { systemctl --user cat "$1" &>/dev/null; }
port_listener_pids() {
    local port="$1"
    ss -ltnp "( sport = :$port )" 2>/dev/null | grep -oP 'pid=\K[0-9]+' | sort -u
}

kill_port_listeners() {
    local port="$1"
    local pids
    pids=$(port_listener_pids "$port")
    [ -n "$pids" ] || return 0

    log_warn "Clearing stale listeners on port $port: $(echo "$pids" | tr '\n' ' ')"
    while IFS= read -r pid; do
        [ -n "$pid" ] || continue
        kill "$pid" 2>/dev/null || true
    done <<< "$pids"

    local _i
    for _i in $(seq 1 10); do
        pids=$(port_listener_pids "$port")
        [ -z "$pids" ] && return 0
        sleep 1
    done

    while IFS= read -r pid; do
        [ -n "$pid" ] || continue
        kill -9 "$pid" 2>/dev/null || true
    done <<< "$pids"
    sleep 1
    pids=$(port_listener_pids "$port")
    [ -z "$pids" ] || {
        log_error "Port $port is still occupied"
        return 1
    }
}

restart_service() {
    local s="$1"
    local port="${2:-}"
    service_exists "$s" || { log_info "$s not found"; return 0; }
    log "Restarting $s..."

    if [ -n "$port" ] && [ "$port" -gt 0 ] 2>/dev/null; then
        systemctl --user stop "$s" >/dev/null 2>&1 || true
        kill_port_listeners "$port" || return 1
        systemctl --user start "$s" && log_success "$s restarted" || {
            log_error "$s failed"
            return 1
        }
        return 0
    fi

    systemctl --user restart "$s" && log_success "$s restarted" || {
        log_error "$s failed"
        return 1
    }
}
clear_build_cache() { local d="$PROJECT_DIR/frontend"; [ ! -d "$d" ] && d="$PROJECT_DIR"; rm -rf "$d/.next" "$d/dist" "$d/node_modules/.vite" 2>/dev/null; log_success "Cache cleared"; }
clear_nextjs_cache() { clear_build_cache; }
_frontend_dir() {
    local d="$PROJECT_DIR/frontend"
    [ -d "$d" ] || d="$PROJECT_DIR"
    echo "$d"
}

_frontend_package_manager() {
    local d="${1:-$(_frontend_dir)}"
    if [ -f "$d/package-lock.json" ] || [ -f "$d/npm-shrinkwrap.json" ]; then
        echo "npm"
    else
        echo "pnpm"
    fi
}

ensure_frontend_dependencies() {
    local d="${1:-$(_frontend_dir)}"
    [ -f "$d/package.json" ] || return 0
    [ -d "$d/node_modules" ] && return 0

    local manager
    manager=$(_frontend_package_manager "$d")

    log "Installing frontend dependencies with $manager..."
    (
        cd "$d" || exit 1
        if [ "$manager" = "npm" ]; then
            npm ci
        else
            CI=true pnpm install
        fi
    ) 2>&1 | tail -20
    [ ${PIPESTATUS[0]} -eq 0 ] && log_success "Frontend dependencies installed" || {
        log_error "Frontend dependency install failed"
        return 1
    }
}

build_frontend() {
    local d
    d=$(_frontend_dir)
    [ -f "$d/package.json" ] || { log_warn "No frontend package.json for $PROJECT_NAME"; return 0; }

    ensure_frontend_dependencies "$d" || return 1

    local manager
    manager=$(_frontend_package_manager "$d")

    log "Building frontend with $manager..."
    (
        cd "$d" || exit 1
        if [ "$manager" = "npm" ]; then
            npm run build
        else
            pnpm build
        fi
    ) 2>&1 | tail -20
    [ ${PIPESTATUS[0]} -eq 0 ] && log_success "Built" || { log_error "Build failed"; return 1; }
}
_sanitize_native_process_env() {
    env -u DATABASE_URL \
        -u DATABASE_ADMIN_URL \
        -u REDIS_URL \
        -u AGENT_HUB_DB_URL \
        -u AGENT_HUB_REDIS_URL \
        -u PORTFOLIO_DB_URL \
        -u PORTFOLIO_AI_DB_URL \
        -u PORTFOLIO_REDIS_URL \
        -u HATCHET_CLIENT_TOKEN \
        -u HATCHET_CLIENT_HOST_PORT \
        -u HATCHET_CLIENT_TLS_STRATEGY \
        "$@"
}

run_native_migrations() {
    [ "$HAS_BACKEND" = false ] && return 0
    [ ! -f "$BACKEND_DIR/alembic.ini" ] && return 0

    local venv_dir="$BACKEND_DIR/.venv"
    [ ! -d "$venv_dir" ] && venv_dir="$PROJECT_DIR/.venv"
    [ ! -x "$venv_dir/bin/alembic" ] && { log_warn "Alembic not available for $PROJECT_NAME"; return 0; }

    log "Running migrations..."
    (
        cd "$BACKEND_DIR" &&
        _sanitize_native_process_env "$venv_dir/bin/alembic" upgrade head
    ) 2>&1 | tail -10
    [ ${PIPESTATUS[0]} -eq 0 ] && log_success "Migrations applied" || { log_error "Migration failed"; return 1; }
}

sync_seed_data_from_db() {
    [ "$HAS_BACKEND" = false ] && return 0

    local export_script="$BACKEND_DIR/scripts/export_seeds.py"
    [ -f "$export_script" ] || return 0

    local venv_dir="$BACKEND_DIR/.venv"
    [ ! -d "$venv_dir" ] && venv_dir="$PROJECT_DIR/.venv"
    [ ! -x "$venv_dir/bin/python" ] && { log_warn "Python runtime not available for $PROJECT_NAME seed export"; return 0; }

    log "Syncing seed data from database..."
    (
        cd "$BACKEND_DIR" &&
        _sanitize_native_process_env "$venv_dir/bin/python" -m scripts.export_seeds
    ) 2>&1 | tail -10
    [ ${PIPESTATUS[0]} -eq 0 ] && log_success "Seed data synced" || log "Seed export skipped (non-fatal)"
}
verify_backend() { local p="${1:-$BACKEND_PORT}"; [ "$p" -eq 0 ] 2>/dev/null && return 0; log "Checking backend ($p)..."; for i in $(seq 1 10); do curl -s "http://localhost:$p/health" &>/dev/null && { log_success "Backend OK"; return 0; }; sleep 1; done; log_error "Backend failed"; return 1; }
verify_frontend() { local p="${1:-$FRONTEND_PORT}"; [ "$p" -eq 0 ] 2>/dev/null && return 0; log "Checking frontend ($p)..."; for i in $(seq 1 30); do local s=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 "http://localhost:$p/" 2>/dev/null); [[ "$s" =~ ^(2|3)[0-9][0-9]$ ]] && { log_success "Frontend OK ($s)"; return 0; }; sleep 1; done; log_error "Frontend failed"; return 1; }

export -f log log_success log_warn log_error log_info
export -f service_exists port_listener_pids kill_port_listeners restart_service clear_build_cache clear_nextjs_cache _frontend_dir _frontend_package_manager ensure_frontend_dependencies build_frontend run_native_migrations sync_seed_data_from_db verify_backend verify_frontend
export -f _sanitize_native_process_env
export -f _compose_env_var_names _sanitize_compose_process_env _docker_compose _runtime_mode_from_disk _set_docker_mode detect_docker _detect_stale_image _project_to_prefix _compose_all_services _compose_running_services _compose_stack_services _compose_api_service _compose_web_service _compose_service_port _resolve_ports _compose_files _persist_runtime_mode docker_start_stack docker_build_and_recreate docker_restart_services docker_recreate_services docker_run_migration docker_validate_hatchet_token docker_reapply_hatchet_tuning docker_ensure_infra
