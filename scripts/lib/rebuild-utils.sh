#!/bin/bash
export GREEN='\033[0;32m' YELLOW='\033[1;33m' RED='\033[0;31m' BLUE='\033[0;34m' NC='\033[0m'
if [ -z "$PROJECT_DIR" ]; then
    PROJECT_DIR=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
    # Detect if we're in a worktree (path pattern: ~/.local/share/st/worktrees/<project-id>/<task-id>/)
    if [[ "$PROJECT_DIR" == *"/worktrees/"* ]]; then
        # Extract actual project name from worktree path
        PROJECT_NAME=$(echo "$PROJECT_DIR" | sed -E 's|.*/worktrees/([^/]+)/.*|\1|')
    else
        PROJECT_NAME=$(basename "$PROJECT_DIR")
    fi
fi
export PROJECT_DIR PROJECT_NAME
case "$PROJECT_NAME" in
    summitflow) export SERVICE_PREFIX="summitflow" FRONTEND_PORT=3001 BACKEND_PORT=8001 HAS_CELERY=true HAS_REDIS=false ;;
    terminal) export SERVICE_PREFIX="summitflow-terminal" FRONTEND_PORT=3002 BACKEND_PORT=8002 HAS_CELERY=false HAS_REDIS=false ;;
    portfolio-ai) export SERVICE_PREFIX="portfolio" FRONTEND_PORT=3000 BACKEND_PORT=8000 HAS_CELERY=true HAS_REDIS=true ;;
    agent-hub) export SERVICE_PREFIX="agent-hub" FRONTEND_PORT=3003 BACKEND_PORT=8003 HAS_CELERY=true HAS_REDIS=false ;;
    monkey-fight) export SERVICE_PREFIX="monkey-fight" FRONTEND_PORT=4001 BACKEND_PORT=0 HAS_CELERY=false HAS_REDIS=false HAS_BACKEND=false IS_VITE=true ;;
    *) export SERVICE_PREFIX=$(echo "$PROJECT_NAME" | tr '-' '_') FRONTEND_PORT=3000 BACKEND_PORT=8000 HAS_CELERY=false HAS_REDIS=false ;;
esac
export BACKEND_SERVICE="${SERVICE_PREFIX}-backend" FRONTEND_SERVICE="${SERVICE_PREFIX}-frontend"
export CELERY_SERVICE="${SERVICE_PREFIX}-celery" CELERY_BEAT_SERVICE="${SERVICE_PREFIX}-celery-beat" REDIS_SERVICE="${SERVICE_PREFIX}-redis"
[ "$PROJECT_NAME" = "terminal" ] && export BACKEND_SERVICE="summitflow-terminal" FRONTEND_SERVICE="summitflow-terminal-frontend"
[ "$PROJECT_NAME" = "monkey-fight" ] && export FRONTEND_SERVICE="monkey-fight"
log() { printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$*"; }
log_success() { printf "${GREEN}[%s] ✓ %s${NC}\n" "$(date '+%H:%M:%S')" "$*"; }
log_warn() { printf "${YELLOW}[%s] ⚠ %s${NC}\n" "$(date '+%H:%M:%S')" "$*"; }
log_error() { printf "${RED}[%s] ✗ %s${NC}\n" "$(date '+%H:%M:%S')" "$*"; }
log_info() { printf "${BLUE}[%s] ℹ %s${NC}\n" "$(date '+%H:%M:%S')" "$*"; }
service_exists() { systemctl --user cat "$1" &>/dev/null; }
restart_service() { local s="$1"; service_exists "$s" || { log_info "$s not found"; return 0; }; log "Restarting $s..."; systemctl --user restart "$s" && log_success "$s restarted" || { log_error "$s failed"; return 1; }; }
clear_build_cache() { local d="$PROJECT_DIR/frontend"; [ ! -d "$d" ] && d="$PROJECT_DIR"; [ "$IS_VITE" = true ] && { log "Clearing Vite cache..."; rm -rf "$d/dist" "$d/node_modules/.vite"; } || { log "Clearing Next.js cache..."; rm -rf "$d/.next"; }; log_success "Cache cleared"; }
clear_nextjs_cache() { clear_build_cache; }
build_frontend() { local d="$PROJECT_DIR/frontend"; [ ! -d "$d" ] && d="$PROJECT_DIR"; cd "$d" || return 1; log "Building..."; pnpm build 2>&1 | tail -15 && log_success "Built" || { log_error "Build failed"; return 1; }; }
verify_backend() { local p="${1:-$BACKEND_PORT}"; [ "$p" -eq 0 ] && return 0; log "Checking backend ($p)..."; for i in $(seq 1 10); do curl -s "http://localhost:$p/health" &>/dev/null && { log_success "Backend OK"; return 0; }; sleep 1; done; log_error "Backend failed"; return 1; }
verify_frontend() { local p="${1:-$FRONTEND_PORT}"; log "Checking frontend ($p)..."; for i in $(seq 1 30); do local s=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 "http://localhost:$p/" 2>/dev/null); [[ "$s" =~ ^(2|3)[0-9][0-9]$ ]] && { log_success "Frontend OK ($s)"; return 0; }; sleep 1; done; log_error "Frontend failed"; return 1; }
export -f log log_success log_warn log_error log_info service_exists restart_service clear_build_cache clear_nextjs_cache build_frontend verify_backend verify_frontend
