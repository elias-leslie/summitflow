#!/bin/bash
#
# Universal Rebuild Script
# Clears caches, rebuilds, restarts services, verifies health
# Works for any project — auto-detects systemd vs Docker runtime
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
DOCKER_MODE_OVERRIDE=""

for arg in "$@"; do
    case $arg in
        --frontend|-f) FRONTEND_ONLY=true ;;
        --backend|-b) BACKEND_ONLY=true ;;
        --restart|-r) RESTART_ONLY=true ;;
        --status|-s) STATUS_ONLY=true ;;
        --dev) DOCKER_MODE_OVERRIDE="dev" ;;
        --prod) DOCKER_MODE_OVERRIDE="prod" ;;
        --help|-h)
            echo "Usage: $0 [--frontend] [--backend] [--restart] [--status] [--dev|--prod]"
            echo ""
            echo "Options:"
            echo "  --frontend, -f  Frontend only (rebuild + restart frontend)"
            echo "  --backend, -b   Backend only (restart backend + worker)"
            echo "  --restart, -r   Restart only (no rebuild)"
            echo "  --status, -s    Show service status"
            echo "  --dev           Use Docker dev mode (bind mounts + hot reload)"
            echo "  --prod          Use Docker prod mode (published/runtime images)"
            echo ""
            echo "Project: $PROJECT_NAME ($PROJECT_DIR)"
            exit 0
            ;;
    esac
done

selected_action_label() {
    if [ "$RESTART_ONLY" = true ]; then
        echo "restart"
    elif [ "$FRONTEND_ONLY" = true ]; then
        echo "frontend"
    elif [ "$BACKEND_ONLY" = true ]; then
        echo "backend"
    else
        echo "full"
    fi
}

print_rebuild_header() {
    local title="$1"
    local runtime_desc="$2"
    local switch_desc="${3:-}"
    echo ""
    echo "========================================"
    echo "$title"
    echo "========================================"
    echo ""
    echo "Project: $PROJECT_NAME"
    echo "Mode: $(selected_action_label)"
    echo "Runtime: $runtime_desc"
    [ -n "$switch_desc" ] && echo "Switch: $switch_desc"
    echo ""
}

print_rebuild_footer() {
    local errors="$1"
    local duration="$2"
    echo ""
    echo "========================================"
    if [ "$errors" -eq 0 ]; then
        log_success "Rebuild complete (${duration}s)"
    else
        log_error "Rebuild completed with $errors error(s) (${duration}s)"
    fi
    echo "========================================"
    echo ""
    echo "URLs:"
    if [ "$FRONTEND_ONLY" = false ] && [ "$HAS_BACKEND" != false ] && [ "$BACKEND_PORT" -gt 0 ]; then
        echo "  Backend:  http://localhost:$BACKEND_PORT"
    fi
    if [ "$BACKEND_ONLY" = false ] && [ "$FRONTEND_PORT" -gt 0 ]; then
        echo "  Frontend: http://localhost:$FRONTEND_PORT"
    fi
    echo ""
}

# ─── Status ──────────────────────────────────────────────────────

show_status_docker() {
    set +e  # Don't exit on docker compose ps failures
    local active_mode
    active_mode=$([ "$DOCKER_DEV" = true ] && echo "dev overlay" || echo "production images")
    echo ""
    echo "========================================"
    echo "$PROJECT_NAME Service Status (Docker)"
    echo "========================================"
    echo ""
    local services
    services=$(_compose_all_services)
    if [ -n "$services" ]; then
        for svc in $services; do
            local state health
            state=$(_docker_compose -f "$_COMPOSE_FILE" ps --format '{{.State}}' "$svc" 2>/dev/null)
            [ -z "$state" ] && state="not found"
            health=$(_docker_compose -f "$_COMPOSE_FILE" ps --format '{{.Health}}' "$svc" 2>/dev/null)
            local icon="✗"; [ "$state" = "running" ] && icon="✓"
            printf "  %-30s %s %s %s\n" "$svc" "$icon" "$state" "${health:+($health)}"
        done
    else
        echo "  (no project containers created yet)"
    fi
    echo ""
    echo "Ports: backend=$BACKEND_PORT, frontend=$FRONTEND_PORT"
    if [ "$RUNTIME_MODE" = "docker-stopped" ]; then
        echo "Stack: stopped"
    else
        echo "Stack: running"
    fi
    if [ "$DOCKER_DEV" = true ]; then
        echo "Mode: docker ($active_mode)"
    else
        echo "Mode: docker ($active_mode)"
    fi
    echo "Default mode: $_DEFAULT_RUNTIME_MODE"
    echo ""
    set -e
}

