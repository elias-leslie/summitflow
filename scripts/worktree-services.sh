#!/bin/bash
# Worktree Service Manager for SummitFlow
#
# Starts/stops backend and frontend services in an isolated worktree
# with unique ports to avoid conflicts with main services.
#
# Usage:
#   worktree-services.sh start <task-id>   - Start services for worktree
#   worktree-services.sh stop <task-id>    - Stop services for worktree
#   worktree-services.sh status <task-id>  - Check service status
#   worktree-services.sh ports <task-id>   - Show allocated ports
#
# Main services (untouched):
#   Backend:  8001
#   Frontend: 3001
#
# Worktree services (isolated):
#   Backend:  8100 + (hash % 100)
#   Frontend: 3100 + (hash % 100)

set -e

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
WORKTREES_BASE="${HOME}/.summitflow/worktrees"
SUMMITFLOW_DIR="${HOME}/summitflow"

# Port ranges
BACKEND_BASE=8100
FRONTEND_BASE=3100
PORT_RANGE=100

usage() {
    echo "Worktree Service Manager for SummitFlow"
    echo ""
    echo "Usage: $0 <command> <task-id>"
    echo ""
    echo "Commands:"
    echo "  start   Start backend and frontend for worktree"
    echo "  stop    Stop worktree services"
    echo "  status  Check if services are running"
    echo "  ports   Show allocated ports"
    echo "  logs    Tail logs for worktree services"
    echo ""
    echo "Examples:"
    echo "  $0 start task-abc123"
    echo "  $0 stop task-abc123"
    echo "  $0 status task-abc123"
    exit 1
}

