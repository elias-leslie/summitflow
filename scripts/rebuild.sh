#!/bin/bash
#
# Universal Rebuild Script
# Clears caches, rebuilds, restarts services, verifies health
# Works for any project - auto-detects project from PWD/git root
#
# Usage:
#   ./scripts/rebuild.sh              # Full rebuild (frontend + all services)
#   ./scripts/rebuild.sh --frontend   # Frontend only (rebuild + restart frontend)
#   ./scripts/rebuild.sh --backend    # Backend only (restart backend + worker)
#   ./scripts/rebuild.sh --restart    # Restart only (no rebuild)
#   ./scripts/rebuild.sh --status     # Show service status
#

set -eo pipefail

# Load utilities (which also detects PROJECT_DIR and PROJECT_NAME)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/rebuild-utils.sh"

# Parse arguments
FRONTEND_ONLY=false
BACKEND_ONLY=false
RESTART_ONLY=false
STATUS_ONLY=false

for arg in "$@"; do
    case $arg in
        --frontend|-f) FRONTEND_ONLY=true ;;
        --backend|-b) BACKEND_ONLY=true ;;
        --restart|-r) RESTART_ONLY=true ;;
        --status|-s) STATUS_ONLY=true ;;
        --help|-h)
            echo "Usage: $0 [--frontend] [--backend] [--restart] [--status]"
            echo ""
            echo "Options:"
            echo "  --frontend, -f  Frontend only (rebuild + restart frontend)"
            echo "  --backend, -b   Backend only (restart backend + worker)"
            echo "  --restart, -r   Restart only (no rebuild)"
            echo "  --status, -s    Show service status"
            echo ""
            echo "Project: $PROJECT_NAME ($PROJECT_DIR)"
            echo "Services: $SERVICE_PREFIX-*"
            echo "Ports: backend=$BACKEND_PORT, frontend=$FRONTEND_PORT"
            exit 0
            ;;
    esac
done

# Show status function
show_status() {
    echo ""
    echo "========================================"
    echo "$PROJECT_NAME Service Status"
    echo "========================================"
    echo ""
    echo "Project: $PROJECT_NAME ($PROJECT_DIR)"
    echo ""
    echo "Services:"

    for svc in $MANAGED_SERVICES; do
        if service_exists "$svc"; then
            local status=$(systemctl --user is-active "$svc" 2>/dev/null || echo "unknown")
            local icon="✗"
            [ "$status" = "active" ] && icon="✓"
            printf "  %-35s %s %s\n" "$svc" "$icon" "$status"
        fi
    done

    echo ""
    echo "Ports:"
    if [ "$HAS_BACKEND" != false ] && [ "$BACKEND_PORT" -gt 0 ]; then
        printf "  Backend  (%-5d): " "$BACKEND_PORT"
        ss -tlnp 2>/dev/null | grep -q ":$BACKEND_PORT " && echo "✓ listening" || echo "✗ not bound"
    fi
    printf "  Frontend (%-5d): " "$FRONTEND_PORT"
    ss -tlnp 2>/dev/null | grep -q ":$FRONTEND_PORT " && echo "✓ listening" || echo "✗ not bound"

    echo ""
    echo "Health:"
    if [ "$HAS_BACKEND" != false ] && [ "$BACKEND_PORT" -gt 0 ]; then
        printf "  Backend:  "
        curl -s "http://localhost:$BACKEND_PORT/health" &>/dev/null && echo "✓ healthy" || echo "✗ unhealthy"
    fi
    printf "  Frontend: "
    local http_status=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 "http://localhost:$FRONTEND_PORT/" 2>/dev/null)
    [[ "$http_status" =~ ^(2|3)[0-9][0-9]$ ]] && echo "✓ serving (HTTP $http_status)" || echo "✗ not serving (HTTP $http_status)"

    echo ""
}

# Main rebuild function
main() {
    local start_time=$(date +%s)
    local errors=0

    if [ "$STATUS_ONLY" = true ]; then
        show_status
        exit 0
    fi

    if [ "$IS_WORKTREE" = true ]; then
        log_error "rebuild.sh targets shared project services, not task worktree services."
        echo ""
        echo "Use the isolated worktree service manager instead:"
        echo "  bash ~/summitflow/scripts/worktree-services.sh start ${WORKTREE_TASK_ID} --project ${PROJECT_NAME}"
        echo "  bash ~/summitflow/scripts/worktree-services.sh status ${WORKTREE_TASK_ID} --project ${PROJECT_NAME}"
        echo "  bash ~/summitflow/scripts/worktree-services.sh ports ${WORKTREE_TASK_ID} --project ${PROJECT_NAME}"
        echo ""
        echo "The 'ports' command prints the local preview URLs for that worktree."
        echo ""
        exit 1
    fi

    echo ""
    echo "========================================"
    echo "$PROJECT_NAME Rebuild"
    echo "========================================"
    echo ""
    echo "Project: $PROJECT_NAME"
    echo "Mode: $([ "$RESTART_ONLY" = true ] && echo "restart" || ([ "$FRONTEND_ONLY" = true ] && echo "frontend" || ([ "$BACKEND_ONLY" = true ] && echo "backend" || echo "full")))"
    echo ""

    # Frontend rebuild (unless backend-only or restart-only)
    if [ "$BACKEND_ONLY" = false ] && [ "$RESTART_ONLY" = false ]; then
        clear_nextjs_cache || true
        build_frontend || { log_error "Frontend build failed"; ((errors++)); }
    fi

    # Restart services
    if [ "$FRONTEND_ONLY" = false ] && [ "$HAS_BACKEND" != false ]; then
        # Backend
        restart_service "$BACKEND_SERVICE" || ((errors++))

        # Project-specific workers/support services are declared centrally in rebuild-utils.sh.
        for svc in $WORKER_SERVICES $AUXILIARY_SERVICES; do
            [ -n "$svc" ] || continue
            restart_service "$svc" || ((errors++))
        done
    fi

    # Frontend service (unless backend-only)
    if [ "$BACKEND_ONLY" = false ]; then
        restart_service "$FRONTEND_SERVICE" || ((errors++))
    fi

    # Verify health
    echo ""
    log "Verifying services..."

    if [ "$FRONTEND_ONLY" = false ] && [ "$HAS_BACKEND" != false ]; then
        verify_backend || ((errors++))
    fi

    if [ "$BACKEND_ONLY" = false ]; then
        verify_frontend || ((errors++))
    fi

    # Regenerate project index (keeps .index.yaml ports in sync with systemd)
    # Only if backend was rebuilt and SummitFlow API is available
    if [ "$FRONTEND_ONLY" = false ] && [ "$HAS_BACKEND" != false ] && [ $errors -eq 0 ]; then
        local summitflow_api="${ST_API_BASE:-http://localhost:8001/api}"
        log "Regenerating project index..."
        local index_result=$(curl -s -X POST "$summitflow_api/projects/$PROJECT_NAME/explorer/regenerate-index" 2>/dev/null)
        if echo "$index_result" | grep -q '"status":"success"'; then
            log_success "Index regenerated"
        else
            # Non-fatal - index regeneration is optional
            log "Index regeneration skipped (API may not be SummitFlow)"
        fi
    fi

    # Summary
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))

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
    [ "$FRONTEND_ONLY" = false ] && echo "  Backend:  http://localhost:$BACKEND_PORT"
    [ "$BACKEND_ONLY" = false ] && echo "  Frontend: http://localhost:$FRONTEND_PORT"
    echo ""

    return $errors
}

main "$@"
