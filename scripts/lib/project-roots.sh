#!/usr/bin/env bash

PROJECT_ROOTS_WORKSPACES_ROOT="${ST_WORKSPACES_ROOT:-/srv/workspaces}"

project_root_from_cli() {
    local project="$1"

    command -v st >/dev/null 2>&1 || return 1

    local root_path
    root_path="$(ST_PROGRESS_ONLY=1 st projects root "$project" 2>/dev/null | head -n 1 | tr -d '\r')"
    [ -n "$root_path" ] || return 1
    printf '%s\n' "$root_path"
}

default_home_root_for_project() {
    case "$1" in
        summitflow)
            [ -n "${SUMMITFLOW_ROOT_OVERRIDE:-}" ] || return 1
            printf '%s\n' "$SUMMITFLOW_ROOT_OVERRIDE"
            ;;
        agent-hub | portfolio-ai | terminal | monkey-fight)
            printf '%s\n' "$HOME/$1"
            ;;
        *)
            return 1
            ;;
    esac
}

resolve_project_root() {
    local project="$1"
    local candidate

    if [ "$project" = "summitflow" ] && [ -n "${SUMMITFLOW_ROOT_OVERRIDE:-}" ] && [ -d "${SUMMITFLOW_ROOT_OVERRIDE}" ]; then
        printf '%s\n' "$SUMMITFLOW_ROOT_OVERRIDE"
        return 0
    fi

    candidate="$(project_root_from_cli "$project" 2>/dev/null || true)"
    if [ -n "$candidate" ] && [ -d "$candidate" ]; then
        printf '%s\n' "$candidate"
        return 0
    fi

    candidate="${PROJECT_ROOTS_WORKSPACES_ROOT}/projects/$project"
    if [ -d "$candidate" ]; then
        printf '%s\n' "$candidate"
        return 0
    fi

    candidate="$(default_home_root_for_project "$project" 2>/dev/null || true)"
    if [ -n "$candidate" ] && [ -d "$candidate" ]; then
        printf '%s\n' "$candidate"
        return 0
    fi

    return 1
}
