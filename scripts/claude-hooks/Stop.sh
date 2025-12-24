#!/usr/bin/env bash
#
# Stop hook - Context monitoring after each response.
#
# Monitors context usage and provides warnings:
# - 75-79%: Warning message
# - 80-84%: Wrap up warning - finish current task and notify user
# - 85-89%: Auto-commit + urgent warning
# - 90%+: Critical - end session immediately
#

set -euo pipefail

PROJECT_DIR="/home/kasadis/summitflow"
CONTEXT_SCRIPT="${PROJECT_DIR}/.claude/skills/context-manager/check.js"

# Thresholds
WARN_THRESHOLD=75
WRAP_UP_THRESHOLD=80
CHECKPOINT_THRESHOLD=85
CRITICAL_THRESHOLD=90
UNCOMMITTED_WARN_THRESHOLD=5

# Read stdin (JSON input)
INPUT=$(cat)

# Function to get context info
get_context_info() {
    if [[ -f "$CONTEXT_SCRIPT" ]]; then
        local output
        output=$(cd "$PROJECT_DIR" && node "$CONTEXT_SCRIPT" --json 2>/dev/null) || true
        if [[ -n "$output" ]]; then
            echo "$output"
            return 0
        fi
    fi
    echo '{"used_percent": 0}'
}

# Function to get uncommitted file count
get_uncommitted_count() {
    local count
    count=$(cd "$PROJECT_DIR" && git status --porcelain 2>/dev/null | grep -c "." || echo 0)
    echo "$count"
}

# Function to auto-commit
auto_commit() {
    local message="$1"
    cd "$PROJECT_DIR"
    if git add -A 2>/dev/null && git commit -m "$message" 2>/dev/null; then
        echo "committed"
    else
        echo "needs commit"
    fi
}

# Main logic
main() {
    local messages=()
    local context_json
    local context_pct

    context_json=$(get_context_info)
    context_pct=$(echo "$context_json" | python3 -c "import json,sys; print(json.load(sys.stdin).get('used_percent', 0))" 2>/dev/null || echo 0)

    # Convert to integer
    context_pct=${context_pct%.*}
    context_pct=${context_pct:-0}

    if (( context_pct >= CRITICAL_THRESHOLD )); then
        local commit_msg="checkpoint: auto-save at ${context_pct}% context"
        local status
        status=$(auto_commit "$commit_msg")
        messages+=("🔴 CRITICAL: ${context_pct}% context (${status}). END SESSION NOW. Tell user: 'I've reached context limit. Please start a new session.'")

    elif (( context_pct >= CHECKPOINT_THRESHOLD )); then
        local commit_msg="checkpoint: auto-save at ${context_pct}% context"
        local status
        status=$(auto_commit "$commit_msg")
        messages+=("🟠 HIGH: ${context_pct}% (${status}). Finish current task, commit, and notify user to start new session.")

    elif (( context_pct >= WRAP_UP_THRESHOLD )); then
        messages+=("🟡 WRAP UP: ${context_pct}% context. Finish current task, commit progress, then notify user you're at 80% and they should start a new session.")

    elif (( context_pct >= WARN_THRESHOLD )); then
        messages+=("📊 Context: ${context_pct}%. Approaching wrap-up threshold.")
    fi

    # Uncommitted files warning
    if (( context_pct < CHECKPOINT_THRESHOLD )); then
        local uncommitted
        uncommitted=$(get_uncommitted_count)
        if (( uncommitted >= UNCOMMITTED_WARN_THRESHOLD )); then
            messages+=("📁 ${uncommitted} uncommitted files. Consider committing.")
        fi
    fi

    # Output if we have messages
    if (( ${#messages[@]} > 0 )); then
        local joined
        joined=$(IFS=" | "; echo "${messages[*]}")
        echo "{\"systemMessage\": \"$joined\"}"
    fi
}

main
