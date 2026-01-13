#!/bin/bash
#
# Dev Standards Configuration
# Canonical versions and settings for all projects
# Source of truth - other projects symlink to summitflow
#

# =============================================================================
# CANONICAL VERSIONS - Update here, all projects follow
# =============================================================================

export CANONICAL_RUFF="0.14.10"
export CANONICAL_MYPY="1.19.1"
export CANONICAL_PYTEST="9.0.2"
export CANONICAL_PRECOMMIT="4.5.1"
export CANONICAL_PYTEST_ASYNCIO="1.3.0"
export CANONICAL_PYTEST_COV="7.0.0"
export CANONICAL_PYTEST_XDIST="3.6.1"

# Python version requirements
export MIN_PYTHON_VERSION="3.12"

# =============================================================================
# PROJECT REGISTRY - All managed projects
# =============================================================================

# Projects registered in SummitFlow (auto-discovered via API if available)
MANAGED_PROJECTS=(
    "summitflow"
    "agent-hub"
    "terminal"
    "portfolio-ai"
    "monkey-fight"
)
export MANAGED_PROJECTS

# Project-specific venv locations (relative to project root)
# Format: project_name:venv_path:backend_path
PROJECT_VENV_MAP=(
    "summitflow:backend/.venv:backend"
    "agent-hub:backend/.venv:backend"
    "terminal:.venv:terminal"
    "portfolio-ai:backend/.venv:backend"
    "monkey-fight:backend/.venv:backend"
)
export PROJECT_VENV_MAP

# =============================================================================
# QUALITY THRESHOLDS
# =============================================================================

export MIN_TEST_COVERAGE=70
export MAX_RUFF_VIOLATIONS=0
export MAX_MYPY_ERRORS=0

# =============================================================================
# DEV DEPENDENCIES - Full list for pyproject.toml sync
# =============================================================================

DEV_DEPS=(
    "pytest>=${CANONICAL_PYTEST}"
    "pytest-asyncio>=${CANONICAL_PYTEST_ASYNCIO}"
    "pytest-cov>=${CANONICAL_PYTEST_COV}"
    "pytest-xdist>=${CANONICAL_PYTEST_XDIST}"
    "ruff>=${CANONICAL_RUFF}"
    "mypy>=${CANONICAL_MYPY}"
    "pre-commit>=${CANONICAL_PRECOMMIT}"
)
export DEV_DEPS

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

# Get venv path for a project
get_venv_path() {
    local project_name="$1"
    local project_root="$2"

    for mapping in "${PROJECT_VENV_MAP[@]}"; do
        local name="${mapping%%:*}"
        local rest="${mapping#*:}"
        local venv_path="${rest%%:*}"

        if [[ "$name" == "$project_name" ]]; then
            echo "${project_root}/${venv_path}"
            return 0
        fi
    done

    # Default fallback
    echo "${project_root}/.venv"
}

# Get backend/source path for a project
get_backend_path() {
    local project_name="$1"
    local project_root="$2"

    for mapping in "${PROJECT_VENV_MAP[@]}"; do
        local name="${mapping%%:*}"
        local rest="${mapping#*:}"
        local backend_path="${rest#*:}"

        if [[ "$name" == "$project_name" ]]; then
            echo "${project_root}/${backend_path}"
            return 0
        fi
    done

    # Default fallback
    echo "${project_root}"
}

# Check if version meets minimum
version_gte() {
    local installed="$1"
    local required="$2"

    # Simple version comparison using sort -V
    printf '%s\n%s\n' "$required" "$installed" | sort -V | head -n1 | grep -q "^${required}$"
}
