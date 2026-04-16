#!/bin/bash
# Worktree Service Manager (Config-Driven)
#
# Starts/stops services in an isolated worktree with unique ports
# to avoid conflicts with main services. Configuration is loaded
# from the SummitFlow API based on project settings.
#
# Usage:
#   worktree-services.sh start <task-id> --project <project-id>
#   worktree-services.sh stop <task-id> --project <project-id>
#   worktree-services.sh status <task-id> --project <project-id>
#   worktree-services.sh ports <task-id> --project <project-id>
#   worktree-services.sh logs <task-id> --project <project-id>
#
# Configuration is loaded from:
#   GET http://localhost:8001/api/projects/{project-id}/services

set -e

SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${SCRIPT_PATH}")" && pwd)"
SUMMITFLOW_ROOT_OVERRIDE="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck source=/dev/null
. "${SCRIPT_DIR}/lib/project-roots.sh"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Default API base URL
API_BASE_URL="${ST_API_URL:-http://localhost:8001}"

# Worktrees base directory (per-project paths)
DEFAULT_WORKSPACES_ROOT="${ST_WORKSPACES_ROOT:-/srv/workspaces}"
if [ -d "${DEFAULT_WORKSPACES_ROOT}/lanes" ]; then
    DEFAULT_WORKTREES_BASE="${DEFAULT_WORKSPACES_ROOT}/lanes"
else
    DEFAULT_WORKTREES_BASE="${HOME}/.local/share/st/worktrees"
fi
WORKTREES_BASE="${ST_WORKTREES_BASE:-${DEFAULT_WORKTREES_BASE}}"

load_shared_env() {
    local env_file="${HOME}/.env.local"
    if [ -f "$env_file" ]; then
        set -a
        # shellcheck disable=SC1090
        source "$env_file"
        set +a
    fi
}

usage() {
    echo "Worktree Service Manager (Config-Driven)"
    echo ""
    echo "Usage: $0 <command> <task-id> --project <project-id>"
    echo ""
    echo "Commands:"
    echo "  start   Start all configured services for worktree"
    echo "  stop    Stop worktree services"
    echo "  status  Check if services are running"
    echo "  ports   Show allocated ports"
    echo "  logs    Tail logs for worktree services"
    echo ""
    echo "Options:"
    echo "  --project, -p <id>   Project ID (required)"
    echo ""
    echo "Environment Variables:"
    echo "  ST_API_URL           SummitFlow API URL (default: http://localhost:8001)"
    echo "  ST_WORKTREES_BASE    Worktrees base dir (default: /srv/workspaces/lanes when available)"
    echo ""
    echo "Examples:"
    echo "  $0 start task-abc123 --project proj-xyz"
    echo "  $0 stop task-abc123 -p proj-xyz"
    echo "  $0 status task-abc123 --project proj-xyz"
    exit 1
}

# Parse arguments
parse_args() {
    COMMAND=""
    TASK_ID=""
    PROJECT_ID=""

    while [[ $# -gt 0 ]]; do
        case $1 in
            --project|-p)
                PROJECT_ID="$2"
                shift 2
                ;;
            start|stop|status|ports|logs)
                COMMAND="$1"
                shift
                ;;
            -*)
                echo -e "${RED}Error: Unknown option $1${NC}"
                usage
                ;;
            *)
                if [ -z "$TASK_ID" ]; then
                    TASK_ID="$1"
                fi
                shift
                ;;
        esac
    done

    if [ -z "$COMMAND" ]; then
        echo -e "${RED}Error: Command required${NC}"
        usage
    fi

    if [ -z "$TASK_ID" ]; then
        echo -e "${RED}Error: Task ID required${NC}"
        usage
    fi

    if [ -z "$PROJECT_ID" ]; then
        echo -e "${RED}Error: Project ID required (--project or -p)${NC}"
        usage
    fi
}

# Build worktree config directly from repo-local project identity + service templates
build_local_config() {
    local project_id="$1"
    local project_root=""
    project_root="$(resolve_project_root "$project_id" 2>/dev/null || true)"

    local py
    py=$(find_venv_python || command -v python3 || true)
    [ -n "$py" ] || return 1

    local cmd=("$py" -m app.worktree_service_config --project "$project_id")
    if [ -n "$project_root" ]; then
        cmd+=(--root "$project_root")
    fi

    PYTHONPATH="${SUMMITFLOW_ROOT_OVERRIDE}/backend${PYTHONPATH:+:${PYTHONPATH}}" "${cmd[@]}"
}

