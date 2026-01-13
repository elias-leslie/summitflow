#!/bin/bash
#
# Universal Dev Standards Script
# Enforces consistent dev tooling, testing, and quality gates across all projects
# Works for any project - auto-detects project from PWD/git root
#
# Usage:
#   ./scripts/dev-standards.sh              # Dashboard of all projects (default)
#   ./scripts/dev-standards.sh --check      # Full quality gate (lint, types, tests)
#   ./scripts/dev-standards.sh --fix        # Auto-fix + install deps + pre-commit install
#   ./scripts/dev-standards.sh --fix-all    # Fix all managed projects
#   ./scripts/dev-standards.sh --rebuild-venv  # Nuclear option: delete and recreate venv
#

set -o pipefail

# =============================================================================
# SETUP
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/dev-standards-config.sh"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# Project detection
PROJECT_DIR=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
PROJECT_NAME=$(basename "$PROJECT_DIR")
VENV_PATH=$(get_venv_path "$PROJECT_NAME" "$PROJECT_DIR")
BACKEND_PATH=$(get_backend_path "$PROJECT_NAME" "$PROJECT_DIR")

# Parse arguments
ACTION="status"
TARGET="all"

for arg in "$@"; do
    case $arg in
        --check|-c) ACTION="check"; TARGET="current" ;;
        --fix|-f) ACTION="fix"; TARGET="current" ;;
        --fix-all) ACTION="fix"; TARGET="all" ;;
        --rebuild-venv) ACTION="rebuild"; TARGET="current" ;;
        --help|-h) ACTION="help" ;;
    esac
done

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_header() { echo -e "\n${BOLD}${CYAN}=== $1 ===${NC}"; }

# Get installed version of a package
get_installed_version() {
    local venv="$1"
    local package="$2"

    if [[ -f "${venv}/bin/pip" ]]; then
        "${venv}/bin/pip" show "$package" 2>/dev/null | grep "^Version:" | awk '{print $2}' || echo ""
    else
        echo ""
    fi
}

# Check if venv exists and is valid
check_venv() {
    local venv="$1"
    [[ -f "${venv}/bin/python" ]] && [[ -f "${venv}/bin/pip" ]]
}

# Rebuild venv from scratch
rebuild_venv() {
    local project_dir="$1"
    local project_name=$(basename "$project_dir")
    local venv=$(get_venv_path "$project_name" "$project_dir")

    echo "REBUILD_VENV:$project_name"

    # Find Python 3.12+ (prefer 3.13)
    local python_bin=""
    for py in python3.13 python3.12 python3; do
        if command -v "$py" &>/dev/null; then
            local ver=$("$py" --version 2>&1 | grep -oP '\d+\.\d+')
            if [[ $(echo "$ver >= 3.12" | bc -l) -eq 1 ]]; then
                python_bin="$py"
                break
            fi
        fi
    done

    if [[ -z "$python_bin" ]]; then
        echo "ERROR:no_python_3.12+"
        return 1
    fi

    # Remove old venv
    if [[ -d "$venv" ]]; then
        rm -rf "$venv"
        echo "  removed:$venv"
    fi

    # Create new venv
    if ! "$python_bin" -m venv "$venv" 2>/dev/null; then
        echo "ERROR:venv_creation_failed"
        return 1
    fi
    echo "  created:$venv"

    # Install dev deps
    install_deps "$project_dir"
}

# =============================================================================
# SINGLE PROJECT FUNCTIONS
# =============================================================================

install_deps() {
    local project_dir="$1"
    local project_name=$(basename "$project_dir")
    local venv=$(get_venv_path "$project_name" "$project_dir")

    echo "INSTALL:$project_name"

    if ! check_venv "$venv"; then
        echo "ERROR:venv_missing:$venv"
        return 1
    fi

    local installed=0
    local failed=0

    for pkg_spec in "ruff==$CANONICAL_RUFF" "mypy==$CANONICAL_MYPY" "pytest==$CANONICAL_PYTEST" \
                    "pytest-asyncio==$CANONICAL_PYTEST_ASYNCIO" "pytest-cov==$CANONICAL_PYTEST_COV" \
                    "pre-commit==$CANONICAL_PRECOMMIT"; do
        local pkg="${pkg_spec%%==*}"
        if "${venv}/bin/pip" install -q "$pkg_spec" 2>/dev/null; then
            ((installed++))
        else
            echo "  FAIL:$pkg"
            ((failed++))
        fi
    done

    echo "INSTALLED:$installed|FAILED:$failed"
}

