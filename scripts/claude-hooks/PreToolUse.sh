#!/usr/bin/env bash
#
# PreToolUse hook - Git discipline enforcement before tool use.
#
# Warns if:
# - More than 10 uncommitted files AND last commit was >30 minutes ago
#
# This encourages regular commits during long sessions.
#

set -euo pipefail

# Read stdin (JSON input with tool_name, tool_input, cwd, etc.)
INPUT=$(cat)

# Extract cwd from input and detect project
CWD=$(echo "$INPUT" | jq -r '.cwd // empty' 2>/dev/null)
if [[ -z "$CWD" ]]; then
    exit 0
fi

# Detect project directory from git root
cd "$CWD" 2>/dev/null || exit 0
PROJECT_DIR=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0

# Thresholds
UNCOMMITTED_THRESHOLD=10
MINUTES_THRESHOLD=30

# Function to count uncommitted files
get_uncommitted_count() {
    local count
    count=$(cd "$PROJECT_DIR" && git status --porcelain 2>/dev/null | wc -l || echo 0)
    echo "$count"
}

# Function to get minutes since last commit
get_minutes_since_commit() {
    local last_commit_epoch
    local now_epoch
    local diff_seconds

    last_commit_epoch=$(cd "$PROJECT_DIR" && git log -1 --format=%ct 2>/dev/null || echo 0)
    now_epoch=$(date +%s)

    if (( last_commit_epoch == 0 )); then
        echo 0
        return
    fi

    diff_seconds=$((now_epoch - last_commit_epoch))
    echo $((diff_seconds / 60))
}

# Main logic
main() {
    local uncommitted
    local minutes_since_commit

    uncommitted=$(get_uncommitted_count)
    minutes_since_commit=$(get_minutes_since_commit)

    # Check if we should block
    if (( uncommitted > UNCOMMITTED_THRESHOLD && minutes_since_commit > MINUTES_THRESHOLD )); then
        cat <<EOF
{"decision": "block", "reason": "⚠️ Git discipline: ${uncommitted} uncommitted files and last commit was ${minutes_since_commit} minutes ago. Please commit your progress before continuing."}
EOF
    fi
}

main
