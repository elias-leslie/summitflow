#!/usr/bin/env bash
#
# Stop hook - Context monitoring after each response.
#
# Monitors context usage and takes action:
# - 75-79%: Warning message only
# - 80-84%: Auto-commit + wrap up warning
# - 85-89%: Auto-commit + auto-push + urgent warning
# - 90%+: Auto-commit + auto-push + critical end session
#

set -euo pipefail

# Context script location (git versioned in summitflow)
CONTEXT_SCRIPT="/home/kasadis/summitflow/.claude/skills/context-manager/check.js"

# Thresholds
WARN_THRESHOLD=75
WRAP_UP_THRESHOLD=80
CHECKPOINT_THRESHOLD=85
CRITICAL_THRESHOLD=90
UNCOMMITTED_WARN_THRESHOLD=5

# Read stdin (JSON input)
INPUT=$(cat)

# Extract cwd from input and detect project
CWD=$(echo "$INPUT" | jq -r '.cwd // empty' 2>/dev/null)
if [[ -z "$CWD" ]]; then
    exit 0
fi

# Detect project directory from git root
cd "$CWD" 2>/dev/null || exit 0
PROJECT_DIR=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
PROJECT_ID=$(basename "$PROJECT_DIR")

# Function to get context info
get_context_info() {
    if [[ -f "$CONTEXT_SCRIPT" ]]; then
        local output
        # Pass project ID to context script
        output=$(node "$CONTEXT_SCRIPT" --json --project "$PROJECT_ID" 2>/dev/null) || true
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
    if git add -A 2>/dev/null && SKIP=mypy,pyright git commit -m "$message" 2>/dev/null; then
        echo "committed"
    else
        echo "nothing to commit"
    fi
}

# Function to auto-push
auto_push() {
    cd "$PROJECT_DIR"
    if git push 2>/dev/null; then
        echo "pushed"
    else
        echo "push failed"
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
        local commit_status push_status
        commit_status=$(auto_commit "$commit_msg")
        push_status=$(auto_push)
        messages+=("🔴 CRITICAL: ${context_pct}% context (${commit_status}, ${push_status}). END SESSION NOW. Tell user: 'I've reached context limit. Please start a new session.'")

    elif (( context_pct >= CHECKPOINT_THRESHOLD )); then
        local commit_msg="checkpoint: auto-save at ${context_pct}% context"
        local commit_status push_status
        commit_status=$(auto_commit "$commit_msg")
        push_status=$(auto_push)
        messages+=("🟠 HIGH: ${context_pct}% (${commit_status}, ${push_status}). Finish current task and notify user to start new session.")

    elif (( context_pct >= WRAP_UP_THRESHOLD )); then
        local commit_msg="checkpoint: auto-save at ${context_pct}% context"
        local commit_status
        commit_status=$(auto_commit "$commit_msg")
        messages+=("🟡 WRAP UP: ${context_pct}% context (${commit_status}). Finish current task, then notify user you're at 80% and they should start a new session.")

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