run_lint() {
    local project_dir="$1"
    local project_name=$(basename "$project_dir")
    local venv=$(get_venv_path "$project_name" "$project_dir")
    local backend=$(get_backend_path "$project_name" "$project_dir")
    local fix_mode="$2"

    echo "LINT:$project_name"

    local ruff_bin="${venv}/bin/ruff"
    local ruff_src="venv"
    if [[ ! -x "$ruff_bin" ]]; then
        ruff_bin=$(which ruff 2>/dev/null || echo "")
        ruff_src="global"
        if [[ -z "$ruff_bin" ]]; then
            echo "ERROR:ruff_not_found"
            return 1
        fi
    fi

    local app_dir="$backend/app"
    [[ ! -d "$app_dir" ]] && app_dir="$backend"

    if [[ "$fix_mode" == "fix" ]]; then
        "$ruff_bin" check "$app_dir" --fix 2>&1 >/dev/null || true
        "$ruff_bin" format "$app_dir" 2>&1 >/dev/null || true
        echo "FIXED:ruff=$ruff_src"
    else
        # Use concise format for reliable one-line-per-violation counting
        # wc -l always succeeds, avoiding pipefail issues
        local violations
        violations=$("$ruff_bin" check "$app_dir" --output-format=concise 2>&1 | wc -l) || true
        if [[ "$violations" -eq 0 ]]; then
            echo "OK:violations=0"
        else
            echo "FAIL:violations=$violations"
            return 1
        fi
    fi
}

run_types() {
    local project_dir="$1"
    local project_name=$(basename "$project_dir")
    local venv=$(get_venv_path "$project_name" "$project_dir")
    local backend=$(get_backend_path "$project_name" "$project_dir")

    echo "TYPES:$project_name"

    local mypy_bin="${venv}/bin/mypy"
    if [[ ! -x "$mypy_bin" ]]; then
        echo "ERROR:mypy_not_found"
        return 1
    fi

    local app_dir="$backend/app"
    [[ ! -d "$app_dir" ]] && app_dir="$backend"

    cd "$backend"
    # Capture output first, then count errors to avoid pipefail issues
    local output errors
    output=$("$mypy_bin" "$app_dir" --ignore-missing-imports 2>&1) || true
    errors=$(echo "$output" | grep -c "error:") || errors=0
    if [[ "$errors" -eq 0 ]]; then
        echo "OK:errors=0"
    else
        echo "FAIL:errors=$errors"
        return 1
    fi
}

run_tests() {
    local project_dir="$1"
    local project_name=$(basename "$project_dir")
    local venv=$(get_venv_path "$project_name" "$project_dir")
    local backend=$(get_backend_path "$project_name" "$project_dir")

    echo "TEST:$project_name"

    local pytest_bin="${venv}/bin/pytest"
    if [[ ! -x "$pytest_bin" ]]; then
        echo "ERROR:pytest_not_found"
        return 1
    fi

    cd "$backend"
    # Use pytest exit code, not text matching (avoids "6 failed, 677 passed" false positive)
    local output retval=0
    output=$("$pytest_bin" --tb=no -q 2>&1) || retval=$?
    local summary=$(echo "$output" | tail -1)

    if [[ $retval -eq 0 ]]; then
        echo "OK:$summary"
    else
        echo "FAIL:$summary"
        return 1
    fi
}

run_hooks() {
    local project_dir="$1"
    local project_name=$(basename "$project_dir")
    local venv=$(get_venv_path "$project_name" "$project_dir")

    echo "HOOKS:$project_name"

    local precommit_bin="${venv}/bin/pre-commit"
    if [[ ! -x "$precommit_bin" ]]; then
        echo "ERROR:precommit_not_found"
        return 1
    fi

    cd "$project_dir"
    if "$precommit_bin" run --all-files >/dev/null 2>&1; then
        echo "OK:all_passed"
    else
        echo "FAIL:hook_errors"
        return 1
    fi
}

full_check() {
    local project_dir="$1"
    local project_name=$(basename "$project_dir")
    local errors=0

    echo "CHECK:$project_name"
    run_lint "$project_dir" || ((errors++))
    run_types "$project_dir" || ((errors++))
    run_tests "$project_dir" || ((errors++))

    if [[ $errors -eq 0 ]]; then
        echo "CHECK_RESULT:OK"
    else
        echo "CHECK_RESULT:FAIL:$errors"
    fi

    return $errors
}

full_fix() {
    local project_dir="$1"
    local project_name=$(basename "$project_dir")
    local venv=$(get_venv_path "$project_name" "$project_dir")
    local errors=0

    echo "FIX:$project_name"
    install_deps "$project_dir" || ((errors++))
    run_lint "$project_dir" "fix"

    # Install pre-commit hooks into git
    local precommit_bin="${venv}/bin/pre-commit"
    if [[ -x "$precommit_bin" && -f "$project_dir/.pre-commit-config.yaml" ]]; then
        cd "$project_dir"
        if "$precommit_bin" install >/dev/null 2>&1; then
            echo "HOOKS_INSTALLED:OK"
        else
            echo "HOOKS_INSTALLED:FAIL"
            ((errors++))
        fi
    fi

    # Run hooks to validate
    run_hooks "$project_dir" || ((errors++))

    if [[ $errors -eq 0 ]]; then
        echo "FIX_RESULT:OK"
    else
        echo "FIX_RESULT:PARTIAL:$errors"
        return 1
    fi
}

