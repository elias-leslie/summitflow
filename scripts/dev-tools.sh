#!/bin/bash
#
# Universal Dev Standards Script
# Enforces consistent dev tooling, testing, and quality gates across all projects
# Works for any project - auto-detects project from PWD/git root
#
# Usage (via ~/bin/dt symlink):
#   dt                    # Dashboard of all projects (default)
#   dt --check            # Full quality gate (lint, types, tests)
#   dt --fix              # Auto-fix + install deps + pre-commit install
#   dt --fix-all          # Fix all managed projects
#   dt --rebuild-venv     # Nuclear option: delete and recreate venv
#   dt cleanroom -- ...   # Run a command in a clean snapshot of the working tree
#   dt pytest             # Run pytest with TOON output
#   dt ruff               # Run ruff with TOON output
#   dt types              # Run ty with TOON output
#

set -o pipefail

# =============================================================================
# SETUP
# =============================================================================

# Resolve symlinks to find the real script location (enables ~/bin/dt symlink)
SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"
source "$SCRIPT_DIR/lib/dev-standards-config.sh"
SUMMITFLOW_ROOT_OVERRIDE="$(dirname "$SCRIPT_DIR")"
source "$SCRIPT_DIR/lib/project-roots.sh"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

read_project_id_from_index() {
    local root="$1"
    local index_path="$root/.index.yaml"

    if [[ ! -f "$index_path" ]]; then
        return 1
    fi

    awk '
        /^project:[[:space:]]*/ {
            sub(/^project:[[:space:]]*/, "", $0)
            gsub(/["'"'"']/, "", $0)
            if ($0 != "") {
                print $0
                exit
            }
        }
    ' "$index_path"
}

detect_local_project_context() {
    local candidate="${1:-$PWD}"

    while [[ -n "$candidate" ]]; do
        if [[ -f "$candidate/.index.yaml" ]]; then
            local project_id
            project_id="$(read_project_id_from_index "$candidate")"
            if [[ -n "$project_id" ]]; then
                DT_CONTEXT_ROOT="$candidate"
                DT_CONTEXT_PROJECT="$project_id"
                return 0
            fi
        fi

        if [[ "$candidate" == "/" ]]; then
            break
        fi
        candidate="$(dirname "$candidate")"
    done

    return 1
}

# Project detection - handles both main repos and worktrees
PROJECT_DIR=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
PROJECT_NAME=$(basename "$PROJECT_DIR")
MAIN_REPO_DIR="$PROJECT_DIR"
DT_CONTEXT_ROOT=""
DT_CONTEXT_PROJECT=""
detect_local_project_context "$PWD" || detect_local_project_context "$PROJECT_DIR" || true
if [[ -n "$DT_CONTEXT_PROJECT" ]]; then
    PROJECT_NAME="$DT_CONTEXT_PROJECT"
fi

# Detect ANY git worktree (Claude Code .claude/worktrees, SummitFlow st worktrees, etc.)
# Use `git worktree list` to find the primary checkout — it's always listed first.
# If we're in a linked worktree, use the primary checkout for venv (worktrees share it).
_primary_worktree=$(git worktree list 2>/dev/null | head -1 | awk '{print $1}')
if [[ -n "$_primary_worktree" && "$_primary_worktree" != "$PROJECT_DIR" ]]; then
    if [[ -x "$PROJECT_DIR/backend/.venv/bin/python" || -x "$PROJECT_DIR/.venv/bin/python" ]]; then
        MAIN_REPO_DIR="$PROJECT_DIR"
    else
        MAIN_REPO_DIR="$_primary_worktree"
    fi
fi

# Claimed lanes/worktrees often omit a local .index.yaml even though the primary
# checkout has the canonical project identity. Re-resolve from the primary
# checkout before computing backend and venv paths so worktree wrappers remain
# project-aware without lane-local symlink fixes.
if [[ -z "$DT_CONTEXT_PROJECT" && -n "$_primary_worktree" && "$_primary_worktree" != "$PROJECT_DIR" ]]; then
    detect_local_project_context "$_primary_worktree" || true
    if [[ -n "$DT_CONTEXT_PROJECT" ]]; then
        PROJECT_NAME="$DT_CONTEXT_PROJECT"
    fi
fi

# Use main repo for venv (tools), but PROJECT_DIR for backend (code to lint)
VENV_PATH=$(get_venv_path "$PROJECT_NAME" "$MAIN_REPO_DIR")
# Backend path should be in the WORKTREE (or current dir) for linting
BACKEND_PATH=$(get_backend_path "$PROJECT_NAME" "$PROJECT_DIR")

# Output directory for TOON details
OUTPUT_DIR="$PROJECT_DIR/.dev-tools"

# Parse arguments - subcommands first, then flags
ACTION="status"
TARGET="all"

# Tool registry — single source of truth for tool definitions
TOOL_REGISTRY="$SCRIPT_DIR/lib/tool-registry.json"

# Check for subcommands (first positional argument)
# Tool names are read dynamically from the registry
if [[ "${1:-}" == "cleanroom" ]]; then
    ACTION="cleanroom"; shift
elif [ -n "${1:-}" ] && [ -f "$TOOL_REGISTRY" ]; then
    REGISTRY_TOOL_NAMES=$(jq -r '.tools[] | select(.dt) | .name' "$TOOL_REGISTRY" 2>/dev/null | tr '\n' '|')
    REGISTRY_TOOL_NAMES="${REGISTRY_TOOL_NAMES%|}"  # strip trailing pipe
    if [ -n "$REGISTRY_TOOL_NAMES" ] && echo "$1" | grep -qE "^(${REGISTRY_TOOL_NAMES})$"; then
        ACTION="tool_toon"; TOOL_NAME="$1"; shift
    fi
fi

# Parse remaining flags — unknown args are passed through to tool subcommands
# When a tool subcommand was detected, ALL remaining args are pass-through to that tool
# A leading `--` separator is stripped so it doesn't leak into the underlying tool
# (e.g., `dt pytest -- -k "persona"` → pytest receives `-k persona`, not `-- -k persona`)
CHANGED_ONLY=0
EXTRA_ARGS=()
CLEANROOM_ENV_VARS=()
CLEANROOM_UNSET_KEYS=()
CLEANROOM_KEEP_DIR=0
if [[ "$ACTION" == "tool_toon" ]]; then
    _passthrough=0
    for arg in "$@"; do
        if [[ $_passthrough -eq 0 ]]; then
            case $arg in
                --changed-only|-d) CHANGED_ONLY=1; continue ;;
                --) _passthrough=1; continue ;;  # strip separator, start passthrough
            esac
        fi
        EXTRA_ARGS+=("$arg")
    done
