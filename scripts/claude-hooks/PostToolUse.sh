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

# Detect project ID from working directory
if [ -n "${SUMMITFLOW_PROJECT_ID:-}" ]; then
    PROJECT_ID="$SUMMITFLOW_PROJECT_ID"
elif [ -d "$CWD/.git" ]; then
    # Use git repo name as project ID
    PROJECT_ID=$(cd "$CWD" && basename "$(git rev-parse --show-toplevel 2>/dev/null)" | tr '[:upper:]' '[:lower:]')
else
    # Use current directory name
    PROJECT_ID=$(basename "$CWD" | tr '[:upper:]' '[:lower:]')
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

# Send to SummitFlow API (fire-and-forget)
(
    curl -s -X POST \
        -H "Content-Type: application/json" \
        -d "$PAYLOAD" \
        "${SUMMITFLOW_API_URL}/hooks/tool-use" \
        --connect-timeout 2 \
        --max-time 5 \
        > /dev/null 2>&1 || \
    echo "[$(date -Iseconds)] Failed to send to SummitFlow: $TOOL_NAME" >> "$LOG_FILE"
) &

# Exit immediately (don't block Claude Code)
exit 0
