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
    # Check if last commit was a checkpoint (deduplication)
    LAST_MSG=$(git log -1 --format=%s 2>/dev/null || echo "")

    if [[ "$LAST_MSG" == "checkpoint: auto-save from previous session" ]]; then
        # Amend the existing checkpoint instead of creating a new one
        if git add -A 2>/dev/null && git commit --amend --no-edit 2>/dev/null; then
            if git push --force-with-lease 2>/dev/null; then
                MESSAGES="✅ Recovered ${UNCOMMITTED} uncommitted files (amended existing checkpoint + pushed)."
            else
                MESSAGES="⚠️ Recovered ${UNCOMMITTED} uncommitted files (amended, push failed - run 'git push')."
            fi
        else
            MESSAGES="📁 Found ${UNCOMMITTED} uncommitted files from previous session. Consider committing."
        fi
    else
        # Create new checkpoint commit
        if git add -A 2>/dev/null && git commit -m "checkpoint: auto-save from previous session

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
fi

# API endpoint
API_BASE="${SUMMITFLOW_API:-http://localhost:8001/api}"

# Collect git state for context injection
CURRENT_TIME=$(date '+%Y-%m-%d %H:%M %Z')
RECENT_FILES=$(git log -1 --name-only --pretty=format: 2>/dev/null | head -5 | paste -sd, 2>/dev/null || echo "")

# Build JSON request body
REQUEST_BODY=$(jq -n \
    --arg current_time "$CURRENT_TIME" \
    --arg recent_files "$RECENT_FILES" \
    --argjson uncommitted "$UNCOMMITTED" \
    '{current_time: $current_time, recent_files: $recent_files, uncommitted_count: $uncommitted}')

# Fetch context from SummitFlow (POST with JSON body)
RESPONSE=$(curl -s --max-time 5 \
    -X POST \
    -H "Content-Type: application/json" \
    -d "$REQUEST_BODY" \
    "${API_BASE}/projects/${PROJECT_ID}/context/session-start" \
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