elif [[ "$ACTION" == "cleanroom" ]]; then
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --env)
                CLEANROOM_ENV_VARS+=("$2")
                shift 2
                ;;
            --unset)
                CLEANROOM_UNSET_KEYS+=("$2")
                shift 2
                ;;
            --keep-dir)
                CLEANROOM_KEEP_DIR=1
                shift
                ;;
            --)
                shift
                EXTRA_ARGS=("$@")
                break
                ;;
            *)
                EXTRA_ARGS=("$@")
                break
                ;;
        esac
    done
else
    for arg in "$@"; do
        case $arg in
            --check|-c) ACTION="check"; TARGET="current" ;;
            --quick|-q) ACTION="quick_check"; TARGET="current" ;;
            --changed-only|-d) CHANGED_ONLY=1 ;;
            --frontend-only|--fe) ACTION="frontend_only_check"; TARGET="current" ;;
            --fix|-f) ACTION="fix"; TARGET="current" ;;
            --fix-all) ACTION="fix"; TARGET="all" ;;
            --rebuild-venv) ACTION="rebuild"; TARGET="current" ;;
            --help|-h) ACTION="help" ;;
            *) EXTRA_ARGS+=("$arg") ;;
        esac
    done
fi

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_header() { echo -e "\n${BOLD}${CYAN}=== $1 ===${NC}"; }

