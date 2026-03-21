#!/bin/bash
#
# backup-all.sh - Back up all registered backup sources in sequence
# Discovers sources from SummitFlow backup_sources API, runs backup.sh in each.
# Replaces per-project systemd service/timer pairs with a single invocation.
#
# Usage:
#   ./scripts/backup-all.sh              # Full backup (SMB)
#   ./scripts/backup-all.sh --local      # Local only
#   ./scripts/backup-all.sh --status     # Show status for all repos
#
# All flags are passed through to backup.sh per-repo.

set -uo pipefail

SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
SUMMITFLOW_API="${ST_API_BASE:-http://localhost:8001/api}/backup-sources"
FALLBACK_FILE="$HOME/.claude/config/managed-repos.txt"
STAGGER_DELAY=60  # seconds between backups

# Discover all registered backup source paths.
get_managed_repos() {
    local repos=()

    local api_response
    if api_response=$(curl -sf --connect-timeout 2 "$SUMMITFLOW_API" 2>/dev/null); then
        if command -v jq &>/dev/null; then
            while IFS= read -r path; do
                [[ -d "$path" ]] && repos+=("$path")
            done < <(echo "$api_response" | jq -r '.[].path // empty')
        else
            while IFS= read -r path; do
                [[ -d "$path" ]] && repos+=("$path")
            done < <(echo "$api_response" | grep -o '"path":"[^"]*"' | sed 's/"path":"//;s/"$//')
        fi
    else
        if [[ -f "$FALLBACK_FILE" ]]; then
            while IFS= read -r line || [[ -n "$line" ]]; do
                [[ "$line" =~ ^[[:space:]]*# ]] && continue
                [[ -z "${line// }" ]] && continue
                local expanded="${line/#\~/$HOME}"
                [[ -d "$expanded" ]] && repos+=("$expanded")
            done < "$FALLBACK_FILE"
        fi
    fi

    printf '%s\n' "${repos[@]}" | awk '!seen[$0]++'
}

main() {
    local passthrough_args=("$@")
    local status_only=false

    for arg in "${passthrough_args[@]}"; do
        if [[ "$arg" == "--status" ]]; then
            status_only=true
            break
        fi
    done

    mapfile -t repos < <(get_managed_repos)

    if [[ ${#repos[@]} -eq 0 ]]; then
        echo "ERROR: no repos found"
        exit 1
    fi

    echo "========================================"
    echo "Backup All (${#repos[@]} repos)"
    echo "========================================"
    echo ""

    local success=0 fail=0 skip=0
    local first=true

    for repo in "${repos[@]}"; do
        local repo_name
        repo_name=$(basename "$repo")

        if ! $first && ! $status_only; then
            echo ""
            echo "--- Stagger delay: ${STAGGER_DELAY}s ---"
            sleep "$STAGGER_DELAY"
        fi
        first=false

        echo ""
        echo ">> Backing up: $repo_name ($repo)"

        if ! [[ -d "$repo" ]]; then
            echo "  SKIP: directory not found"
            ((skip++))
            continue
        fi

        if (cd "$repo" && bash "$SCRIPT_DIR/backup.sh" "${passthrough_args[@]}"); then
            ((success++))
        else
            echo "  ERROR: backup failed for $repo_name"
            ((fail++))
        fi
    done

    echo ""
    echo "========================================"
    echo "BACKUP_ALL[${#repos[@]}]: ok=${success} skip=${skip} err=${fail}"
    echo "========================================"

    [[ $fail -gt 0 ]] && exit 1
    exit 0
}

main "$@"