# =============================================================================
# MULTI-PROJECT FUNCTIONS
# =============================================================================

get_all_project_dirs() {
    for project in "${MANAGED_PROJECTS[@]}"; do
        local dir="$HOME/$project"
        if [[ -d "$dir" ]]; then
            echo "$dir"
        fi
    done
}

fix_all() {
    echo "FIX_ALL:start"

    local fixed=0
    for project_dir in $(get_all_project_dirs); do
        full_fix "$project_dir"
        ((fixed++))
    done

    echo "FIX_ALL:$fixed:done"
}

status_dashboard() {
    # TOON format: token-optimized for machine readability
    # Status: OK (healthy), DRIFT (version mismatch), WARN (0 tests), FAIL (missing tools)

    local total=0
    local healthy=0

    echo "DEVSTD[${#MANAGED_PROJECTS[@]}]:canonical:ruff=$CANONICAL_RUFF|mypy=$CANONICAL_MYPY|pytest=$CANONICAL_PYTEST"

    for project_dir in $(get_all_project_dirs); do
        local name=$(basename "$project_dir")
        local venv=$(get_venv_path "$name" "$project_dir")
        local backend=$(get_backend_path "$name" "$project_dir")

        local venv_ok="N"
        local ruff_v="-"
        local mypy_v="-"
        local pytest_v="-"
        local hooks_v="-"
        local test_count="0"
        local status="FAIL"
        local drift=""

        if check_venv "$venv"; then
            venv_ok="Y"
            ruff_v=$(get_installed_version "$venv" ruff)
            mypy_v=$(get_installed_version "$venv" mypy)
            pytest_v=$(get_installed_version "$venv" pytest)
            hooks_v=$(get_installed_version "$venv" pre-commit)
            [[ -z "$ruff_v" ]] && ruff_v="-"
            [[ -z "$mypy_v" ]] && mypy_v="-"
            [[ -z "$pytest_v" ]] && pytest_v="-"
            [[ -z "$hooks_v" ]] && hooks_v="-"

            # Check for version drift (exact match required)
            [[ "$ruff_v" != "-" && "$ruff_v" != "$CANONICAL_RUFF" ]] && drift="ruff"
            [[ "$mypy_v" != "-" && "$mypy_v" != "$CANONICAL_MYPY" ]] && drift="${drift:+$drift,}mypy"
            [[ "$pytest_v" != "-" && "$pytest_v" != "$CANONICAL_PYTEST" ]] && drift="${drift:+$drift,}pytest"
            [[ "$hooks_v" != "-" && "$hooks_v" != "$CANONICAL_PRECOMMIT" ]] && drift="${drift:+$drift,}hooks"
        fi

        if [[ -d "$backend/tests" ]]; then
            test_count=$(find "$backend/tests" -name "test_*.py" 2>/dev/null | wc -l)
        fi

        # Determine health status
        if [[ "$venv_ok" == "N" || "$ruff_v" == "-" || "$mypy_v" == "-" || "$pytest_v" == "-" || "$hooks_v" == "-" ]]; then
            status="FAIL"
        elif [[ -n "$drift" ]]; then
            status="DRIFT"
        elif [[ "$test_count" -eq 0 ]]; then
            status="WARN"
            ((healthy++))  # WARN still counts as healthy (0 tests is warning, not failure)
        else
            status="OK"
            ((healthy++))
        fi
        ((total++))

        # Output line with drift info if present
        local line="$status $name|venv=$venv_ok|ruff=$ruff_v|mypy=$mypy_v|pytest=$pytest_v|hooks=$hooks_v|tests=$test_count"
        [[ -n "$drift" ]] && line="$line|drift=$drift"
        echo "$line"
    done

    echo "SUMMARY:$healthy/$total:healthy"
}

show_help() {
    echo "Dev Standards - Cross-project tooling management"
    echo ""
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "  (no args)        Dashboard of all projects (default)"
    echo "  --check, -c      Quality gate: lint, types, tests (current project)"
    echo "  --fix, -f        Auto-fix + install deps + pre-commit install (current project)"
    echo "  --fix-all        Fix all managed projects"
    echo "  --rebuild-venv   Delete and recreate venv (fixes corrupt venv)"
    echo "  --help, -h       Show this help"
    echo ""
    echo "Managed: ${MANAGED_PROJECTS[*]}"
}

# =============================================================================
# MAIN
# =============================================================================

case "$ACTION" in
    help)
        show_help
        ;;
    status)
        status_dashboard
        ;;
    check)
        full_check "$PROJECT_DIR"
        ;;
    fix)
        if [[ "$TARGET" == "all" ]]; then
            fix_all
        else
            full_fix "$PROJECT_DIR"
        fi
        ;;
    rebuild)
        rebuild_venv "$PROJECT_DIR"
        ;;
esac
