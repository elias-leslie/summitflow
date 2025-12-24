#!/bin/bash
# PostToolUse hook for Claude Code
# Captures tool executions and sends to SummitFlow for observation extraction
#
# Data from Claude Code (passed via stdin as JSON):
# - session_id: Claude Code session ID
# - hook_event_name: "PostToolUse"
# - tool_name: Name of the executed tool
# - tool_input: JSON object of tool parameters
# - tool_response: Output from the tool execution
# - cwd: Current working directory
# - transcript_path: Path to conversation transcript
#
# Configuration:
# - SUMMITFLOW_PROJECT_ID: Project to capture observations for (default: from pwd)
# - SUMMITFLOW_API_URL: API endpoint (default: http://localhost:8001/api)
# - SUMMITFLOW_ENABLED: Set to "0" to disable capture (default: "1")

set -euo pipefail

# Configuration
SUMMITFLOW_API_URL="${SUMMITFLOW_API_URL:-http://localhost:8001/api}"
SUMMITFLOW_ENABLED="${SUMMITFLOW_ENABLED:-1}"
LOG_FILE="$HOME/.claude/hooks/summitflow.log"

# Commit reminder configuration
COMMIT_REMINDER_COUNTER_FILE="$HOME/.claude/hooks/.write-edit-counter"
COMMIT_REMINDER_INTERVAL=5
UNCOMMITTED_THRESHOLD=3

# Exit if disabled
if [ "$SUMMITFLOW_ENABLED" = "0" ]; then
    exit 0
fi

# Ensure log directory exists
mkdir -p "$(dirname "$LOG_FILE")"

# Read input from stdin
INPUT=$(cat)

# Parse hook event (Claude Code passes data as JSON via stdin)
HOOK_EVENT=$(echo "$INPUT" | jq -r '.hook_event_name // empty')

# Only process PostToolUse events
if [ "$HOOK_EVENT" != "PostToolUse" ]; then
    exit 0
fi

# Extract fields from input
# Claude Code uses 'tool_response' not 'tool_output'
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // "unknown"')
TOOL_INPUT=$(echo "$INPUT" | jq -c '.tool_input // {}')
TOOL_OUTPUT=$(echo "$INPUT" | jq -r '.tool_response // ""')

# Get session ID from Claude Code input or generate from timestamp
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty')
if [ -z "$SESSION_ID" ]; then
    SESSION_ID="claude-$(date +%s)"
fi

# Get working directory from Claude Code input or use current dir
CWD=$(echo "$INPUT" | jq -r '.cwd // empty')
if [ -z "$CWD" ]; then
    CWD="$(pwd)"
fi

# Detect project ID from git root (most reliable)
# Server-side validates against registered projects in database
if [ -n "${SUMMITFLOW_PROJECT_ID:-}" ]; then
    PROJECT_ID="$SUMMITFLOW_PROJECT_ID"
else
    # Find git root and use repo name as project ID
    GIT_ROOT=$(cd "$CWD" && git rev-parse --show-toplevel 2>/dev/null)
    if [ -n "$GIT_ROOT" ]; then
        PROJECT_ID=$(basename "$GIT_ROOT" | tr '[:upper:]' '[:lower:]')
    else
        # Not in a git repo - skip capture (can't reliably identify project)
        exit 0
    fi
fi

# Build request payload
PAYLOAD=$(jq -n \
    --arg project_id "$PROJECT_ID" \
    --arg session_id "$SESSION_ID" \
    --arg tool_name "$TOOL_NAME" \
    --argjson tool_input "$TOOL_INPUT" \
    --arg tool_output "$TOOL_OUTPUT" \
    '{
        project_id: $project_id,
        session_id: $session_id,
        tool_name: $tool_name,
        tool_input: $tool_input,
        tool_output: $tool_output
    }'
)

# Send to SummitFlow API and check response
# Run synchronously but with tight timeouts to minimize CLI blocking
RESPONSE=$(curl -s -X POST \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD" \
    "${SUMMITFLOW_API_URL}/hooks/tool-use" \
    --connect-timeout 1 \
    --max-time 3 \
    2>/dev/null) || RESPONSE=""

# Check if observation was skipped (unknown project)
if [ -n "$RESPONSE" ]; then
    QUEUED=$(echo "$RESPONSE" | jq -r '.queued // true')
    QUEUE_ID=$(echo "$RESPONSE" | jq -r '.queue_item_id // ""')

    if [ "$QUEUED" = "false" ] && [ "$QUEUE_ID" = "skipped-unknown-project" ]; then
        # Rate limit CLI warnings - one per project per 10 minutes
        WARN_FILE="$HOME/.claude/hooks/.warned-$PROJECT_ID"
        WARN_COOLDOWN=600  # 10 minutes

        SHOULD_WARN=true
        if [ -f "$WARN_FILE" ]; then
            LAST_WARN=$(cat "$WARN_FILE" 2>/dev/null || echo 0)
            NOW=$(date +%s)
            if [ $((NOW - LAST_WARN)) -lt $WARN_COOLDOWN ]; then
                SHOULD_WARN=false
            fi
        fi

        if [ "$SHOULD_WARN" = "true" ]; then
            # Output warning to stderr so it's visible in CLI
            echo "⚠️  SummitFlow: Project '$PROJECT_ID' not registered. Observations not captured." >&2
            echo "[$(date -Iseconds)] Unknown project skipped: $PROJECT_ID" >> "$LOG_FILE"
            date +%s > "$WARN_FILE"
        fi
    fi
elif [ -z "$RESPONSE" ]; then
    # API request failed - log but don't warn (might just be offline)
    echo "[$(date -Iseconds)] API request failed for: $TOOL_NAME" >> "$LOG_FILE"
fi

# Periodic commit reminder for Write/Edit tools
if [ "$TOOL_NAME" = "Write" ] || [ "$TOOL_NAME" = "Edit" ]; then
    # Increment counter
    CURRENT_COUNT=0
    if [ -f "$COMMIT_REMINDER_COUNTER_FILE" ]; then
        CURRENT_COUNT=$(cat "$COMMIT_REMINDER_COUNTER_FILE" 2>/dev/null || echo 0)
    fi
    NEW_COUNT=$((CURRENT_COUNT + 1))
    echo "$NEW_COUNT" > "$COMMIT_REMINDER_COUNTER_FILE"

    # Check if we should remind
    if [ $((NEW_COUNT % COMMIT_REMINDER_INTERVAL)) -eq 0 ]; then
        # Count uncommitted files
        UNCOMMITTED=$(git status --porcelain 2>/dev/null | wc -l || echo 0)
        if [ "$UNCOMMITTED" -ge "$UNCOMMITTED_THRESHOLD" ]; then
            echo "{\"systemMessage\": \"📝 Commit reminder: ${UNCOMMITTED} uncommitted files after ${NEW_COUNT} Write/Edit operations.\"}"
        fi
    fi
fi

exit 0