run_cleanroom_command() {
    local summitflow_python="$SUMMITFLOW_ROOT_OVERRIDE/backend/.venv/bin/python"
    local cmd=()

    if [[ ! -x "$summitflow_python" ]]; then
        log_error "SummitFlow backend venv is missing: $summitflow_python"
        return 1
    fi
    if [[ ${#EXTRA_ARGS[@]} -eq 0 ]]; then
        log_error "dt cleanroom requires a command after '--'"
        return 1
    fi

    cmd=(
        "$summitflow_python"
        -m cli.lib.cleanroom
        --project-root "$PROJECT_DIR"
    )

    if [[ "$CLEANROOM_KEEP_DIR" -eq 1 ]]; then
        cmd+=(--keep-dir)
    fi
    for assignment in "${CLEANROOM_ENV_VARS[@]}"; do
        cmd+=(--env "$assignment")
    done
    for key in "${CLEANROOM_UNSET_KEYS[@]}"; do
        cmd+=(--unset "$key")
    done
    cmd+=(-- "${EXTRA_ARGS[@]}")

    (
        cd "$SUMMITFLOW_ROOT_OVERRIDE/backend"
        "${cmd[@]}"
    )
}

# Get changed files (staged + unstaged) for a given extension pattern
# Usage: get_changed_files "py" or get_changed_files "ts|tsx"
get_changed_files() {
    local ext_pattern="$1"
    local base_dir="${2:-$PROJECT_DIR}"
    local changed_scope="${DT_CHANGED_ONLY_SCOPE:-all}"

    # Changed-only checks normally include staged, unstaged, and untracked files.
    # commit.sh can narrow this to the staged subset to protect scoped commits.
    (
        if [[ "$changed_scope" == "staged" ]]; then
            git -C "$base_dir" diff --name-only --cached 2>/dev/null
        else
            git -C "$base_dir" diff --name-only HEAD 2>/dev/null
            git -C "$base_dir" diff --name-only --cached 2>/dev/null
            git -C "$base_dir" ls-files --others --exclude-standard 2>/dev/null
        fi
    ) | grep -E "\.($ext_pattern)$" | sort -u | while read -r file; do
        # Return full path if file exists
        local full_path="$base_dir/$file"
        [[ -f "$full_path" ]] && echo "$full_path"
    done
}

# Get changed Python files in backend
get_changed_python_files() {
    get_changed_files "py" "$PROJECT_DIR" | grep -E "^$BACKEND_PATH" | grep -v "alembic/versions/" || true
}

# Get frontend root directory for current project
get_frontend_root() {
    local project_dir="${1:-$PROJECT_DIR}"
    local frontend_dir="$project_dir/frontend"
    [[ -d "$frontend_dir" ]] && echo "$frontend_dir" || echo "$project_dir"
}

# Get changed TypeScript files in frontend
get_changed_ts_files() {
    local frontend_dir
    frontend_dir="$(get_frontend_root "$PROJECT_DIR")"
    get_changed_files "ts|tsx|js|jsx" "$PROJECT_DIR" | grep -E "^$frontend_dir" || true
}

resolve_tool_binary() {
    local binary="$1"
    local dir_type="$2"
    local work_dir="$3"
    local fallback_global="$4"
    local candidate=""

    if [[ "$dir_type" == "frontend" ]]; then
        candidate="$work_dir/node_modules/.bin/$binary"
        [[ -x "$candidate" ]] && echo "$candidate" && return 0
    fi

    candidate="${VENV_PATH}/bin/$binary"
    [[ -x "$candidate" ]] && echo "$candidate" && return 0

    if [[ "$fallback_global" == "1" ]]; then
        candidate=$(which "$binary" 2>/dev/null || echo "")
        [[ -n "$candidate" ]] && echo "$candidate" && return 0
    fi

    return 1
}

# Max detail files to keep for rotation (last N runs)
MAX_DETAIL_FILES=5

# Ensure .dev-tools output directory exists
ensure_output_dir() {
    mkdir -p "$OUTPUT_DIR"
}

# Rotate detail files: tool-details.txt -> tool-details.1.txt -> ... -> tool-details.N.txt
# Keeps last MAX_DETAIL_FILES runs for comparison
rotate_details() {
    local base_file="$1"
    local dir=$(dirname "$base_file")
    local name=$(basename "$base_file" .txt)

    # Delete oldest if at max
    local oldest="$dir/${name}.${MAX_DETAIL_FILES}.txt"
    [[ -f "$oldest" ]] && rm -f "$oldest"

    # Rotate existing numbered files (N-1 -> N, N-2 -> N-1, etc.)
    for ((i=MAX_DETAIL_FILES-1; i>=1; i--)); do
        local src="$dir/${name}.${i}.txt"
        local dst="$dir/${name}.$((i+1)).txt"
        [[ -f "$src" ]] && mv "$src" "$dst"
    done

    # Move current to .1 if exists
    [[ -f "$base_file" ]] && mv "$base_file" "$dir/${name}.1.txt"
}

# Strip ANSI codes from text
strip_ansi() {
    sed 's/\x1b\[[0-9;]*m//g' | sed 's/\x1b\[K//g'
}

# Sync quality check result to SummitFlow (non-blocking, silent on failure)
# Args: check_type status error_count [triggered_by]
sync_quality_result() {
    local check_type="$1"
    local status="$2"
    local error_count="${3:-0}"
    local triggered_by="${4:-commit}"

    # Only sync if st CLI is available and we're in a SummitFlow-managed project
    if ! command -v st &>/dev/null; then
        return 0
    fi

    # Silently sync - don't let failures affect the main command
    st health sync "$check_type" "$status" --errors "$error_count" --triggered-by "$triggered_by" >/dev/null 2>&1 || true
}

# Get installed version of a package
get_installed_version() {
    local venv="$1"
    local package="$2"
    local python_bin="${venv}/bin/python"

    if [[ -x "$python_bin" ]]; then
        "$python_bin" - "$package" <<'PY' 2>/dev/null || true
from importlib import metadata
import sys

package = sys.argv[1]
try:
    print(metadata.version(package))
except metadata.PackageNotFoundError:
    pass
PY
    else
        echo ""
    fi
}

# Check if venv exists and is valid
check_venv() {
    local venv="$1"
    [[ -x "${venv}/bin/python" ]]
}

# Rebuild venv from scratch
rebuild_venv() {
    local project_dir="$1"
    local project_name="$PROJECT_NAME"
    local venv=$(get_venv_path "$project_name" "$MAIN_REPO_DIR")

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
    local project_name="$PROJECT_NAME"
    local venv=$(get_venv_path "$project_name" "$MAIN_REPO_DIR")

    echo "INSTALL:$project_name"

    if ! check_venv "$venv"; then
        echo "ERROR:venv_missing:$venv"
        return 1
    fi

    local installed=0
    local failed=0

    for pkg_spec in "ruff==$CANONICAL_RUFF" "ty==$CANONICAL_TY" "pytest==$CANONICAL_PYTEST" \
                    "pytest-asyncio==$CANONICAL_PYTEST_ASYNCIO" "pytest-cov==$CANONICAL_PYTEST_COV" \
                    "pytest-xdist==$CANONICAL_PYTEST_XDIST" "pytest-mock==$CANONICAL_PYTEST_MOCK" \
                    "pytest-timeout==$CANONICAL_PYTEST_TIMEOUT" "pytest-randomly==$CANONICAL_PYTEST_RANDOMLY" \
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
    local project_name="$PROJECT_NAME"
    local venv=$(get_venv_path "$project_name" "$MAIN_REPO_DIR")
    local backend=$(get_backend_path "$project_name" "$project_dir")
    local fix_mode="$2"

    local mode_suffix=""
    [[ "$CHANGED_ONLY" == "1" ]] && mode_suffix=":changed"
    echo "LINT:$project_name$mode_suffix"

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

    # Determine what to lint
    local lint_targets="$backend"
    if [[ "$CHANGED_ONLY" == "1" ]]; then
        local changed_files
        changed_files=$(get_changed_python_files)
        if [[ -z "$changed_files" ]]; then
            echo "OK:no_py_changes"
            return 0
        fi
        local file_count
        file_count=$(echo "$changed_files" | wc -l)
        local file_names
        file_names=$(echo "$changed_files" | xargs -I{} basename {} | tr '\n' ' ')
        echo "SCOPE:${file_count} files:${file_names% }"
        lint_targets="$changed_files"
    fi

    # Build --extend-exclude flags from centralized config
    local exclude_args=()
    for pattern in "${LINT_EXCLUDE_DIRS[@]}"; do
        exclude_args+=(--extend-exclude "$pattern")
    done

    # ALWAYS auto-fix safe issues first (import sorting, formatting)
    # This eliminates the fix vs check distinction for safe fixes
    echo "$lint_targets" | xargs "$ruff_bin" check --fix --quiet "${exclude_args[@]}" 2>/dev/null || true
    echo "$lint_targets" | xargs "$ruff_bin" format --quiet "${exclude_args[@]}" 2>/dev/null || true

    ensure_output_dir
    local details_file="$OUTPUT_DIR/ruff-details.1.txt"

    if [[ "$fix_mode" == "fix" ]]; then
        rm -f "$details_file"
        echo "FIXED:ruff=$ruff_src"
    else
        # Check for remaining unfixable violations
        local output retval=0
        output=$(echo "$lint_targets" | xargs "$ruff_bin" check --output-format=concise "${exclude_args[@]}" 2>&1) || retval=$?
        if [[ $retval -eq 0 ]]; then
            rm -f "$details_file"
            echo "OK:violations=0"
        elif [[ $retval -eq 2 ]]; then
            # Exit 2 = usage/configuration error (bad flag, invalid config)
            echo "$output" > "$details_file"
            echo "ERROR:ruff_usage_error|details:$details_file"
            echo "  Hint: check ruff flags and config. Run 'ruff check --help' for valid options." >&2
            return 1
        else
            local violations
            violations=$(echo "$output" | wc -l) || violations=0
            echo "$output" > "$details_file"
            echo "FAIL:violations=$violations|details:$details_file"
            return 1
        fi
    fi
}

run_types() {
    local project_dir="$1"
    local project_name="$PROJECT_NAME"
    local venv=$(get_venv_path "$project_name" "$MAIN_REPO_DIR")
    local backend=$(get_backend_path "$project_name" "$project_dir")

    local mode_suffix=""
    [[ "$CHANGED_ONLY" == "1" ]] && mode_suffix=":changed"
    echo "TYPES:$project_name$mode_suffix"

    local ty_bin
    ty_bin=$(which ty 2>/dev/null || echo "")
    if [[ -z "$ty_bin" ]]; then
        echo "ERROR:ty_not_found"
        return 1
    fi

    ensure_output_dir
    local details_file="$OUTPUT_DIR/ty-details.1.txt"

    local app_dir="$backend/app"
    [[ ! -d "$app_dir" ]] && app_dir="$backend"

    local python_bin="${venv}/bin/python"

    cd "$backend"
    local output errors retval=0
    if [[ "$CHANGED_ONLY" == "1" ]]; then
        local changed_files
        changed_files=$(get_changed_python_files)
        if [[ -z "$changed_files" ]]; then
            echo "OK:no_py_changes"
            return 0
        fi
        local file_count
        file_count=$(echo "$changed_files" | wc -l)
        local file_names
        file_names=$(echo "$changed_files" | xargs -I{} basename {} | tr '\n' ' ')
        echo "SCOPE:${file_count} files:${file_names% }"
        # ty doesn't support file list directly — check only app/ but it's fast enough
        output=$("$ty_bin" check --python "$python_bin" "$app_dir" 2>&1) || retval=$?
    else
        output=$("$ty_bin" check --python "$python_bin" "$app_dir" 2>&1) || retval=$?
    fi

    errors=$(echo "$output" | grep -c "^error\[") || errors=0
    if [[ "$errors" -eq 0 ]]; then
        rm -f "$details_file"
        echo "OK:errors=0"
    else
        echo "$output" > "$details_file"
        echo "FAIL:errors=$errors|details:$details_file"
        return 1
    fi
}

run_tests() {
    local project_dir="$1"
    local project_name="$PROJECT_NAME"
    local venv=$(get_venv_path "$project_name" "$MAIN_REPO_DIR")
    local backend=$(get_backend_path "$project_name" "$project_dir")

    echo "TEST:$project_name"

    local pytest_bin="${venv}/bin/pytest"
    if [[ ! -x "$pytest_bin" ]]; then
        echo "ERROR:pytest_not_found"
        return 1
    fi

    ensure_output_dir
    local details_file="$OUTPUT_DIR/pytest-details.1.txt"

    # Prefer backend/ when it has tests/, otherwise run from project root.
    # This keeps projects like A-Term (tests/ at repo root) discoverable.
    local test_dir="$backend"
    if [[ ! -d "$backend/tests" && -d "$project_dir/tests" ]]; then
        test_dir="$project_dir"
    fi
    cd "$test_dir"
    # Use pytest exit code, not text matching (avoids "6 failed, 677 passed" false positive)
    local output retval=0
    output=$("$pytest_bin" --tb=short -q 2>&1) || retval=$?
    local summary=$(echo "$output" | tail -1)

    # Trust summary over exit code: non-zero exit with all tests passing = coverage/warnings, not test failure
    local tests_passed=0
    if [[ $retval -eq 0 ]]; then
        tests_passed=1
    elif echo "$summary" | grep -qE '\bpassed\b' && ! echo "$summary" | grep -qiE '\b(failed|error)\b'; then
        tests_passed=1
    fi

    if [[ $tests_passed -eq 1 ]]; then
        rm -f "$details_file"
        echo "OK:$summary"
    else
        echo "$output" > "$details_file"
        # Extract failing test names for inline display
        local failed_tests
        failed_tests=$(echo "$output" | grep -E '^FAILED ' | sed 's/^FAILED //' | sed 's/ -.*$//' | head -5) || true
        if [[ -n "$failed_tests" ]]; then
            local failed_inline
            failed_inline=$(echo "$failed_tests" | tr '\n' ',' | sed 's/,$//')
            echo "FAIL:$summary|failed:$failed_inline|details:$details_file"
        else
            echo "FAIL:$summary|details:$details_file"
        fi
        return 1
    fi
}


# Check if project has python backend
has_python_backend() {
    local project_dir="${1:-$PROJECT_DIR}"
    local backend_dir=$(get_backend_path "$PROJECT_NAME" "$project_dir")

    # Check for pyproject.toml or requirements.txt in the backend dir
    if [[ -f "$backend_dir/pyproject.toml" ]] || [[ -f "$backend_dir/requirements.txt" ]]; then
        return 0
    fi
    # Only scan for .py files if backend_dir is a DEDICATED subdirectory,
    # not the project root fallback (which catches stray utility scripts)
    if [[ "$backend_dir" != "$project_dir" && -d "$backend_dir" ]]; then
        if find "$backend_dir" -maxdepth 2 -name "*.py" -print -quit | grep -q .; then
            return 0
        fi
    fi
    return 1
}

quick_check() {
    local project_dir="$1"
    local project_name="$PROJECT_NAME"
    local errors=0

    local mode_suffix=""
    [[ "$CHANGED_ONLY" == "1" ]] && mode_suffix=":changed"
    echo "QUICK_CHECK:$project_name$mode_suffix"

    # Python tools only if backend exists
    if has_python_backend "$project_dir"; then
        run_lint "$project_dir" || { ((errors++)) || true; }
        run_types "$project_dir" || { ((errors++)) || true; }
    else
        echo "LINT:OK:skipped_no_python"
        echo "TYPES:OK:skipped_no_python"
    fi

    # Frontend tools if project has frontend (skip if --changed-only and no frontend files changed)
    if has_frontend "$project_dir"; then
        if [[ "$CHANGED_ONLY" == "1" ]] && [[ -z "$(get_changed_ts_files)" ]]; then
            echo "BIOME:OK:no_frontend_changes"
            echo "TSC:OK:no_frontend_changes"
        else
            run_tool_toon biome || { ((errors++)) || true; }
            run_tool_toon tsc || { ((errors++)) || true; }
        fi
    else
        echo "BIOME:OK:skipped_no_frontend"
        echo "TSC:OK:skipped_no_frontend"
    fi

    if [[ $errors -eq 0 ]]; then
        echo "CHECK_RESULT:OK"
    else
        echo "CHECK_RESULT:FAIL:$errors"
    fi

    return $errors
}

# Frontend-only check: skip Python tools, run biome + tsc and vitest when configured
# Useful for pure frontend projects (e.g., monkey-fight)
frontend_only_check() {
    local project_dir="$1"
    local project_name="$PROJECT_NAME"
    local errors=0

    echo "FRONTEND_CHECK:$project_name"

    if ! has_frontend "$project_dir"; then
        echo "ERROR:no_frontend_detected"
        echo "CHECK_RESULT:FAIL:1"
        return 1
    fi

    run_tool_toon biome || { ((errors++)) || true; }
    run_tool_toon tsc || { ((errors++)) || true; }
    if has_frontend_vitest "$project_dir"; then
        run_tool_toon vitest || { ((errors++)) || true; }
    else
        echo "VITEST:OK:skipped_no_vitest"
    fi

    if [[ $errors -eq 0 ]]; then
        echo "CHECK_RESULT:OK"
    else
        echo "CHECK_RESULT:FAIL:$errors"
    fi

    return $errors
}

full_check() {
    local project_dir="$1"
    local project_name="$PROJECT_NAME"
    local errors=0

    echo "CHECK:$project_name"
    
    if has_python_backend "$project_dir"; then
        run_lint "$project_dir" || { ((errors++)) || true; }
        run_types "$project_dir" || { ((errors++)) || true; }
        run_tests "$project_dir" || { ((errors++)) || true; }
    else
        echo "LINT:OK:skipped_no_python"
        echo "TYPES:OK:skipped_no_python"
        echo "TEST:OK:skipped_no_python"
    fi

    # Frontend tools if project has frontend
    if has_frontend "$project_dir"; then
        run_tool_toon biome || { ((errors++)) || true; }
        run_tool_toon tsc || { ((errors++)) || true; }
        if has_frontend_vitest "$project_dir"; then
            run_tool_toon vitest || { ((errors++)) || true; }
        else
            echo "VITEST:OK:skipped_no_vitest"
        fi
    else
        echo "BIOME:OK:skipped_no_frontend"
        echo "TSC:OK:skipped_no_frontend"
        echo "VITEST:OK:skipped_no_frontend"
    fi

    if [[ $errors -eq 0 ]]; then
        echo "CHECK_RESULT:OK"
    else
        echo "CHECK_RESULT:FAIL:$errors"
    fi

    return $errors
}

full_fix() {
    local project_dir="$1"
    local project_name="$PROJECT_NAME"
    local venv=$(get_venv_path "$project_name" "$MAIN_REPO_DIR")
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
        local dir
        dir="$(resolve_project_root "$project" 2>/dev/null || true)"
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

    echo "DEVSTD[${#MANAGED_PROJECTS[@]}]:canonical:ruff=$CANONICAL_RUFF|ty=$CANONICAL_TY|pytest=$CANONICAL_PYTEST"

    for project_dir in $(get_all_project_dirs); do
        local name=$(basename "$project_dir")
        local venv=$(get_venv_path "$name" "$project_dir")
        local backend=$(get_backend_path "$name" "$project_dir")

        local venv_ok="N"
        local ruff_v="-"
        local ty_v="-"
        local pytest_v="-"
        local hooks_v="-"
        local test_count="0"
        local status="FAIL"
        local drift=""

        if check_venv "$venv"; then
            venv_ok="Y"
            ruff_v=$(get_installed_version "$venv" ruff)
            ty_v=$(ty --version 2>/dev/null | awk '{print $2}' || echo "-")
            pytest_v=$(get_installed_version "$venv" pytest)
            hooks_v=$(get_installed_version "$venv" pre-commit)
            [[ -z "$ruff_v" ]] && ruff_v="-"
            [[ -z "$ty_v" ]] && ty_v="-"
            [[ -z "$pytest_v" ]] && pytest_v="-"
            [[ -z "$hooks_v" ]] && hooks_v="-"

            # Check for version drift (exact match required)
            [[ "$ruff_v" != "-" && "$ruff_v" != "$CANONICAL_RUFF" ]] && drift="ruff"
            [[ "$ty_v" != "-" && "$ty_v" != "$CANONICAL_TY" ]] && drift="${drift:+$drift,}ty"
            [[ "$pytest_v" != "-" && "$pytest_v" != "$CANONICAL_PYTEST" ]] && drift="${drift:+$drift,}pytest"
            [[ "$hooks_v" != "-" && "$hooks_v" != "$CANONICAL_PRECOMMIT" ]] && drift="${drift:+$drift,}hooks"
        fi

        if [[ -d "$backend/tests" ]]; then
            test_count=$(find "$backend/tests" -name "test_*.py" 2>/dev/null | wc -l)
        fi

        # Determine health status
        if [[ "$venv_ok" == "N" || "$ruff_v" == "-" || "$ty_v" == "-" || "$pytest_v" == "-" || "$hooks_v" == "-" ]]; then
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
        local line="$status $name|venv=$venv_ok|ruff=$ruff_v|ty=$ty_v|pytest=$pytest_v|hooks=$hooks_v|tests=$test_count"
        [[ -n "$drift" ]] && line="$line|drift=$drift"
        echo "$line"
    done

    echo "SUMMARY:$healthy/$total:healthy"
}

# =============================================================================
# TOON WRAPPER FUNCTIONS - Token-optimized output for Claude
# =============================================================================

# Tool definitions loaded from centralized registry (tool-registry.json)
# Format: LABEL|binary|args|count_method|working_dir_type|fallback_global|pass_path
declare -A TOOL_DEFS
REGISTRY_DUPLICATES=()
if [ -f "$TOOL_REGISTRY" ]; then
    while IFS='|' read -r name label binary args count_method working_dir fallback_global pass_path; do
        if [[ -n "${TOOL_DEFS[$name]+x}" ]]; then
            REGISTRY_DUPLICATES+=("$name")
            continue
        fi
        TOOL_DEFS[$name]="${label}|${binary}|${args}|${count_method}|${working_dir}|${fallback_global}|${pass_path}"
    done < <(jq -r '.tools[] | select(.dt) | [
        .name,
        .dt.label,
        .dt.binary,
        .dt.args,
        .dt.count_method,
        .dt.working_dir,
        (if .dt.fallback_global then "1" else "0" end),
        (if .dt.pass_path then "1" else "0" end)
    ] | join("|")' "$TOOL_REGISTRY")
    if [[ ${#REGISTRY_DUPLICATES[@]} -gt 0 ]]; then
        mapfile -t _unique_registry_duplicates < <(printf '%s\n' "${REGISTRY_DUPLICATES[@]}" | sort -u)
        echo "ERROR:duplicate_tool_names:${_unique_registry_duplicates[*]// /,}" >&2
        exit 1
    fi
else
    echo "ERROR:registry_not_found:$TOOL_REGISTRY" >&2
fi

# Check if project has frontend (biome.json, eslint.config.*, or package.json in frontend/)
has_frontend() {
    local project_dir="${1:-$PROJECT_DIR}"
    local frontend_dir="$project_dir/frontend"
    # Check for frontend/ with biome, eslint config, or package.json
    if [[ -d "$frontend_dir" ]]; then
        if [[ -f "$frontend_dir/biome.json" ]]; then
            return 0
        fi
        if ls "$frontend_dir"/eslint.config.* 2>/dev/null | head -1 >/dev/null; then
            return 0
        fi
        if [[ -f "$frontend_dir/package.json" ]]; then
            return 0
        fi
    fi
    # Check root for frontend-only projects (biome, eslint config, OR package.json with no backend/)
    if [[ -f "$project_dir/biome.json" ]]; then
        return 0
    fi
    if ls "$project_dir"/eslint.config.* 2>/dev/null | head -1 >/dev/null; then
        return 0
    fi
    # Frontend-only project: has package.json at root but no backend/
    if [[ -f "$project_dir/package.json" && ! -d "$project_dir/backend" ]]; then
        return 0
    fi
    return 1
}

# Check if project has Vitest frontend tests configured
has_frontend_vitest() {
    local project_dir="${1:-$PROJECT_DIR}"
    if ! has_frontend "$project_dir"; then
        return 1
    fi

    local frontend_dir
    frontend_dir="$(get_frontend_root "$project_dir")"

    if ls "$frontend_dir"/vitest.config.* 2>/dev/null | head -1 >/dev/null; then
        return 0
    fi

    if [[ -f "$frontend_dir/package.json" ]] && grep -q '"vitest"' "$frontend_dir/package.json"; then
        return 0
    fi

    return 1
}

# Get working directory for a tool
get_tool_working_dir() {
    local dir_type="$1"
    case "$dir_type" in
        backend)
            local app_dir="$BACKEND_PATH/app"
            [[ ! -d "$app_dir" ]] && app_dir="$BACKEND_PATH"
            echo "$app_dir"
            ;;
        frontend)
            local frontend_dir
            frontend_dir="$(get_frontend_root "$PROJECT_DIR")"
            echo "$frontend_dir"
            ;;
        test)
            # For test runners: prefer backend/tests, fall back to project root
            if [[ -d "$BACKEND_PATH/tests" ]]; then
                echo "$BACKEND_PATH"
            else
                echo "$PROJECT_DIR"
            fi
            ;;
        migrations)
            # For SQL linting: look for migrations/ in backend or root
            local mig_dir="$BACKEND_PATH/migrations"
            [[ ! -d "$mig_dir" ]] && mig_dir="$PROJECT_DIR/migrations"
            echo "$mig_dir"
            ;;
        project_root)
            echo "$PROJECT_DIR"
            ;;
        root)
            echo "$PROJECT_DIR"
            ;;
    esac
}

