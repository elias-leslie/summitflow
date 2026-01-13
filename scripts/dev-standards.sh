#!/bin/bash
#
# Universal Dev Standards Script
# Enforces consistent dev tooling, testing, and quality gates across all projects
# Works for any project - auto-detects project from PWD/git root
#
# Usage:
#   ./scripts/dev-standards.sh              # Show status for current project
#   ./scripts/dev-standards.sh --check      # Full quality gate (lint, types, tests)
#   ./scripts/dev-standards.sh --fix        # Auto-fix all issues
#   ./scripts/dev-standards.sh --verify     # Verify setup is correct
#   ./scripts/dev-standards.sh --install    # Install missing dev deps
#   ./scripts/dev-standards.sh --audit-all  # Audit all managed projects
#   ./scripts/dev-standards.sh --fix-all    # Fix all managed projects
#   ./scripts/dev-standards.sh --status     # Dashboard of all projects
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
TARGET="current"
VERBOSE=false

for arg in "$@"; do
    case $arg in
        --check|-c) ACTION="check" ;;
        --fix|-f) ACTION="fix" ;;
        --verify|-v) ACTION="verify" ;;
        --install|-i) ACTION="install" ;;
        --test|-t) ACTION="test" ;;
        --lint|-l) ACTION="lint" ;;
        --types) ACTION="types" ;;
        --hooks) ACTION="hooks" ;;
        --audit-all) ACTION="audit"; TARGET="all" ;;
        --fix-all) ACTION="fix"; TARGET="all" ;;
        --status|-s) ACTION="status"; TARGET="all" ;;
        --verbose) VERBOSE=true ;;
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

# =============================================================================
# SINGLE PROJECT FUNCTIONS
# =============================================================================

verify_project() {
    local project_dir="$1"
    local project_name=$(basename "$project_dir")
    local venv=$(get_venv_path "$project_name" "$project_dir")
    local backend=$(get_backend_path "$project_name" "$project_dir")
    local issues=0

    # TOON format output
    echo "VERIFY:$project_name"

    # Check venv
    if check_venv "$venv"; then
        echo "  venv:OK"
    else
        echo "  venv:MISSING"
        ((issues++))
    fi

    # Check dev dependencies
    for pkg_spec in "ruff:$CANONICAL_RUFF" "mypy:$CANONICAL_MYPY" "pytest:$CANONICAL_PYTEST" "pre-commit:$CANONICAL_PRECOMMIT"; do
        local pkg="${pkg_spec%%:*}"
        local required="${pkg_spec#*:}"
        local installed=$(get_installed_version "$venv" "$pkg")

        if [[ -z "$installed" ]]; then
            echo "  $pkg:MISSING(need:$required)"
            ((issues++))
        elif [[ "$installed" == "$required" ]]; then
            echo "  $pkg:$installed"
        else
            echo "  $pkg:$installed(drift:$required)"
        fi
    done

    # Check pre-commit config
    if [[ -f "$project_dir/.pre-commit-config.yaml" ]]; then
        echo "  precommit-config:OK"
    else
        echo "  precommit-config:MISSING"
        ((issues++))
    fi

    # Check for tests
    local test_count=0
    if [[ -d "$backend/tests" ]]; then
        test_count=$(find "$backend/tests" -name "test_*.py" 2>/dev/null | wc -l)
    fi
    echo "  tests:$test_count"

    if [[ $issues -eq 0 ]]; then
        echo "RESULT:OK"
    else
        echo "RESULT:ISSUES:$issues"
    fi

    return $issues
}

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
        local violations=$("$ruff_bin" check "$app_dir" 2>&1 | grep -c "^" || echo "0")
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
    local errors=$("$mypy_bin" "$app_dir" --ignore-missing-imports 2>&1 | grep -c "error:" || echo "0")
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
    local output=$("$pytest_bin" --tb=no -q 2>&1)
    local summary=$(echo "$output" | tail -1)

    if echo "$output" | grep -q "passed"; then
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

    echo "FIX:$project_name"
    install_deps "$project_dir"
    run_lint "$project_dir" "fix"
    run_hooks "$project_dir" || true
    echo "FIX_RESULT:DONE"
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

audit_all() {
    echo "AUDIT_ALL:start"

    local total=0
    local healthy=0

    for project_dir in $(get_all_project_dirs); do
        if verify_project "$project_dir"; then
            ((healthy++))
        fi
        ((total++))
    done

    echo "AUDIT_ALL:$healthy/$total:healthy"
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
    # Format: PROJECT|venv|ruff|mypy|pytest|hooks|tests
    # Values: Y=installed, N=missing, version numbers where relevant

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
        fi

        if [[ -d "$backend/tests" ]]; then
            test_count=$(find "$backend/tests" -name "test_*.py" 2>/dev/null | wc -l)
        fi

        # Determine health
        if [[ "$venv_ok" == "Y" && "$ruff_v" != "-" && "$mypy_v" != "-" && "$pytest_v" != "-" && "$hooks_v" != "-" ]]; then
            status="OK"
            ((healthy++))
        fi
        ((total++))

        echo "$status $name|venv=$venv_ok|ruff=$ruff_v|mypy=$mypy_v|pytest=$pytest_v|hooks=$hooks_v|tests=$test_count"
    done

    echo "SUMMARY:$healthy/$total:healthy"
}

show_help() {
    echo "Dev Standards - Universal development tooling management"
    echo ""
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Single Project (auto-detects from git root):"
    echo "  --check, -c      Full quality gate (lint, types, tests)"
    echo "  --fix, -f        Auto-fix all issues + install deps"
    echo "  --verify, -v     Verify setup is correct"
    echo "  --install, -i    Install missing dev dependencies"
    echo "  --test, -t       Run tests only"
    echo "  --lint, -l       Run linting only"
    echo "  --types          Run type checking only"
    echo "  --hooks          Run pre-commit hooks"
    echo ""
    echo "Multi-Project:"
    echo "  --audit-all      Audit all managed projects"
    echo "  --fix-all        Fix all managed projects"
    echo "  --status, -s     Dashboard of all projects"
    echo ""
    echo "Other:"
    echo "  --verbose        Show detailed output"
    echo "  --help, -h       Show this help"
    echo ""
    echo "Managed projects: ${MANAGED_PROJECTS[*]}"
}

# =============================================================================
# MAIN
# =============================================================================

case "$ACTION" in
    help)
        show_help
        ;;
    status)
        if [[ "$TARGET" == "all" ]]; then
            status_dashboard
        else
            verify_project "$PROJECT_DIR"
        fi
        ;;
    verify)
        verify_project "$PROJECT_DIR"
        ;;
    install)
        install_deps "$PROJECT_DIR"
        ;;
    lint)
        run_lint "$PROJECT_DIR"
        ;;
    types)
        run_types "$PROJECT_DIR"
        ;;
    test)
        run_tests "$PROJECT_DIR"
        ;;
    hooks)
        run_hooks "$PROJECT_DIR"
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
    audit)
        audit_all
        ;;
esac
