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

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Default API base URL
API_BASE_URL="${ST_API_URL:-http://localhost:8001}"

# Worktrees base directory
WORKTREES_BASE="${ST_WORKTREES_BASE:-${HOME}/.summitflow/worktrees}"

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
    echo "  ST_WORKTREES_BASE    Worktrees directory (default: ~/.summitflow/worktrees)"
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

# Fetch service configuration from API
fetch_config() {
    local project_id="$1"
    local config_url="${API_BASE_URL}/api/projects/${project_id}/services"

    local response
    response=$(curl -sf "$config_url" 2>/dev/null) || {
        echo -e "${RED}Error: Failed to fetch config from ${config_url}${NC}" >&2
        echo -e "${RED}Make sure SummitFlow API is running and project exists.${NC}" >&2
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

# Check if a port is in use
check_port() {
    local port="$1"
    if nc -z localhost "$port" 2>/dev/null; then
        return 0  # Port is in use
    else
        return 1  # Port is available
    fi
}

# Get worktree path
get_worktree_path() {
    local task_id="$1"
    # Sanitize task ID (replace non-alphanumeric chars with underscore)
    local sanitized
    sanitized=$(echo "$task_id" | tr -c 'a-zA-Z0-9_-' '_' | tr -s '_' | sed 's/^_//;s/_$//')
    echo "${WORKTREES_BASE}/${sanitized}"
}

# Get PID file directory
get_pid_dir() {
    local task_id="$1"
    local worktree_path
    worktree_path=$(get_worktree_path "$task_id")
    echo "${worktree_path}/.pids"
}

# Substitute {port} placeholder in command
substitute_port() {
    local command="$1"
    local port="$2"
    echo "${command//\{port\}/$port}"
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
    local command port_base port_range cwd env_file build_command
    command=$(get_service_prop "$config" "$service_name" "command")
    port_base=$(get_service_prop "$config" "$service_name" "worktree_port_base")
    port_range=$(get_service_prop "$config" "$service_name" "worktree_port_range")
    cwd=$(get_service_prop "$config" "$service_name" "cwd")
    env_file=$(get_service_prop "$config" "$service_name" "env_file")
    build_command=$(get_service_prop "$config" "$service_name" "build_command")

    # Calculate port
    local port
    port=$(get_worktree_port "$task_id" "$port_base" "$port_range")

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
    if [[ "$command" == *"uvicorn"* ]] || [[ "$command" == *"python"* ]]; then
        if [ ! -d "${service_dir}/.venv" ]; then
            echo -e "${YELLOW}Creating venv...${NC}"
            (cd "$service_dir" && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]")
        fi
    fi

    # Handle npm install for frontend-like services
    if [[ "$command" == *"npm"* ]]; then
        if [ ! -d "${service_dir}/node_modules" ]; then
            echo -e "${YELLOW}Installing npm deps...${NC}"
            (cd "$service_dir" && npm install)
        fi
        # Run build command if specified and no build output exists
        if [ -n "$build_command" ] && [ ! -d "${service_dir}/.next" ] && [ ! -d "${service_dir}/dist" ] && [ ! -d "${service_dir}/build" ]; then
            echo -e "${YELLOW}Building...${NC}"
            (cd "$service_dir" && eval "$build_command")
        fi
    fi

    # Copy env file if specified and not present
    if [ -n "$env_file" ] && [ ! -f "${service_dir}/${env_file}" ]; then
        # Try to find source env file from main project
        local main_env_candidates=(
            "${HOME}/summitflow/${cwd}/${env_file}"
            "${HOME}/${cwd}/${env_file}"
        )
        for candidate in "${main_env_candidates[@]}"; do
            if [ -f "$candidate" ]; then
                cp "$candidate" "${service_dir}/${env_file}"
                break
            fi
        done
    fi

    # Substitute port in command
    local final_command
    final_command=$(substitute_port "$command" "$port")

    # Start the service
    (
        cd "$service_dir"

        # Activate venv if it exists (for Python services)
        if [ -d ".venv" ]; then
            # shellcheck disable=SC1091
            source .venv/bin/activate
        fi

        # Set environment variables
        export PORT="$port"
        export WORKTREE_MODE=1
        export WORKTREE_TASK_ID="$task_id"

        # Run the service
        nohup bash -c "$final_command" > "${log_dir}/${service_name}.log" 2>&1 &
        echo $! > "${pid_dir}/${service_name}.pid"
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
        local port_base port_range port
        port_base=$(get_service_prop "$config" "$service_name" "worktree_port_base")
        port_range=$(get_service_prop "$config" "$service_name" "worktree_port_range")
        port=$(get_worktree_port "$task_id" "$port_base" "$port_range")

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
        local port_base port_range port
        port_base=$(get_service_prop "$config" "$service_name" "worktree_port_base")
        port_range=$(get_service_prop "$config" "$service_name" "worktree_port_range")
        port=$(get_worktree_port "$task_id" "$port_base" "$port_range")
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
            if kill "$pid" 2>/dev/null; then
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
        local port_base port_range port
        port_base=$(get_service_prop "$config" "$service_name" "worktree_port_base")
        port_range=$(get_service_prop "$config" "$service_name" "worktree_port_range")
        port=$(get_worktree_port "$task_id" "$port_base" "$port_range")

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
        local port_base port_range port
        port_base=$(get_service_prop "$config" "$service_name" "worktree_port_base")
        port_range=$(get_service_prop "$config" "$service_name" "worktree_port_range")
        port=$(get_worktree_port "$task_id" "$port_base" "$port_range")
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

    local service_names
    service_names=$(get_service_names "$config")

    for service_name in $service_names; do
        local port_base port_range port
        port_base=$(get_service_prop "$config" "$service_name" "worktree_port_base")
        port_range=$(get_service_prop "$config" "$service_name" "worktree_port_range")
        port=$(get_worktree_port "$task_id" "$port_base" "$port_range")

        echo "  ${service_name}: ${port}"
    done

    echo ""
    echo "URLs:"
    for service_name in $service_names; do
        local port_base port_range port
        port_base=$(get_service_prop "$config" "$service_name" "worktree_port_base")
        port_range=$(get_service_prop "$config" "$service_name" "worktree_port_range")
        port=$(get_worktree_port "$task_id" "$port_base" "$port_range")
        echo "  ${service_name}: http://localhost:${port}"
    done

    echo ""
    echo "Port status:"
    for service_name in $service_names; do
        local port_base port_range port
        port_base=$(get_service_prop "$config" "$service_name" "worktree_port_base")
        port_range=$(get_service_prop "$config" "$service_name" "worktree_port_range")
        port=$(get_worktree_port "$task_id" "$port_base" "$port_range")

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