# Count issues from output based on method
count_issues() {
    local method="$1"
    local output="$2"
    local retval="$3"

    case "$method" in
        wc_l)
            local count
            count=$(echo "$output" | wc -l) || count=0
            [[ -z "$output" ]] && count=0
            echo "$count"
            ;;
        grep_error)
            local count
            count=$(echo "$output" | grep -c "error:") || count=0
            echo "$count"
            ;;
        grep_error_ts)
            # TypeScript errors: "error TS" pattern
            local count
            count=$(echo "$output" | grep -c "error TS") || count=0
            echo "$count"
            ;;
        grep_warn_error)
            # ESLint style: count lines with "warning" or "error"
            local count
            count=$(echo "$output" | grep -cE '\s+(warning|error)\s+' ) || count=0
            echo "$count"
            ;;
        biome_parse)
            # Biome output: count lines with lint/ prefix (rule violations)
            local count
            count=$(echo "$output" | grep -c "lint/") || count=0
            echo "$count"
            ;;
        coderabbit_parse)
            # CodeRabbit: count "Type:" lines (each = one finding)
            local count
            count=$(echo "$output" | grep -c "^Type:") || count=0
            echo "$count"
            ;;
        pytest_parse)
            # For pytest, extract the summary line (e.g. "4 passed in 1.23s")
            # Use a tight pattern to avoid matching coverage file paths like console_errors.py
            # The summary always has "=== ... ===" or a bare "N passed" / "N failed" format
            local summary_line
            summary_line=$(echo "$output" | strip_ansi | grep -E '^\s*=*\s*[0-9]+ (passed|failed|errors?|skipped|deselected|warnings?)' | tail -1) || true
            if [[ -z "$summary_line" ]]; then
                # Fallback: grab the very last non-empty line (works for all pytest formats)
                summary_line=$(echo "$output" | strip_ansi | grep -v '^\s*$' | tail -1) || true
            fi
            echo "$summary_line"
            ;;
        vitest_parse)
            local failed_count summary_line
            summary_line=$(echo "$output" | strip_ansi | grep -E '^\s*(Tests|Test Files)\s+' | tail -1) || true
            failed_count=""
            if [[ -n "$summary_line" ]]; then
                failed_count=$(echo "$summary_line" | sed -nE 's/.*[^0-9]([0-9]+) failed.*/\1/p' | head -1) || true
            fi
            if [[ -n "$failed_count" ]]; then
                echo "$failed_count"
            elif [[ $retval -eq 0 ]]; then
                echo "0"
            else
                echo "1"
            fi
            ;;
    esac
}

