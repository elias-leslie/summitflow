#!/bin/bash
# SessionStart hook for Claude Code - Inject recent context at session start
#
# This hook reads stdin (JSON with cwd), detects the project from git root,
# and fetches context from SummitFlow to inject into the session.
#
# All errors are handled silently (exit 0) to avoid blocking sessions.

set -e

# Read stdin JSON
INPUT=$(cat)

# Extract cwd from input
CWD=$(echo "$INPUT" | jq -r '.cwd // empty' 2>/dev/null)
if [[ -z "$CWD" ]]; then
    exit 0
fi

# Detect project from git root directory name
cd "$CWD" 2>/dev/null || exit 0
GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
PROJECT_ID=$(basename "$GIT_ROOT")

# API endpoint
API_BASE="${SUMMITFLOW_API:-http://localhost:8001/api}"

# Fetch context from SummitFlow
RESPONSE=$(curl -s --max-time 5 \
    "${API_BASE}/projects/${PROJECT_ID}/context/session-start?limit=10" \
    2>/dev/null) || exit 0

# Extract context_block from response
CONTEXT=$(echo "$RESPONSE" | jq -r '.context_block // empty' 2>/dev/null)

# Output context to stdout (if not empty)
if [[ -n "$CONTEXT" ]]; then
    echo "$CONTEXT"
fi

exit 0