show_status_native() {
    echo ""
    echo "========================================"
    echo "$PROJECT_NAME Service Status"
    echo "========================================"
    echo ""
    echo "Project: $PROJECT_NAME ($PROJECT_DIR)"
    echo ""
    echo "Services:"
    for svc in $MANAGED_SERVICES; do
        [ -n "$svc" ] || continue
        if service_exists "$svc"; then
            local status=$(systemctl --user is-active "$svc" 2>/dev/null || echo "unknown")
            local icon="✗"; [ "$status" = "active" ] && icon="✓"
            printf "  %-35s %s %s\n" "$svc" "$icon" "$status"
        fi
    done
    if [ -f "$_COMPOSE_FILE" ]; then
        echo ""
        echo "Infra (Docker):"
        local infra_lines
        infra_lines=$(_docker_compose -f "$_COMPOSE_FILE" ps --format '{{.Service}} {{.State}} {{.Health}}' postgres redis hatchet 2>/dev/null || true)
        if [ -n "$infra_lines" ]; then
            while IFS= read -r line; do
                [ -n "$line" ] || continue
                printf "  %s\n" "$line"
            done <<< "$infra_lines"
        else
            echo "  (infra not running)"
        fi
    fi
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

# ─── Docker rebuild ──────────────────────────────────────────────

main_docker() {
    local start_time=$(date +%s)
    local errors=0

    local all_services=$(_compose_all_services)
    local stack_services=$(_compose_stack_services)
    local api_svc=$(_compose_api_service)
    local web_svc=$(_compose_web_service)
    local detected_mode=$([ "$DOCKER_DEV" = true ] && echo "dev" || echo "prod")
    local target_mode="$detected_mode"

    if [ -n "$DOCKER_MODE_OVERRIDE" ]; then
        target_mode="$DOCKER_MODE_OVERRIDE"
        _set_docker_mode "$target_mode"
    fi

    local mode_switch_required=false
    if [ "$detected_mode" != "$target_mode" ]; then
        mode_switch_required=true
    fi

    local runtime_desc="docker"
    if [ "$DOCKER_DEV" = true ] && [ "$DOCKER_IMAGE_STALE" = true ]; then
        runtime_desc="docker (dev — image stale, rebuilding)"
    elif [ "$DOCKER_DEV" = true ]; then
        runtime_desc="docker (dev — hot reload)"
    else
        runtime_desc="docker (production images)"
    fi
    local switch_desc=""
    [ "$mode_switch_required" = true ] && switch_desc="$detected_mode -> $target_mode"
    print_rebuild_header "$PROJECT_NAME Rebuild (Docker)" "$runtime_desc" "$switch_desc"

    if [ "$mode_switch_required" = true ]; then
        local switch_services="${stack_services:-$all_services}"
        if [ "$target_mode" = "dev" ]; then
            docker_recreate_services "$switch_services" false || ((errors++))
        else
            docker_recreate_services "$switch_services" false || ((errors++))
        fi
        docker_run_migration || true
    else
        # In dev mode with a stale image, escalate to full build+recreate
        local needs_build=false
        if [ "$DOCKER_DEV" = true ] && [ "$DOCKER_IMAGE_STALE" = true ]; then
            needs_build=true
        elif [ "$DOCKER_DEV" = false ]; then
            needs_build=true
        fi

        if [ "$needs_build" = false ]; then
        # Dev overlay, image is fresh: bind-mounted source, hot reload. Just restart + migrate.
            if [ "$RESTART_ONLY" = true ]; then
                docker_restart_services "$all_services" || ((errors++))
            elif [ "$FRONTEND_ONLY" = true ]; then
                docker_restart_services "$web_svc" || ((errors++))
            elif [ "$BACKEND_ONLY" = true ]; then
                local backend_svcs="$api_svc"
                # Include worker if it exists
                for s in $all_services; do [[ "$s" == *worker* ]] && backend_svcs="$backend_svcs $s"; done
                docker_restart_services "$backend_svcs" || ((errors++))
                docker_run_migration || true
            else
                docker_restart_services "$all_services" || ((errors++))
                docker_run_migration || true
            fi
        else
            # Production images: build → recreate → migrate
            if [ "$RESTART_ONLY" = true ]; then
                docker_restart_services "$all_services" || ((errors++))
            elif [ "$FRONTEND_ONLY" = true ]; then
                docker_build_and_recreate "$web_svc" || ((errors++))
            elif [ "$BACKEND_ONLY" = true ]; then
                local backend_svcs="$api_svc"
                for s in $all_services; do [[ "$s" == *worker* ]] && backend_svcs="$backend_svcs $s"; done
                docker_build_and_recreate "$backend_svcs" || ((errors++))
                docker_run_migration || true
            else
                docker_build_and_recreate "$all_services" || ((errors++))
                docker_run_migration || true
            fi
        fi
    fi

    if [ "$FRONTEND_ONLY" = false ]; then
        docker_reapply_hatchet_tuning || ((errors++))
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

    # Post-rebuild sync (only for summitflow backend)
    if [ "$FRONTEND_ONLY" = false ] && [ "$PROJECT_NAME" = "summitflow" ] && [ $errors -eq 0 ]; then
        local summitflow_api="${ST_API_BASE:-http://localhost:8001/api}"
        log "Regenerating project index..."
        local index_result=$(curl -s -X POST "$summitflow_api/projects/$PROJECT_NAME/explorer/regenerate-index" 2>/dev/null)
        echo "$index_result" | grep -q '"status":"success"' && log_success "Index regenerated" || log "Index regeneration skipped"
    fi

    local end_time=$(date +%s)
    local duration=$((end_time - start_time))

    print_rebuild_footer "$errors" "$duration"

    return $errors
}

# ─── Native (systemd) rebuild ────────────────────────────────────

main_native() {
    local start_time=$(date +%s)
    local errors=0

    if [ "$IS_WORKTREE" = true ]; then
        log_error "rebuild.sh targets shared project services, not task worktree services."
        echo ""
        echo "Use the isolated worktree service manager instead:"
        echo "  bash ~/summitflow/scripts/worktree-services.sh start ${WORKTREE_TASK_ID} --project ${PROJECT_NAME}"
        echo "  bash ~/summitflow/scripts/worktree-services.sh status ${WORKTREE_TASK_ID} --project ${PROJECT_NAME}"
        echo "  bash ~/summitflow/scripts/worktree-services.sh ports ${WORKTREE_TASK_ID} --project ${PROJECT_NAME}"
        echo ""
        exit 1
    fi

    print_rebuild_header "$PROJECT_NAME Rebuild" "native apps + docker infra"

    docker_ensure_infra || ((errors++))

    # Frontend rebuild (unless backend-only or restart-only)
    if [ "$BACKEND_ONLY" = false ] && [ "$RESTART_ONLY" = false ]; then
        clear_nextjs_cache || true
        build_frontend || { log_error "Frontend build failed"; ((errors++)); }
    fi

    if [ "$FRONTEND_ONLY" = false ] && [ "$HAS_BACKEND" != false ]; then
        run_native_migrations || ((errors++))
    fi

    # Restart services
    if [ "$FRONTEND_ONLY" = false ] && [ "$HAS_BACKEND" != false ]; then
        restart_service "$BACKEND_SERVICE" || ((errors++))
        for svc in $WORKER_SERVICES $AUXILIARY_SERVICES; do
            [ -n "$svc" ] || continue
            restart_service "$svc" || ((errors++))
        done
    fi

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

    # Post-rebuild sync tasks (only when backend rebuilt successfully)
    if [ "$FRONTEND_ONLY" = false ] && [ "$HAS_BACKEND" != false ] && [ $errors -eq 0 ]; then
        local summitflow_api="${ST_API_BASE:-http://localhost:8001/api}"
        log "Regenerating project index..."
        local index_result=$(curl -s -X POST "$summitflow_api/projects/$PROJECT_NAME/explorer/regenerate-index" 2>/dev/null)
        if echo "$index_result" | grep -q '"status":"success"'; then
            log_success "Index regenerated"
        else
            log "Index regeneration skipped (API may not be SummitFlow)"
        fi

        local export_script="$PROJECT_DIR/backend/scripts/export_seeds.py"
        if [ -f "$export_script" ]; then
            log "Syncing seed data from database..."
            if "$PROJECT_DIR/backend/.venv/bin/python" -m scripts.export_seeds 2>/dev/null; then
                log_success "Seed data synced"
            else
                log "Seed export skipped (non-fatal)"
            fi
        fi
    fi

    local end_time=$(date +%s)
    local duration=$((end_time - start_time))

    print_rebuild_footer "$errors" "$duration"

    return $errors
}

# ─── Entry point ─────────────────────────────────────────────────

detect_docker
DETECTED_RUNTIME_MODE="$RUNTIME_MODE"
DETECTED_DOCKER_MODE=$([ "$DOCKER_DEV" = true ] && echo "dev" || echo "prod")

if [ "$STATUS_ONLY" = true ]; then
    if [ "$RUNTIME_MODE" = "docker" ] || [ "$RUNTIME_MODE" = "docker-stopped" ]; then
        show_status_docker
    else
        show_status_native
    fi
    exit 0
fi

log_info "Detected runtime: $RUNTIME_MODE"
if [ "$RUNTIME_MODE" = "docker-stopped" ]; then
    if [ -n "$DOCKER_MODE_OVERRIDE" ] && [ "$DOCKER_MODE_OVERRIDE" != "$DETECTED_DOCKER_MODE" ]; then
        log "Persisting Docker mode: $DOCKER_MODE_OVERRIDE"
        _persist_runtime_mode
    fi
    docker_start_stack || exit 1
    if [ "$RESTART_ONLY" = true ] && [ "$FRONTEND_ONLY" = false ] && [ "$BACKEND_ONLY" = false ]; then
        detect_docker
        show_status_docker
        exit 0
    fi
    detect_docker
fi

if [ "$RUNTIME_MODE" = "docker" ] || [ "$RUNTIME_MODE" = "docker-stopped" ]; then
    main_docker
else
    main_native
fi