# Fetch service configuration, preferring repo-local identity over API indirection
fetch_config() {
    local project_id="$1"
    local response=""

    if response=$(build_local_config "$project_id" 2>/dev/null); then
        echo "$response"
        return 0
    fi

    local config_url="${API_BASE_URL}/api/projects/${project_id}/services"
    response=$(curl -sf "$config_url" 2>/dev/null) || {
        echo -e "${RED}Error: Failed to derive local config and failed to fetch ${config_url}${NC}" >&2
        echo -e "${RED}Make sure project identity exists or SummitFlow API is running.${NC}" >&2
        exit 1
    }

    echo "$response"
}

# Extract service names from config JSON
get_service_names() {
    local config="$1"
    echo "$config" | jq -r '.services | keys[]'
}

# Get service property from config
get_service_prop() {
    local config="$1"
    local service="$2"
    local prop="$3"
    echo "$config" | jq -r ".services.\"${service}\".${prop} // empty"
}

get_service_prop_json() {
    local config="$1"
    local service="$2"
    local prop="$3"
    echo "$config" | jq -c ".services.\"${service}\".${prop} // empty"
}

# Calculate deterministic port offset from task ID using MD5
get_port_offset() {
    local task_id="$1"
    local port_range="$2"
    # Get MD5 hash and take first 8 hex chars as a number
    local hash
    hash=$(echo -n "$task_id" | md5sum | cut -c1-8)
    # Convert hex to decimal and mod by port_range
    local decimal=$((16#$hash))
    echo $((decimal % port_range))
}

# Get worktree port for a service
get_worktree_port() {
    local task_id="$1"
    local port_base="$2"
    local port_range="$3"
    local offset
    offset=$(get_port_offset "$task_id" "$port_range")
    echo $((port_base + offset))
}

find_venv_python() {
    local py
    for py in python3.13 python3.12 python3; do
        if ! command -v "$py" >/dev/null 2>&1; then
            continue
        fi
        if ! "$py" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' >/dev/null 2>&1; then
            continue
        fi
        if ! "$py" -c 'import ensurepip' >/dev/null 2>&1; then
            continue
        fi
        echo "$py"
        return 0
    done
    return 1
}

venv_is_usable() {
    local service_dir="$1"
    [[ -x "${service_dir}/.venv/bin/python" && -f "${service_dir}/.venv/bin/activate" ]]
}

# Check if a port is in use
check_port() {
    local port="$1"
    if command -v nc >/dev/null 2>&1; then
        if nc -z 127.0.0.1 "$port" 2>/dev/null; then
            return 0  # Port is in use
        fi
    fi

    local py
    py=$(command -v python3 || true)
    [ -n "$py" ] || return 1

    "$py" - "$port" <<'PY' >/dev/null 2>&1
import socket
import sys

sock = socket.socket()
sock.settimeout(0.5)
try:
    sock.connect(("127.0.0.1", int(sys.argv[1])))
except OSError:
    raise SystemExit(1)
finally:
    sock.close()
PY
}

# Get worktree path (per-project: /srv/workspaces/lanes/<project-id>/<task-id>/ when available)
get_worktree_path() {
    local task_id="$1"
    # Sanitize task ID (replace non-alphanumeric chars with underscore)
    local sanitized
    sanitized=$(echo "$task_id" | tr -c 'a-zA-Z0-9_-' '_' | tr -s '_' | sed 's/^_//;s/_$//')
    echo "${WORKTREES_BASE}/${PROJECT_ID}/${sanitized}"
}

# Get PID file directory
get_pid_dir() {
    local task_id="$1"
    local worktree_path
    worktree_path=$(get_worktree_path "$task_id")
    echo "${worktree_path}/.pids"
}

expand_runtime_value() {
    local raw_value="$1"
    local expanded_value=""
    eval "expanded_value=\"$raw_value\""
    printf '%s' "$expanded_value"
}

# Substitute legacy placeholders in command strings
substitute_placeholders() {
    local command="$1"
    local port="$2"
    local backend_port="$3"
    local frontend_port="$4"
    local worktree_root="$5"
    command="${command//\{port\}/$port}"
    command="${command//\{backend_port\}/$backend_port}"
    command="${command//\{frontend_port\}/$frontend_port}"
    command="${command//\{worktree_root\}/$worktree_root}"
    echo "$command"
}

get_saved_port() {
    local worktree_path="$1"
    local service_name="$2"
    local ports_file="${worktree_path}/ports.json"
    [ -f "$ports_file" ] || return 0
    echo "$(<"$ports_file")" | jq -r --arg key "${service_name}_port" '.[$key] // empty'
}

resolve_service_port() {
    local config="$1"
    local task_id="$2"
    local service_name="$3"
    local worktree_path="$4"

    local saved_port
    saved_port=$(get_saved_port "$worktree_path" "$service_name")
    if [[ "$saved_port" =~ ^[0-9]+$ ]]; then
        echo "$saved_port"
        return 0
    fi

    local port_base port_range
    port_base=$(get_service_prop "$config" "$service_name" "worktree_port_base")
    port_range=$(get_service_prop "$config" "$service_name" "worktree_port_range")
    [ -n "$port_base" ] || return 0
    get_worktree_port "$task_id" "$port_base" "$port_range"
}

copy_repo_relative_env_file() {
    local worktree_path="$1"
    local repo_relative="$2"
    local target="${worktree_path}/${repo_relative}"
    [ -f "$target" ] && return 0

    local project_root=""
    project_root="$(resolve_project_root "$PROJECT_ID" 2>/dev/null || true)"
    [ -n "$project_root" ] || return 0

    local source="${project_root}/${repo_relative}"
    [ -f "$source" ] || return 0

    mkdir -p "$(dirname "$target")"
    cp "$source" "$target"
}

copy_legacy_env_file() {
    local worktree_path="$1"
    local cwd="$2"
    local env_file="$3"
    local service_dir="$worktree_path"
    if [ -n "$cwd" ]; then
        service_dir="${worktree_path}/${cwd}"
    fi
    [ -f "${service_dir}/${env_file}" ] && return 0

    local project_root=""
    project_root="$(resolve_project_root "$PROJECT_ID" 2>/dev/null || true)"
    local main_env_candidates=(
        "${project_root}/${cwd}/${env_file}"
        "${project_root}/${env_file}"
        "${HOME}/${cwd}/${env_file}"
    )
    local candidate
    for candidate in "${main_env_candidates[@]}"; do
        if [ -f "$candidate" ]; then
            cp "$candidate" "${service_dir}/${env_file}"
            break
        fi
    done
}

prepare_node_workspace() {
    local worktree_path="$1"
    local cwd="$2"
    local project_root=""
    project_root="$(resolve_project_root "$PROJECT_ID" 2>/dev/null || true)"
    [ -n "$project_root" ] || return 0

    local py
    py=$(find_venv_python || command -v python3 || true)
    [ -n "$py" ] || return 0

    local cmd=(
        "$py" -m app.worktree_node_workspace
        --lane-root "$worktree_path"
        --main-root "$project_root"
    )
    if [ -n "$cwd" ]; then
        cmd+=(--cwd "$cwd")
    fi

    local prep_json
    prep_json=$(
        PYTHONPATH="${SUMMITFLOW_ROOT_OVERRIDE}/backend${PYTHONPATH:+:${PYTHONPATH}}" "${cmd[@]}"
    )

    local removed_count materialized_count needs_install
    removed_count=$(echo "$prep_json" | jq '.removed_node_modules_symlinks | length')
    materialized_count=$(echo "$prep_json" | jq '.materialized_file_dependency_links | length')
    needs_install=$(echo "$prep_json" | jq -r '.needs_install')

    if [ "$removed_count" -gt 0 ]; then
        echo -e "${YELLOW}Removed ${removed_count} escaped/broken node_modules symlink(s).${NC}" >&2
    fi
    if [ "$materialized_count" -gt 0 ]; then
        echo -e "${YELLOW}Materialized ${materialized_count} file: dependency link(s).${NC}" >&2
    fi

    echo "$needs_install"
}

latest_tree_mtime() {
    local path="$1"
    shift || true
    [ -e "$path" ] || return 0

    if [ -f "$path" ]; then
        stat -c '%Y' "$path" 2>/dev/null || echo 0
        return 0
    fi

    find "$path" -type f "$@" -printf '%T@\n' 2>/dev/null | sort -nr | head -1 || true
}

mtime_is_greater() {
    local left="${1:-0}"
    local right="${2:-0}"
    awk -v left="$left" -v right="$right" 'BEGIN { exit !(left > right) }'
}

node_latest_build_mtime() {
    local service_dir="$1"
    local command="$2"

    if [[ "$command" == *"next start"* ]] && [ -f "${service_dir}/.next/BUILD_ID" ]; then
        stat -c '%Y' "${service_dir}/.next/BUILD_ID" 2>/dev/null || echo 0
        return 0
    fi

    local latest=0 candidate
    for candidate in \
        "$(latest_tree_mtime "${service_dir}/.next")" \
        "$(latest_tree_mtime "${service_dir}/dist")" \
        "$(latest_tree_mtime "${service_dir}/build")"
    do
        if mtime_is_greater "$candidate" "$latest"; then
            latest="$candidate"
        fi
    done
    echo "${latest:-0}"
}

node_latest_source_mtime() {
    local worktree_path="$1"
    local service_dir="$2"
    local latest=0 candidate path

    for path in \
        "$service_dir" \
        "${worktree_path}/package.json" \
        "${worktree_path}/pnpm-workspace.yaml" \
        "${worktree_path}/pnpm-lock.yaml" \
        "${worktree_path}/packages"
    do
        [ -e "$path" ] || continue
        candidate=$(latest_tree_mtime \
            "$path" \
            ! -path '*/node_modules/*' \
            ! -path '*/.next/*' \
            ! -path '*/dist/*' \
            ! -path '*/build/*' \
            ! -path '*/coverage/*' \
            ! -path '*/.turbo/*')
        if mtime_is_greater "$candidate" "$latest"; then
            latest="$candidate"
        fi
    done

    echo "${latest:-0}"
}

node_build_required() {
    local service_dir="$1"
    local worktree_path="$2"
    local command="$3"

    if [ -d "${service_dir}/.next" ] && [ ! -f "${service_dir}/.next/BUILD_ID" ]; then
        return 0
    fi

    local build_mtime source_mtime
    build_mtime=$(node_latest_build_mtime "$service_dir" "$command")
    if [ -z "$build_mtime" ] || [ "$build_mtime" = "0" ]; then
        return 0
    fi

    source_mtime=$(node_latest_source_mtime "$worktree_path" "$service_dir")
    mtime_is_greater "$source_mtime" "$build_mtime"
}

launch_service_process() {
    local command="$1"
    local log_file="$2"
    local shell_command="exec ${command}"

    if command -v setsid >/dev/null 2>&1; then
        setsid bash -lc "$shell_command" </dev/null > "$log_file" 2>&1 &
    else
        nohup bash -lc "$shell_command" </dev/null > "$log_file" 2>&1 &
    fi
    echo $!
}

# Start a single service
start_service() {
    local config="$1"
    local task_id="$2"
    local service_name="$3"
    local worktree_path="$4"
    local pid_dir="$5"
    local log_dir="$6"

    # Get service configuration
    local command cwd env_file build_command install_command env_files_json environment_json
    command=$(get_service_prop "$config" "$service_name" "command")
    cwd=$(get_service_prop "$config" "$service_name" "cwd")
    env_file=$(get_service_prop "$config" "$service_name" "env_file")
    build_command=$(get_service_prop "$config" "$service_name" "build_command")
    install_command=$(get_service_prop "$config" "$service_name" "install_command")
    env_files_json=$(get_service_prop_json "$config" "$service_name" "env_files")
    environment_json=$(get_service_prop_json "$config" "$service_name" "environment")

    # Resolve ports, preferring persisted claim-time allocation
    local port backend_port frontend_port
    port=$(resolve_service_port "$config" "$task_id" "$service_name" "$worktree_path")
    backend_port=$(resolve_service_port "$config" "$task_id" "backend" "$worktree_path")
    frontend_port=$(resolve_service_port "$config" "$task_id" "frontend" "$worktree_path")

    # Determine service directory
    local service_dir="$worktree_path"
    if [ -n "$cwd" ]; then
        service_dir="${worktree_path}/${cwd}"
    fi

    echo -n "Starting ${service_name} (port ${port})... "

    if [ ! -d "$service_dir" ]; then
        echo -e "${RED}Failed: directory not found at ${service_dir}${NC}"
        return 1
    fi

    # Check for port conflicts
    if check_port "$port"; then
        echo -e "${RED}Failed: port $port is already in use${NC}"
        return 1
    fi

    # Handle Python venv setup for backend-like services
    if [ -f "${service_dir}/pyproject.toml" ] || [ -f "${service_dir}/setup.py" ]; then
        if ! venv_is_usable "$service_dir"; then
            echo -e "${YELLOW}Creating venv...${NC}"
            rm -rf "${service_dir}/.venv"
            local venv_python
            venv_python=$(find_venv_python) || {
                echo -e "${RED}Failed: no Python 3.12+ interpreter with ensurepip is available for worktree venv creation${NC}"
                return 1
            }
            (cd "$service_dir" && "$venv_python" -m venv .venv && .venv/bin/pip install -e ".[dev]")
        fi
    fi

    # Handle node dependency install/build for frontend-like services
    if [ -f "${service_dir}/package.json" ]; then
        local node_workspace_needs_install="false"
        node_workspace_needs_install=$(prepare_node_workspace "$worktree_path" "$cwd")
        if [ ! -d "${service_dir}/node_modules" ] || [ "$node_workspace_needs_install" = "true" ]; then
            echo -e "${YELLOW}Installing npm deps...${NC}"
            if [ -z "$install_command" ]; then
                if [ -f "${service_dir}/pnpm-lock.yaml" ] || [ -f "${worktree_path}/pnpm-workspace.yaml" ]; then
                    install_command="pnpm install"
                else
                    install_command="npm install"
                fi
            fi
            (cd "$service_dir" && CI=true eval "$install_command")
        fi
        # Run build command if specified and no build output exists
        if [ -n "$build_command" ] && node_build_required "$service_dir" "$worktree_path" "$command"; then
            echo -e "${YELLOW}Building...${NC}"
            (cd "$service_dir" && CI=true eval "$build_command")
        fi
    fi

    # Copy declared env files into the worktree if needed
    local repo_env_file
    while IFS= read -r repo_env_file; do
        [ -n "$repo_env_file" ] || continue
        copy_repo_relative_env_file "$worktree_path" "$repo_env_file"
    done < <(echo "$env_files_json" | jq -r '.[]?')

    # Legacy single env_file support
    if [ -n "$env_file" ]; then
        copy_legacy_env_file "$worktree_path" "$cwd" "$env_file"
    fi

    # Substitute legacy placeholders in command
    local final_command
    final_command=$(substitute_placeholders "$command" "$port" "$backend_port" "$frontend_port" "$worktree_path")

    # Start the service
    (
        cd "$service_dir"

        # Activate venv if it exists (for Python services)
        if venv_is_usable "$service_dir"; then
            # shellcheck disable=SC1091
            source .venv/bin/activate
        fi

        # Set environment variables
        export PORT="$port"
        export WORKTREE_ROOT="$worktree_path"
        export WORKTREE_MODE=1
        export WORKTREE_TASK_ID="$task_id"
        export SF_WORKTREE_BACKEND_PORT="${backend_port:-0}"
        export SF_WORKTREE_FRONTEND_PORT="${frontend_port:-0}"
        load_shared_env
        export SF_COMMAND_GUARD_DISABLE=1

        # Source repo-local env files after shared env so lane-local overrides win
        while IFS= read -r repo_env_file; do
            [ -n "$repo_env_file" ] || continue
            if [ -f "${WORKTREE_ROOT}/${repo_env_file}" ]; then
                set -a
                # shellcheck disable=SC1090
                source "${WORKTREE_ROOT}/${repo_env_file}"
                set +a
            fi
        done < <(echo "$env_files_json" | jq -r '.[]?')

        # Legacy single env_file support
        if [ -n "$env_file" ]; then
            local legacy_env_path="${service_dir}/${env_file}"
            if [ -f "$legacy_env_path" ]; then
                set -a
                # shellcheck disable=SC1090
                source "$legacy_env_path"
                set +a
            fi
        fi

        # Template-derived environment exports
        while IFS= read -r entry; do
            [ -n "$entry" ] || continue
            local key="${entry%%=*}"
            local value="${entry#*=}"
            local expanded_value
            expanded_value=$(expand_runtime_value "$value")
            export "$key=$expanded_value"
        done < <(echo "$environment_json" | jq -r 'to_entries[]? | "\(.key)=\(.value)"')

        # Run the service fully detached so it survives launcher shell exit
        launch_service_process "$final_command" "${log_dir}/${service_name}.log" > "${pid_dir}/${service_name}.pid"
    )

    echo -e "${GREEN}Started (PID: $(cat "${pid_dir}/${service_name}.pid"))${NC}"
}

# Start all services for a worktree
start_services() {
    local task_id="$1"
    local project_id="$2"
    local worktree_path
    worktree_path=$(get_worktree_path "$task_id")
    local pid_dir
    pid_dir=$(get_pid_dir "$task_id")
    local log_dir="${worktree_path}/.logs"

    if [ ! -d "$worktree_path" ]; then
        echo -e "${RED}Error: Worktree not found at $worktree_path${NC}"
        echo "Create worktree first with: st claim $task_id"
        exit 1
    fi

    # Fetch configuration
    echo -e "${BLUE}Fetching service configuration for project: $project_id${NC}"
    local config
    config=$(fetch_config "$project_id")

    local config_source
    config_source=$(echo "$config" | jq -r '.config_source')
    echo "  Config source: $config_source"
    echo ""

    # Create directories
    mkdir -p "$pid_dir"
    mkdir -p "$log_dir"

    echo -e "${BLUE}Starting services for worktree: $task_id${NC}"
    echo "  Worktree: $worktree_path"
    echo ""

    # Build ports.json
    local ports_json='{"task_id":"'"$task_id"'"'

    # Start each service
    local service_names
    service_names=$(get_service_names "$config")

    for service_name in $service_names; do
        local port
        port=$(resolve_service_port "$config" "$task_id" "$service_name" "$worktree_path")

        ports_json="${ports_json},\"${service_name}_port\":${port}"

        start_service "$config" "$task_id" "$service_name" "$worktree_path" "$pid_dir" "$log_dir"
    done

    ports_json="${ports_json}}"

    # Save port assignments
    echo "$ports_json" | jq '.' > "${worktree_path}/ports.json"

    echo ""
    echo -e "${GREEN}Services started successfully!${NC}"
    echo ""
    echo "URLs:"
    for service_name in $service_names; do
        local port
        port=$(resolve_service_port "$config" "$task_id" "$service_name" "$worktree_path")
        echo "  ${service_name}: http://localhost:${port}"
    done
    echo ""
    echo "Logs: ${log_dir}/"
    echo "Stop with: $0 stop $task_id --project $project_id"
}

# Stop all services for a worktree
stop_services() {
    local task_id="$1"
    local project_id="$2"
    local pid_dir
    pid_dir=$(get_pid_dir "$task_id")

    echo -e "${BLUE}Stopping services for worktree: $task_id${NC}"

    # Fetch configuration to get service names
    local config
    config=$(fetch_config "$project_id")

    local stopped=0
    local service_names
    service_names=$(get_service_names "$config")

    for service_name in $service_names; do
        local pid_file="${pid_dir}/${service_name}.pid"
        if [ -f "$pid_file" ]; then
            local pid
            pid=$(cat "$pid_file")
            echo -n "Stopping ${service_name} (PID: $pid)... "
            if kill -- "-${pid}" 2>/dev/null || kill "$pid" 2>/dev/null; then
                echo -e "${GREEN}Stopped${NC}"
                stopped=$((stopped + 1))
            else
                echo -e "${YELLOW}Not running${NC}"
            fi
            rm -f "$pid_file"
        else
            echo "${service_name}: No PID file found"
        fi
    done

    if [ $stopped -gt 0 ]; then
        echo -e "${GREEN}Stopped $stopped service(s)${NC}"
    else
        echo -e "${YELLOW}No services were running${NC}"
    fi
}

# Check status of worktree services
check_status() {
    local task_id="$1"
    local project_id="$2"
    local worktree_path
    worktree_path=$(get_worktree_path "$task_id")
    local pid_dir
    pid_dir=$(get_pid_dir "$task_id")

    echo -e "${BLUE}Service status for worktree: $task_id${NC}"
    echo ""

    if [ ! -d "$worktree_path" ]; then
        echo -e "${RED}Worktree not found at $worktree_path${NC}"
        exit 1
    fi

    # Fetch configuration
    local config
    config=$(fetch_config "$project_id")

    local service_names
    service_names=$(get_service_names "$config")

    for service_name in $service_names; do
        local port
        port=$(resolve_service_port "$config" "$task_id" "$service_name" "$worktree_path")

        local pid_file="${pid_dir}/${service_name}.pid"

        echo -n "${service_name} (port ${port}): "
        if [ -f "$pid_file" ]; then
            local pid
            pid=$(cat "$pid_file")
            if kill -0 "$pid" 2>/dev/null; then
                if check_port "$port"; then
                    echo -e "${GREEN}Running (PID: $pid)${NC}"
                else
                    echo -e "${YELLOW}Process running but port not listening${NC}"
                fi
            else
                echo -e "${RED}Not running (stale PID file)${NC}"
            fi
        else
            if check_port "$port"; then
                echo -e "${YELLOW}Port in use (unknown process)${NC}"
            else
                echo -e "${RED}Not running${NC}"
            fi
        fi
    done

    echo ""
    echo "URLs:"
    for service_name in $service_names; do
        local port
        port=$(resolve_service_port "$config" "$task_id" "$service_name" "$worktree_path")
        echo "  ${service_name}: http://localhost:${port}"
    done
}

# Show allocated ports
show_ports() {
    local task_id="$1"
    local project_id="$2"

    echo -e "${BLUE}Port allocation for: $task_id${NC}"
    echo ""

    # Fetch configuration
    local config
    config=$(fetch_config "$project_id")
    local worktree_path
    worktree_path=$(get_worktree_path "$task_id")

    local service_names
    service_names=$(get_service_names "$config")

    for service_name in $service_names; do
        local port
        port=$(resolve_service_port "$config" "$task_id" "$service_name" "$worktree_path")

        echo "  ${service_name}: ${port}"
    done

    echo ""
    echo "URLs:"
    for service_name in $service_names; do
        local port
        port=$(resolve_service_port "$config" "$task_id" "$service_name" "$worktree_path")
        echo "  ${service_name}: http://localhost:${port}"
    done

    echo ""
    echo "Port status:"
    for service_name in $service_names; do
        local port
        port=$(resolve_service_port "$config" "$task_id" "$service_name" "$worktree_path")

        if check_port "$port"; then
            echo -e "  ${service_name}: ${YELLOW}In use${NC}"
        else
            echo -e "  ${service_name}: ${GREEN}Available${NC}"
        fi
    done
}

# Tail logs for worktree services
tail_logs() {
    local task_id="$1"
    local project_id="$2"
    local worktree_path
    worktree_path=$(get_worktree_path "$task_id")
    local log_dir="${worktree_path}/.logs"

    if [ ! -d "$log_dir" ]; then
        echo -e "${RED}No logs found. Services may not have been started.${NC}"
        exit 1
    fi

    echo -e "${BLUE}Tailing logs for: $task_id${NC}"
    echo "Press Ctrl+C to exit"
    echo ""

    # Fetch configuration to get service names
    local config
    config=$(fetch_config "$project_id")

    local log_files=()
    local service_names
    service_names=$(get_service_names "$config")

    for service_name in $service_names; do
        local log_file="${log_dir}/${service_name}.log"
        if [ -f "$log_file" ]; then
            log_files+=("$log_file")
        fi
    done

    if [ ${#log_files[@]} -eq 0 ]; then
        echo -e "${RED}No log files found${NC}"
        exit 1
    fi

    tail -f "${log_files[@]}"
}

# Main command handler
main() {
    parse_args "$@"

    case "$COMMAND" in
        start)
            start_services "$TASK_ID" "$PROJECT_ID"
            ;;
        stop)
            stop_services "$TASK_ID" "$PROJECT_ID"
            ;;
        status)
            check_status "$TASK_ID" "$PROJECT_ID"
            ;;
        ports)
            show_ports "$TASK_ID" "$PROJECT_ID"
            ;;
        logs)
            tail_logs "$TASK_ID" "$PROJECT_ID"
            ;;
        *)
            echo -e "${RED}Unknown command: $COMMAND${NC}"
            usage
            ;;
    esac
}

main "$@"
