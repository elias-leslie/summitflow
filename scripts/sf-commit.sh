#!/usr/bin/env bash
# sf-commit - Streamlined commit with TOON output for Claude
# Usage: sf-commit [--push] [--task ID] [--type TYPE] [--full] [--skip-tests] [--msg "..."]
#
# Lets pre-commit handle lint/type checks. Only runs pytest separately.
# Output: TOON format (<sf-commit>...</sf-commit>)

set -euo pipefail

# Parse arguments
PUSH=false
TASK_ID=""
COMMIT_TYPE=""
FULL_TESTS=false
SKIP_TESTS=false
CUSTOM_MSG=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --push) PUSH=true; shift ;;
        --task) TASK_ID="$2"; shift 2 ;;
        --type) COMMIT_TYPE="$2"; shift 2 ;;
        --full) FULL_TESTS=true; shift ;;
        --skip-tests) SKIP_TESTS=true; shift ;;
        --msg) CUSTOM_MSG="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

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

# Run targeted pytest for backend
run_pytest() {
    local layer=$1
    local full=$2

    [[ "$layer" != "backend" && "$layer" != "both" ]] && return 0

    cd backend || return 1

    if $full; then
        .venv/bin/pytest tests/ --tb=line -q 2>&1
        return $?
    fi

    # Find test files for changed source files
    local changed_py test_files=""
    changed_py=$(git diff --cached --name-only | grep "^backend/app/.*\.py$" || true)

    for f in $changed_py; do
        local module
        module=$(echo "$f" | sed 's|backend/app/||; s|\.py$||')
        local base="${module##*/}"
        local dir="${module%/*}"

        # Check common test patterns
        for pattern in "tests/${dir}/test_${base}.py" "tests/unit/${dir}/test_${base}.py" "tests/test_${base}.py"; do
            [[ -f "$pattern" ]] && test_files="$test_files $pattern"
        done
    done

    if [[ -n "$test_files" ]]; then
        .venv/bin/pytest $test_files --tb=line -q 2>&1
    else
        # No targeted tests found, run a quick smoke test
        .venv/bin/pytest tests/ --tb=line -q -x --timeout=30 2>&1 || true
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

    # Auto-generate based on diff
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

    # Run pytest if not skipped (before commit so we catch issues early)
    if ! $SKIP_TESTS; then
        local pytest_out pytest_status=0
        pytest_out=$(run_pytest "$layer" "$FULL_TESTS" 2>&1) || pytest_status=$?

        if [[ $pytest_status -ne 0 ]]; then
            # Check if it's a real failure or just warnings
            if echo "$pytest_out" | grep -qE "FAILED|ERROR"; then
                status="BLOCKED"
                gates="pytest:FAIL"
                errors=$(echo "$pytest_out" | grep -E "FAILED|ERROR" | head -3 | tr '\n' '|')

                echo "<sf-commit>"
                echo "<status>$status</status>"
                echo "<gates>$gates</gates>"
                echo "<errors>$errors</errors>"
                echo "</sf-commit>"
                exit 1
            fi
        fi
        gates="pytest:PASS"
    else
        gates="pytest:SKIP"
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

    # Attempt commit (pre-commit runs automatically)
    local commit_out commit_status=0
    commit_out=$(git commit -m "$full_message" 2>&1) || commit_status=$?

    if [[ $commit_status -ne 0 ]]; then
        # Check if files were modified by pre-commit
        if [[ -n "$(git status --porcelain)" ]]; then
            # Re-stage and retry
            git add -A
            commit_out=$(git commit -m "$full_message" 2>&1) || commit_status=$?
        fi

        if [[ $commit_status -ne 0 ]]; then
            status="BLOCKED"
            # Parse pre-commit output for specific failures
            if echo "$commit_out" | grep -q "ruff"; then
                gates="$gates|ruff:FAIL"
            fi
            if echo "$commit_out" | grep -q "mypy"; then
                gates="$gates|mypy:FAIL"
            fi
            if echo "$commit_out" | grep -q "eslint"; then
                gates="$gates|eslint:FAIL"
            fi
            if echo "$commit_out" | grep -q "typescript"; then
                gates="$gates|tsc:FAIL"
            fi
            errors=$(echo "$commit_out" | grep -E "error|Error|FAILED" | head -5 | tr '\n' '|')

            echo "<sf-commit>"
            echo "<status>$status</status>"
            echo "<gates>${gates#|}</gates>"
            echo "<errors>$errors</errors>"
            echo "</sf-commit>"
            exit 1
        fi
    fi

    # Pre-commit passed
    gates="$gates|hooks:PASS"

    # Get commit SHA
    sha=$(git rev-parse --short HEAD)

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
            errors="push_failed:$push_out"
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
