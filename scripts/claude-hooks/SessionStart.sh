#!/bin/bash
# SessionStart hook for Claude Code - Inject recent context at session start
#
# This hook:
# 1. Checks for uncommitted work from previous sessions and commits/pushes
# 2. Fetches context from SummitFlow to inject into the session
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

# Check for uncommitted work from previous session
UNCOMMITTED=$(git status --porcelain 2>/dev/null | wc -l)
MESSAGES=""

if [[ "$UNCOMMITTED" -gt 0 ]]; then
    # Auto-commit leftover changes
    if git add -A 2>/dev/null && SKIP=mypy,pyright git commit -m "checkpoint: auto-save from previous session

🤖 Generated with [Claude Code](https://claude.com/claude-code)" 2>/dev/null; then
        # Try to push
        if git push 2>/dev/null; then
            MESSAGES="✅ Recovered ${UNCOMMITTED} uncommitted files from previous session (committed + pushed)."
        else
            MESSAGES="⚠️ Recovered ${UNCOMMITTED} uncommitted files (committed, push failed - run 'git push')."
        fi
    else
        MESSAGES="📁 Found ${UNCOMMITTED} uncommitted files from previous session. Consider committing."
    fi
fi

# API endpoint
API_BASE="${SUMMITFLOW_API:-http://localhost:8001/api}"

# Fetch context from SummitFlow
RESPONSE=$(curl -s --max-time 5 \
    "${API_BASE}/projects/${PROJECT_ID}/context/session-start?limit=10" \
    2>/dev/null) || exit 0

# Extract context_block from response
CONTEXT=$(echo "$RESPONSE" | jq -r '.context_block // empty' 2>/dev/null)

# Build output
OUTPUT=""

# Add recovery message if present
if [[ -n "$MESSAGES" ]]; then
    OUTPUT="${MESSAGES}\n\n"
fi

# Add context if present
if [[ -n "$CONTEXT" ]]; then
    OUTPUT="${OUTPUT}${CONTEXT}"
fi

# Output to stdout
if [[ -n "$OUTPUT" ]]; then
    echo -e "$OUTPUT"
fi

exit 0
