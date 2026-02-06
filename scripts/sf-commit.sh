#!/usr/bin/env bash
# sf-commit - Streamlined commit with TOON output for Claude
# Version: 2.1.0
# Usage: sf-commit [--push] [--task ID] [--type TYPE] [--skip-checks] [--msg "..."]
#
# Delegates quality gates to `dt` (dev-tools) for consistent TOON output.
# Output: TOON format (<sf-commit>...</sf-commit>)

set -euo pipefail

# Parse arguments
PUSH=false
TASK_ID=""
COMMIT_TYPE=""
SKIP_CHECKS=false
CUSTOM_MSG=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --push) PUSH=true; shift ;;
        --task) TASK_ID="$2"; shift 2 ;;
        --type) COMMIT_TYPE="$2"; shift 2 ;;
        --skip-checks|--skip-tests) SKIP_CHECKS=true; shift ;;
        --msg) CUSTOM_MSG="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Use dt command (~/bin/dt -> ~/summitflow/scripts/dev-tools.sh)
# Falls back to direct path if dt not in PATH
if command -v dt &>/dev/null; then
    DEV_TOOLS="dt"
else
    DEV_TOOLS="$HOME/summitflow/scripts/dev-tools.sh"
fi

# Detect layers from staged + unstaged changes
detect_layers() {
    local files
    files=$(git diff --cached --name-only 2>/dev/null; git diff --name-only 2>/dev/null)

    local backend=false frontend=false
    while IFS= read -r f; do
        [[ "$f" =~ ^backend/ ]] && backend=true
        [[ "$f" =~ ^frontend/ ]] && frontend=true
    done <<< "$files"

    if $backend && $frontend; then
        echo "both"
    elif $backend; then
        echo "backend"
    elif $frontend; then
        echo "frontend"
    else
        echo "other"
    fi
}

# Detect commit type from changes
detect_type() {
    local staged
    staged=$(git diff --cached --name-only 2>/dev/null || true)

    # Check patterns
    if echo "$staged" | grep -qE "^.*/test.*\.py$|^.*_test\.py$|^.*\.test\.(ts|tsx|js)$"; then
        echo "test"
    elif echo "$staged" | grep -qE "requirements.*\.txt$|package.*\.json$|pyproject\.toml$"; then
        echo "deps"
    elif echo "$staged" | grep -qE "\.md$|docs/"; then
        echo "docs"
    elif git diff --cached --stat | grep -q "create mode"; then
        echo "feat"
    else
        echo "chore"
    fi
}

# Run quality gates via dt --quick --changed-only (lint+types on changed files only)
# This avoids failing on pre-existing issues in unchanged code
run_quality_gates() {
    if ! command -v "$DEV_TOOLS" &>/dev/null && [[ ! -x "$DEV_TOOLS" ]]; then
        echo "GATES:FAIL:dt not found"
        return 1
    fi

    # Use --quick --changed-only for fast pre-commit validation
    # Only checks changed files, ignores pre-existing issues elsewhere
    local output retval=0
    output=$("$DEV_TOOLS" --quick --changed-only 2>&1) || retval=$?

    # Parse TOON output for CHECK_RESULT line
    if echo "$output" | grep -q "CHECK_RESULT:OK"; then
        echo "GATES:OK"
        return 0
    else
        # Extract error count and return failure details
        local errors
        errors=$(echo "$output" | grep "CHECK_RESULT:FAIL" | sed 's/.*FAIL:\([0-9]*\).*/\1/' || echo "?")
        echo "GATES:FAIL:$errors|details:.dev-tools/"
        echo "$output"  # Include full output for debugging
        return 1
    fi
}

# Cross-layer check
cross_layer_check() {
    local warnings=""
    local backend_api
    backend_api=$(git diff --cached --name-only | grep "^backend/app/api/" | grep -v "__init__" | grep -v "deps.py" || true)

    for f in $backend_api; do
        local route
        route=$(basename "$f" .py)
        if ! grep -rq "$route" frontend/ 2>/dev/null; then
            warnings="$warnings|$route:no_frontend_ref"
        fi
    done

    echo "${warnings#|}"
}

# Generate commit message
generate_message() {
    local layer=$1
    local type=$2
    local task=$3
    local custom=$4

    # Use custom message if provided
    if [[ -n "$custom" ]]; then
        echo "$custom"
        return
    fi
    
    # Try AI Agent Generation
    if command -v st &>/dev/null; then
        local diff
        diff=$(git diff --cached 2>/dev/null)
        if [[ -n "$diff" ]]; then
            # Use st complete with --raw (JSON) output
            local json_out
            json_out=$(st complete --agent git-agent --raw "Generate a conventional commit message for the following diff. Output ONLY the message:\n\n$diff" 2>/dev/null)
            
            if [[ -n "$json_out" && ! "$json_out" =~ "Error" ]]; then
                # Extract content field using jq or python fallback if jq missing
                if command -v jq &>/dev/null; then
                    ai_msg=$(echo "$json_out" | jq -r '.content // empty')
                else
                    # Fallback python parser if jq missing
                    ai_msg=$(echo "$json_out" | python3 -c "import sys, json; print(json.load(sys.stdin).get('content', ''))")
                fi

                if [[ -n "$ai_msg" ]]; then
                    echo "$ai_msg"
                    return
                fi
            fi
        fi
    fi

    # Auto-generate based on diff (Fallback)
    local summary
    summary=$(git diff --cached --stat | tail -1 | sed 's/^ *//')

    local scope=""
    case $layer in
        backend) scope="(backend)" ;;
        frontend) scope="(frontend)" ;;
        both) scope="(fullstack)" ;;
    esac

    local title
    if [[ -n "$task" ]]; then
        title="${type}${scope}: ${task} - ${summary}"
    else
        title="${type}${scope}: ${summary}"
    fi

    echo "$title"
}