# Calculate deterministic port offset from task ID using MD5
get_port_offset() {
    local task_id="$1"
    # Get MD5 hash and take first 8 hex chars as a number
    local hash=$(echo -n "$task_id" | md5sum | cut -c1-8)
    # Convert hex to decimal and mod by PORT_RANGE
    local decimal=$((16#$hash))
    echo $((decimal % PORT_RANGE))
}

# Get ports for a task
get_ports() {
    local task_id="$1"
    local offset=$(get_port_offset "$task_id")
    local backend_port=$((BACKEND_BASE + offset))
    local frontend_port=$((FRONTEND_BASE + offset))
    echo "$backend_port $frontend_port"
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
    local sanitized=$(echo "$task_id" | tr -c 'a-zA-Z0-9_-' '_' | tr -s '_' | sed 's/^_//;s/_$//')
    echo "${WORKTREES_BASE}/${sanitized}"
}

# Get PID file path
get_pid_dir() {
    local task_id="$1"
    local worktree_path=$(get_worktree_path "$task_id")
    echo "${worktree_path}/.pids"
}

# Start services for a worktree
start_services() {
    local task_id="$1"
    local worktree_path=$(get_worktree_path "$task_id")
    local pid_dir=$(get_pid_dir "$task_id")

    if [ ! -d "$worktree_path" ]; then
        echo -e "${RED}Error: Worktree not found at $worktree_path${NC}"
        echo "Create worktree first with: st claim $task_id"
        exit 1
    fi

    # Get ports
    read -r backend_port frontend_port <<< $(get_ports "$task_id")

    echo -e "${BLUE}Starting services for worktree: $task_id${NC}"
    echo "  Worktree: $worktree_path"
    echo "  Backend:  http://localhost:$backend_port"
    echo "  Frontend: http://localhost:$frontend_port"
    echo ""

    # Check for port conflicts
    if check_port "$backend_port"; then
        echo -e "${RED}Error: Backend port $backend_port is already in use${NC}"
        exit 1
    fi
    if check_port "$frontend_port"; then
        echo -e "${RED}Error: Frontend port $frontend_port is already in use${NC}"
        exit 1
    fi

    # Create PID directory
    mkdir -p "$pid_dir"

    # Create log directory
    local log_dir="${worktree_path}/.logs"
    mkdir -p "$log_dir"

    # Save port assignments
    cat > "${worktree_path}/ports.json" << EOF
{
  "task_id": "$task_id",
  "backend_port": $backend_port,
  "frontend_port": $frontend_port,
  "api_url": "http://localhost:$backend_port",
  "frontend_url": "http://localhost:$frontend_port"
}
EOF

    # Start backend
    echo -n "Starting backend... "
    local backend_dir="${worktree_path}/backend"
    if [ ! -d "$backend_dir" ]; then
        echo -e "${RED}Failed: backend directory not found${NC}"
        exit 1
    fi

    # Copy .env from main backend if not present
    if [ ! -f "${backend_dir}/.env" ] && [ -f "${SUMMITFLOW_DIR}/backend/.env" ]; then
        cp "${SUMMITFLOW_DIR}/backend/.env" "${backend_dir}/.env"
    fi

    # Set up virtual environment if not present
    if [ ! -d "${backend_dir}/.venv" ]; then
        echo -e "${YELLOW}Creating venv...${NC}"
        (cd "$backend_dir" && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]")
    fi

    # Start backend with port override
    (
        cd "$backend_dir"
        source .venv/bin/activate
        export PORT="$backend_port"
        export WORKTREE_MODE=1
        export WORKTREE_TASK_ID="$task_id"
        nohup uvicorn app.main:app --host 0.0.0.0 --port "$backend_port" \
            > "${log_dir}/backend.log" 2>&1 &
        echo $! > "${pid_dir}/backend.pid"
    )
    echo -e "${GREEN}Started (PID: $(cat ${pid_dir}/backend.pid))${NC}"

    # Start frontend
    echo -n "Starting frontend... "
    local frontend_dir="${worktree_path}/frontend"
    if [ ! -d "$frontend_dir" ]; then
        echo -e "${RED}Failed: frontend directory not found${NC}"
        exit 1
    fi

    # Install dependencies if needed
    if [ ! -d "${frontend_dir}/node_modules" ]; then
        echo -e "${YELLOW}Installing deps...${NC}"
        (cd "$frontend_dir" && npm install)
    fi

    # Build if not built
    if [ ! -d "${frontend_dir}/.next" ]; then
        echo -e "${YELLOW}Building frontend...${NC}"
        (cd "$frontend_dir" && npm run build)
    fi

    # Start frontend with port override and backend URL
    (
        cd "$frontend_dir"
        export PORT="$frontend_port"
        export NEXT_PUBLIC_API_URL="http://localhost:$backend_port"
        export WORKTREE_MODE=1
        export WORKTREE_TASK_ID="$task_id"
        nohup npm run start -- --hostname 0.0.0.0 --port "$frontend_port" \
            > "${log_dir}/frontend.log" 2>&1 &
        echo $! > "${pid_dir}/frontend.pid"
    )
    echo -e "${GREEN}Started (PID: $(cat ${pid_dir}/frontend.pid))${NC}"

    echo ""
    echo -e "${GREEN}Services started successfully!${NC}"
    echo ""
    echo "URLs:"
    echo "  Backend API:  http://localhost:$backend_port"
    echo "  API Docs:     http://localhost:$backend_port/docs"
    echo "  Frontend:     http://localhost:$frontend_port"
    echo ""
    echo "Logs:"
    echo "  Backend:  tail -f ${log_dir}/backend.log"
    echo "  Frontend: tail -f ${log_dir}/frontend.log"
    echo ""
    echo "Stop with: $0 stop $task_id"
}

# Stop services for a worktree
stop_services() {
    local task_id="$1"
    local pid_dir=$(get_pid_dir "$task_id")

    echo -e "${BLUE}Stopping services for worktree: $task_id${NC}"

    local stopped=0

    # Stop backend
    if [ -f "${pid_dir}/backend.pid" ]; then
        local pid=$(cat "${pid_dir}/backend.pid")
        echo -n "Stopping backend (PID: $pid)... "
        if kill "$pid" 2>/dev/null; then
            echo -e "${GREEN}Stopped${NC}"
            stopped=$((stopped + 1))
        else
            echo -e "${YELLOW}Not running${NC}"
        fi
        rm -f "${pid_dir}/backend.pid"
    else
        echo "Backend: No PID file found"
    fi

    # Stop frontend
    if [ -f "${pid_dir}/frontend.pid" ]; then
        local pid=$(cat "${pid_dir}/frontend.pid")
        echo -n "Stopping frontend (PID: $pid)... "
        if kill "$pid" 2>/dev/null; then
            echo -e "${GREEN}Stopped${NC}"
            stopped=$((stopped + 1))
        else
            echo -e "${YELLOW}Not running${NC}"
        fi
        rm -f "${pid_dir}/frontend.pid"
    else
        echo "Frontend: No PID file found"
    fi

    if [ $stopped -gt 0 ]; then
        echo -e "${GREEN}Stopped $stopped service(s)${NC}"
    else
        echo -e "${YELLOW}No services were running${NC}"
    fi
}

# Check status of worktree services
check_status() {
    local task_id="$1"
    local worktree_path=$(get_worktree_path "$task_id")
    local pid_dir=$(get_pid_dir "$task_id")

    echo -e "${BLUE}Service status for worktree: $task_id${NC}"
    echo ""

    if [ ! -d "$worktree_path" ]; then
        echo -e "${RED}Worktree not found at $worktree_path${NC}"
        exit 1
    fi

    read -r backend_port frontend_port <<< $(get_ports "$task_id")

    # Check backend
    echo -n "Backend (port $backend_port):  "
    if [ -f "${pid_dir}/backend.pid" ]; then
        local pid=$(cat "${pid_dir}/backend.pid")
        if kill -0 "$pid" 2>/dev/null; then
            if check_port "$backend_port"; then
                echo -e "${GREEN}Running (PID: $pid)${NC}"
            else
                echo -e "${YELLOW}Process running but port not listening${NC}"
            fi
        else
            echo -e "${RED}Not running (stale PID file)${NC}"
        fi
    else
        if check_port "$backend_port"; then
            echo -e "${YELLOW}Port in use (unknown process)${NC}"
        else
            echo -e "${RED}Not running${NC}"
        fi
    fi

    # Check frontend
    echo -n "Frontend (port $frontend_port): "
    if [ -f "${pid_dir}/frontend.pid" ]; then
        local pid=$(cat "${pid_dir}/frontend.pid")
        if kill -0 "$pid" 2>/dev/null; then
            if check_port "$frontend_port"; then
                echo -e "${GREEN}Running (PID: $pid)${NC}"
            else
                echo -e "${YELLOW}Process running but port not listening${NC}"
            fi
        else
            echo -e "${RED}Not running (stale PID file)${NC}"
        fi
    else
        if check_port "$frontend_port"; then
            echo -e "${YELLOW}Port in use (unknown process)${NC}"
        else
            echo -e "${RED}Not running${NC}"
        fi
    fi

    echo ""
    echo "URLs:"
    echo "  Backend:  http://localhost:$backend_port"
    echo "  Frontend: http://localhost:$frontend_port"
}

# Show allocated ports
show_ports() {
    local task_id="$1"
    read -r backend_port frontend_port <<< $(get_ports "$task_id")

    echo -e "${BLUE}Port allocation for: $task_id${NC}"
    echo ""
    echo "  Backend port:  $backend_port"
    echo "  Frontend port: $frontend_port"
    echo ""
    echo "URLs:"
    echo "  Backend API:  http://localhost:$backend_port"
    echo "  API Docs:     http://localhost:$backend_port/docs"
    echo "  Frontend:     http://localhost:$frontend_port"
    echo ""

    # Check port availability
    echo "Port status:"
    if check_port "$backend_port"; then
        echo -e "  Backend:  ${YELLOW}In use${NC}"
    else
        echo -e "  Backend:  ${GREEN}Available${NC}"
    fi
    if check_port "$frontend_port"; then
        echo -e "  Frontend: ${YELLOW}In use${NC}"
    else
        echo -e "  Frontend: ${GREEN}Available${NC}"
    fi
}

# Tail logs for worktree services
tail_logs() {
    local task_id="$1"
    local worktree_path=$(get_worktree_path "$task_id")
    local log_dir="${worktree_path}/.logs"

    if [ ! -d "$log_dir" ]; then
        echo -e "${RED}No logs found. Services may not have been started.${NC}"
        exit 1
    fi

    echo -e "${BLUE}Tailing logs for: $task_id${NC}"
    echo "Press Ctrl+C to exit"
    echo ""

    tail -f "${log_dir}/backend.log" "${log_dir}/frontend.log" 2>/dev/null || {
        echo -e "${RED}No log files found${NC}"
        exit 1
    }
}

# Main command handler
main() {
    if [ $# -lt 2 ]; then
        usage
    fi

    local command="$1"
    local task_id="$2"

    case "$command" in
        start)
            start_services "$task_id"
            ;;
        stop)
            stop_services "$task_id"
            ;;
        status)
            check_status "$task_id"
            ;;
        ports)
            show_ports "$task_id"
            ;;
        logs)
            tail_logs "$task_id"
            ;;
        *)
            echo -e "${RED}Unknown command: $command${NC}"
            usage
            ;;
    esac
}

main "$@"
