#!/bin/bash
#
# backup-all.sh - Back up all managed repos in sequence
# Discovers repos from SummitFlow API + CONFIG_REPOS, runs backup.sh in each.
# Replaces per-project systemd service/timer pairs with a single invocation.
#
# Usage:
#   ./scripts/backup-all.sh              # Full backup (SMB)
#   ./scripts/backup-all.sh --local      # Local only
#   ./scripts/backup-all.sh --status     # Show status for all repos
#
# All flags are passed through to backup.sh per-repo.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUMMITFLOW_API="http://localhost:8001/api/projects"
CONFIG_REPOS=("$HOME/.claude" "$HOME/persona-sandbox")
FALLBACK_FILE="$HOME/.claude/config/managed-repos.txt"
STAGGER_DELAY=60  # seconds between backups

# Discover all managed repos (same logic as commit.sh)
get_managed_repos() {
    local repos=()

    local api_response
    if api_response=$(curl -sf --connect-timeout 2 "$SUMMITFLOW_API" 2>/dev/null); then
        if command -v jq &>/dev/null; then
            while IFS= read -r path; do
                [[ -d "$path/.git" ]] && repos+=("$path")
            done < <(echo "$api_response" | jq -r '.[].root_path // empty')
        else
            while IFS= read -r path; do
                [[ -d "$path/.git" ]] && repos+=("$path")
            done < <(echo "$api_response" | grep -o '"root_path":"[^"]*"' | sed 's/"root_path":"//;s/"$//')
        fi
    else
        if [[ -f "$FALLBACK_FILE" ]]; then
            while IFS= read -r line || [[ -n "$line" ]]; do
                [[ "$line" =~ ^[[:space:]]*# ]] && continue
                [[ -z "${line// }" ]] && continue
                local expanded="${line/#\~/$HOME}"
                [[ -d "$expanded/.git" ]] && repos+=("$expanded")
            done < "$FALLBACK_FILE"
        fi
    fi

    for config_repo in "${CONFIG_REPOS[@]}"; do
        [[ -d "$config_repo/.git" ]] && repos+=("$config_repo")
    done

    printf '%s\n' "${repos[@]}" | awk '!seen[$0]++'
}

main() {
    local passthrough_args=("$@")

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

        if ! $first; then
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