# Main execution
main() {
    local status="SUCCESS"
    local gates=""
    local sha=""
    local pushed="false"
    local message=""
    local errors=""

    # Check for changes
    if [[ -z "$(git status --porcelain)" ]]; then
        # No local changes — but if --push, check for unpushed commits
        if $PUSH; then
            local ahead
            ahead=$(git rev-list --count @{upstream}..HEAD 2>/dev/null || echo "0")
            if [[ "$ahead" -gt 0 ]]; then
                local push_out push_status=0
                push_out=$(git pull --rebase 2>&1 && git push 2>&1) || push_status=$?
                if [[ $push_status -eq 0 ]]; then
                    echo "<sf-commit>"
                    echo "<status>SUCCESS</status>"
                    echo "<reason>pushed_existing</reason>"
                    echo "<pushed>true</pushed>"
                    echo "</sf-commit>"
                    exit 0
                else
                    echo "<sf-commit>"
                    echo "<status>PARTIAL</status>"
                    echo "<reason>push_failed</reason>"
                    echo "<errors>$(echo "$push_out" | head -2 | tr '\n' ' ')</errors>"
                    echo "</sf-commit>"
                    exit 1
                fi
            fi
        fi
        echo "<sf-commit>"
        echo "<status>SKIP</status>"
        echo "<reason>no_changes</reason>"
        echo "</sf-commit>"
        exit 0
    fi

    # Detect context
    local layer type
    layer=$(detect_layers)
    type=${COMMIT_TYPE:-$(detect_type)}

    # Stage all changes
    git add -A

    # Run quality gates BEFORE commit (via dt)
    if ! $SKIP_CHECKS; then
        local gates_out gates_status=0
        gates_out=$(run_quality_gates 2>&1) || gates_status=$?

        if [[ $gates_status -ne 0 ]]; then
            echo "<sf-commit>"
            echo "<status>BLOCKED</status>"
            echo "<gates>$gates_out</gates>"
            echo "</sf-commit>"
            exit 1
        fi
        gates="checks:PASS"
    else
        gates="checks:SKIP"
    fi

    # Generate message
    message=$(generate_message "$layer" "$type" "$TASK_ID" "$CUSTOM_MSG")

    # Format full commit message with co-author
    local full_message
    full_message=$(cat <<EOF
$message

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)

    # Attempt commit - skip lint/types in pre-commit (already ran via dt)
    # Pre-commit still runs formatters (ruff-format, prettier, trailing-whitespace, etc.)
    local commit_out commit_status=0
    commit_out=$(SKIP=ruff,mypy,eslint,tsc git commit -m "$full_message" 2>&1) || commit_status=$?

    if [[ $commit_status -ne 0 ]]; then
        # Check if files were modified by pre-commit formatters
        if [[ -n "$(git status --porcelain)" ]]; then
            # Re-stage formatted files and retry
            git add -A
            commit_out=$(SKIP=ruff,mypy,eslint,tsc git commit -m "$full_message" 2>&1) || commit_status=$?
        fi

        if [[ $commit_status -ne 0 ]]; then
            # Commit still failed - likely pre-commit found new issues
            echo "<sf-commit>"
            echo "<status>BLOCKED</status>"
            echo "<gates>$gates|hooks:FAIL</gates>"
            echo "<errors>$(echo "$commit_out" | grep -E "error|Error|FAILED" | head -5 | tr '\n' '|')</errors>"
            echo "</sf-commit>"
            exit 1
        fi
    fi

    gates="$gates|hooks:PASS"
    sha=$(git rev-parse --short HEAD)

    # Follow-up commit for formatter leftovers
    # Pre-commit formatters (ruff-format, prettier, trailing-whitespace) may leave
    # dirty files after a successful commit. Commit those before pushing so users
    # don't need to run smart-sync twice.
    if [[ -n "$(git status --porcelain)" ]]; then
        git add -A
        local followup_status=0
        SKIP=ruff,mypy,eslint,tsc git commit -m "style: auto-format from pre-commit hooks" 2>&1 || followup_status=$?
        if [[ $followup_status -eq 0 ]]; then
            sha=$(git rev-parse --short HEAD)
            gates="$gates|followup:PASS"
        fi
    fi

    # Cross-layer check (warning only)
    local cross_warn
    cross_warn=$(cross_layer_check)
    [[ -n "$cross_warn" ]] && gates="$gates|cross:WARN($cross_warn)"

    # Push if requested
    if $PUSH; then
        local push_out push_status=0
        push_out=$(git pull --rebase 2>&1 && git push 2>&1) || push_status=$?

        if [[ $push_status -eq 0 ]]; then
            pushed="true"
        else
            status="PARTIAL"
            errors="push_failed:$(echo "$push_out" | head -2 | tr '\n' ' ')"
        fi
    fi

    # Output TOON format
    echo "<sf-commit>"
    echo "<status>$status</status>"
    echo "<gates>${gates#|}</gates>"
    echo "<sha>$sha</sha>"
    echo "<message>$message</message>"
    echo "<pushed>$pushed</pushed>"
    [[ -n "$errors" ]] && echo "<errors>$errors</errors>"
    echo "</sf-commit>"
}

main "$@"