run_coderabbit_with_progress() {
    local tool_bin="$1"
    shift

    local output_file
    output_file=$(mktemp)
    local progress_interval=10
    local start_ts
    start_ts=$(date +%s)
    local last_stage="starting"

    "$tool_bin" "$@" >"$output_file" 2>&1 &
    local cmd_pid=$!

    echo "CODERABBIT:RUNNING:0s|stage:${last_stage}" >&2

    while kill -0 "$cmd_pid" 2>/dev/null; do
        sleep "$progress_interval"
        if ! kill -0 "$cmd_pid" 2>/dev/null; then
            break
        fi

        local elapsed
        elapsed=$(( $(date +%s) - start_ts ))
        local stage
        stage=$(grep -v '^[[:space:]]*$' "$output_file" | tail -1 | cut -c1-120)
        if [[ -z "$stage" ]]; then
            stage="$last_stage"
        fi
        last_stage="$stage"
        echo "CODERABBIT:RUNNING:${elapsed}s|stage:${stage}" >&2
    done

    wait "$cmd_pid"
    local retval=$?
    cat "$output_file"
    rm -f "$output_file"
    return "$retval"
}

NORMALIZED_TOOL_ARGS=()

normalize_tool_args() {
    local tool_name="$1"
    local dir_type="$2"
    shift 2

    NORMALIZED_TOOL_ARGS=()

    for arg in "$@"; do
        local normalized="$arg"

        # Tools with working_dir=backend or test cd into backend/, so explicit
        # paths like backend/app/foo.py must be rewritten to app/foo.py.
        # This applies to all backend tools (ruff, types, etc.), not just pytest.
        if [[ "$arg" != -* && ("$dir_type" == "backend" || ("$dir_type" == "test" && "$tool_name" == "pytest")) ]]; then
            local path_part="$arg"
            local suffix=""

            if [[ "$arg" == *"::"* ]]; then
                path_part="${arg%%::*}"
                suffix="::${arg#*::}"
            fi

            if [[ "$path_part" == */* || "$path_part" == *.py || "$path_part" == /* ]]; then
                normalized="$path_part"

                if [[ "$normalized" == "$PROJECT_DIR/"* ]]; then
                    normalized="${normalized#$PROJECT_DIR/}"
                fi

                if [[ "$normalized" == backend/* ]]; then
                    normalized="${normalized#backend/}"
                fi

                normalized="${normalized}${suffix}"
            fi
        fi

        NORMALIZED_TOOL_ARGS+=("$normalized")
    done
}

is_frontend_pytest_target() {
    local arg="$1"
    local path_part="$arg"

    [[ "$arg" == -* ]] && return 1

    if [[ "$arg" == *"::"* ]]; then
        path_part="${arg%%::*}"
    fi

    [[ -z "$path_part" ]] && return 1

    if [[ "$path_part" == "$PROJECT_DIR/"* ]]; then
        path_part="${path_part#$PROJECT_DIR/}"
    fi

    if [[ "$path_part" == frontend/* ]]; then
        return 0
    fi

    if [[ ! -d "$PROJECT_DIR/frontend" ]]; then
        return 1
    fi

    case "$path_part" in
        src/*|./src/*|__tests__/*|./__tests__/*)
            case "$path_part" in
                *.ts|*.tsx|*.js|*.jsx) return 0 ;;
            esac
            ;;
    esac

    return 1
}

is_cross_project_pytest_target() {
    local arg="$1"
    local path_part="$arg"

    [[ "$arg" == -* ]] && return 1

    if [[ "$arg" == *"::"* ]]; then
        path_part="${arg%%::*}"
    fi

    [[ -z "$path_part" ]] && return 1

    if [[ "$path_part" == /* ]]; then
        [[ "$path_part" != "$PROJECT_DIR/"* ]] && return 0
        return 1
    fi

    case "$path_part" in
        ../*|*/../*)
            return 0
            ;;
    esac

    return 1
}

# Generic TOON wrapper - runs any tool defined in TOOL_DEFS
run_tool_toon() {
    local tool_name="$1"

    # Parse tool definition
    local def="${TOOL_DEFS[$tool_name]}"
    if [[ -z "$def" ]]; then
        echo "ERROR:unknown_tool:$tool_name"
        return 1
    fi

    IFS='|' read -r label binary args count_method dir_type fallback_global pass_path <<< "$def"

    # Smart Check: Skip Python tools if no Python backend (when running explicit command like 'dt types')
    if [[ "$dir_type" == "backend" || "$dir_type" == "test" ]]; then
        if ! has_python_backend "$PROJECT_DIR"; then
            echo "$label:OK:skipped_no_python"
            return 0
        fi
    fi
    if [[ "$tool_name" == "vitest" ]] && ! has_frontend_vitest "$PROJECT_DIR"; then
        echo "$label:OK:skipped_no_vitest"
        return 0
    fi

    ensure_output_dir
    local details_file="$OUTPUT_DIR/${tool_name}-details.txt"

    # Get working directory before resolving project-local binaries
    local work_dir
    work_dir=$(get_tool_working_dir "$dir_type")

    # Find binary
    local tool_bin
    tool_bin=$(resolve_tool_binary "$binary" "$dir_type" "$work_dir" "$fallback_global") || tool_bin=""
    if [[ -z "$tool_bin" ]]; then
        echo "$label:FAIL:${binary}_not_found"
        return 1
    fi

    # Change to appropriate directory for tools that need it
    if [[ "$dir_type" == "backend" ]]; then
        cd "$BACKEND_PATH"
    elif [[ "$dir_type" == "test" ]]; then
        # For test runners: prefer backend (when tests/ is there), else project root
        if [[ -d "$BACKEND_PATH/tests" ]]; then
            cd "$BACKEND_PATH"
        else
            cd "$PROJECT_DIR"
        fi
    elif [[ "$dir_type" == "frontend" ]]; then
        cd "$work_dir"
    elif [[ "$dir_type" == "project_root" ]]; then
        cd "$PROJECT_DIR"
    fi

    normalize_tool_args "$tool_name" "$dir_type" "${EXTRA_ARGS[@]}"

    # Execute tool (NORMALIZED_TOOL_ARGS passed as array to preserve quoted arguments like -k "expr with spaces")
    local output retval=0
    if [[ "$tool_name" == "pytest" ]]; then
        local frontend_target=""
        local cross_project_target=""
        for arg in "${NORMALIZED_TOOL_ARGS[@]}"; do
            if is_frontend_pytest_target "$arg"; then
                frontend_target="$arg"
                break
            fi
            if is_cross_project_pytest_target "$arg"; then
                cross_project_target="$arg"
                break
            fi
        done
        if [[ -n "$frontend_target" ]]; then
            output=$(
                cat <<EOF
dt pytest only runs Python tests and cannot execute frontend test target: $frontend_target
Run the frontend test from the frontend package instead, for example:
  cd frontend && npm test -- --run ${frontend_target#frontend/}
EOF
            )
            retval=2
        elif [[ -n "$cross_project_target" ]]; then
            output=$(
                cat <<EOF
dt pytest runs in the current project's pytest context and cannot mix cross-project targets: $cross_project_target
Run separate dt pytest commands from each repo instead.
EOF
            )
            retval=2
        else
            output=$("$tool_bin" $args "${NORMALIZED_TOOL_ARGS[@]}" 2>&1) || retval=$?
        fi
    elif [[ "$count_method" == "coderabbit_parse" ]]; then
        output=$(run_coderabbit_with_progress "$tool_bin" $args "${NORMALIZED_TOOL_ARGS[@]}") || retval=$?
    elif [[ "$pass_path" == "1" ]]; then
        output=$("$tool_bin" $args "${NORMALIZED_TOOL_ARGS[@]}" "$work_dir" 2>&1) || retval=$?
    else
        output=$("$tool_bin" $args "${NORMALIZED_TOOL_ARGS[@]}" 2>&1) || retval=$?
    fi

    # Count issues
    local count
    count=$(count_issues "$count_method" "$output" "$retval")

    # Determine success based on method
    local is_success=0
    case "$count_method" in
        coderabbit_parse)
            # CodeRabbit exits 0 even with findings; success = no findings
            # But non-zero exit (rate limit, network error) must NOT be treated as success
            if [[ $retval -eq 0 && "$count" == "0" ]]; then
                is_success=1
            elif [[ $retval -ne 0 ]]; then
                # Preserve error info in count for FAIL output
                local cr_error_hint=""
                if echo "$output" | grep -qi "rate limit"; then
                    cr_error_hint="rate_limited"
                elif echo "$output" | grep -qi "error"; then
                    cr_error_hint="error"
                fi
                count="${cr_error_hint:-error}"
            fi
            ;;

        pytest_parse)
            # pytest: trust summary line over exit code.
            # Non-zero exit with "passed" but no "failed"/"error" = coverage/warnings issue, not test failure.
            if [[ $retval -eq 0 ]]; then
                is_success=1
            elif echo "$count" | grep -qE '\bpassed\b' && ! echo "$count" | grep -qiE '\b(failed|error)\b'; then
                is_success=1
            fi
            ;;
        vitest_parse)
            [[ $retval -eq 0 ]] && is_success=1
            ;;
        wc_l)
            # For line counting, exit code 0 means success regardless of output
            [[ $retval -eq 0 ]] && is_success=1 && count=0
            ;;
        biome_parse|grep_error_ts)
            # biome/tsc: trust issue count over exit code (npm warnings cause non-zero exit)
            [[ "$count" == "0" ]] && is_success=1
            ;;
        *)
            # Others use count == 0 AND exit code
            [[ $retval -eq 0 && "$count" == "0" ]] && is_success=1
            ;;
    esac

    if [[ $is_success -eq 1 ]]; then
        # Clear stale details file on success (don't rotate passes)
        rm -f "$details_file"
        echo "$label:OK:$count"
        # Sync pass result to quality gate
        sync_quality_result "$tool_name" "pass" 0
    else
        # Detect invalid argument errors (exit code 2 for most CLIs, 4 for pytest)
        # and output patterns like "unexpected argument" / "unrecognized arguments"
        local is_arg_error=0
        local clean_output
        clean_output=$(echo "$output" | strip_ansi)
        if echo "$clean_output" | grep -qiE '(unexpected argument|unrecognized arguments|invalid option|unknown option)'; then
            is_arg_error=1
        fi

        if [[ $is_arg_error -eq 1 ]]; then
            # Show the tool's own error message plus valid dt-level flags
            local bad_flag
            bad_flag=$(echo "$clean_output" | grep -oiE "'--?[a-zA-Z0-9_-]+'" | head -1)
            echo "$label:ERROR:invalid_flag${bad_flag:+:$bad_flag}"
            echo ""
            echo "Tool error output:"
            echo "$clean_output" | head -5
            echo ""
            echo "dt $tool_name accepts these flags before '--':"
            echo "  --check, -c          Full quality gate"
            echo "  --quick, -q          Fast lint+types"
            echo "  --changed-only, -d   Only check changed files"
            echo "  --fix, -f            Auto-fix + deps"
            echo ""
            echo "To pass flags directly to $binary, put them after '--':"
            echo "  dt $tool_name -- --your-flag"
            echo "  Run '$binary --help' for $binary-specific options."
            return 1
        fi

        # Rotate previous failures before writing new one
        rotate_details "$details_file"
        echo "$output" | strip_ansi > "$details_file"
        # Include first line of output as hint for quick diagnosis
        local hint=""
        if [[ -n "$output" ]]; then
            # Use || true to prevent SIGPIPE (exit 141) from head -1 with pipefail
            hint=$(echo "$output" | strip_ansi | head -1 | cut -c1-120) || true
        fi
        echo "$label:FAIL:$count|details:$details_file${hint:+|hint:$hint}"
        # Sync fail result to quality gate
        sync_quality_result "$tool_name" "fail" "$count"
        return 1
    fi
}

show_help() {
    echo "Dev Standards - Cross-project tooling management"
    echo ""
    echo "Usage: $0 [SUBCOMMAND] [OPTIONS]"
    echo ""
    echo "Subcommands (TOON output for Claude):"
    echo "  cleanroom        Run a command in a clean snapshot of the working tree"
    echo "  pytest           Run pytest with TOON output (<100 bytes on pass)"
    echo "  ruff             Run ruff with TOON output (<50 bytes on clean)"
    echo "  types            Run ty with TOON output (<50 bytes on clean)"
    echo "  biome            Run biome lint with TOON output (frontend)"
    echo "  tsc              Run tsc with TOON output (frontend)"
    echo "  vitest           Run Vitest with TOON output (frontend, when configured)"
    echo "  sqlfluff         Run sqlfluff lint with TOON output (migrations)"
    echo "  squawk           Run squawk migration safety with TOON output (migrations)"
    echo "  coderabbit       Run CodeRabbit AI review with TOON output (not in --check/--quick)"
    echo ""
    echo "Options:"
    echo "  (no args)        Dashboard of all projects (default)"
    echo "  --check, -c      Quality gate: lint, types, tests + frontend checks (current project)"
    echo "  --quick, -q      Fast check: lint, types + frontend (for commits)"
    echo "  --changed-only, -d  Only check changed files (combine with -c or -q)"
    echo "  --frontend-only  Frontend only: biome + tsc + vitest when configured"
    echo "  --fix, -f        Auto-fix + install deps + pre-commit install (current project)"
    echo "  --fix-all        Fix all managed projects"
    echo "  --rebuild-venv   Delete and recreate venv (fixes corrupt venv)"
    echo "  --help, -h       Show this help"
    echo ""
    echo "Examples:"
    echo "  dt --check                 # Full check on all files"
    echo "  dt --quick --changed-only  # Fast check on changed files only (for commits)"
    echo "  dt -q -d                   # Same as above, short form"
    echo "  dt cleanroom -- bash scripts/install.sh --skip-systemd"
    echo ""
    echo "Managed: ${MANAGED_PROJECTS[*]}"
}

# =============================================================================
# MAIN
# =============================================================================

# Safety net: ensure check actions always print an A-Term summary, even on
# unexpected exit (e.g., signal, unhandled error in a sub-function).
_DT_SUMMARY_PRINTED=0
_dt_exit_trap() {
    local exit_code=$?
    if [[ $_DT_SUMMARY_PRINTED -eq 0 ]]; then
        case "$ACTION" in
            check|quick_check|frontend_only_check)
                if [[ $exit_code -eq 0 ]]; then
                    echo "CHECK_RESULT:OK"
                else
                    echo "CHECK_RESULT:FAIL:exit_code=$exit_code"
                fi
                ;;
        esac
    fi
}
trap _dt_exit_trap EXIT

case "$ACTION" in
    help)
        show_help
        ;;
    status)
        status_dashboard
        ;;
    check)
        full_check "$PROJECT_DIR"
        _DT_SUMMARY_PRINTED=1
        ;;
    quick_check)
        quick_check "$PROJECT_DIR"
        _DT_SUMMARY_PRINTED=1
        ;;
    frontend_only_check)
        frontend_only_check "$PROJECT_DIR"
        _DT_SUMMARY_PRINTED=1
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
    tool_toon)
        run_tool_toon "$TOOL_NAME"
        ;;
    cleanroom)
        run_cleanroom_command
        ;;
esac
