#!/bin/bash
#
# Dev Standards Configuration
# Canonical versions and settings for all projects
# Source of truth - other projects symlink to summitflow
#

# =============================================================================
# CANONICAL VERSIONS - Update here, all projects follow
# Last verified: 2026-02-05
# =============================================================================

# Linting & Formatting
export CANONICAL_RUFF="0.15.0"
export CANONICAL_TY="0.0.17"
export CANONICAL_PRECOMMIT="4.5.1"

# Testing - Core
export CANONICAL_PYTEST="9.0.2"
export CANONICAL_PYTEST_ASYNCIO="1.3.0"
export CANONICAL_PYTEST_COV="7.0.0"
export CANONICAL_PYTEST_XDIST="3.8.0"

# Testing - Essential Plugins
export CANONICAL_PYTEST_MOCK="3.15.1"
export CANONICAL_PYTEST_TIMEOUT="2.4.0"
export CANONICAL_PYTEST_RANDOMLY="3.16.0"

# SQL Quality
export CANONICAL_SQLFLUFF="3.3.1"
export CANONICAL_SQUAWK="1.5.2"

# Python version requirements
export MIN_PYTHON_VERSION="3.12"

# Directories excluded from linting/type-checking (dead code, archived scripts)
LINT_EXCLUDE_DIRS=(
    "scripts/archived"
    "__pycache__"
)
export LINT_EXCLUDE_DIRS

# =============================================================================
# PROJECT REGISTRY - All managed projects
# =============================================================================

# Projects registered in SummitFlow (auto-discovered via API if available)
# Note: JS-only projects such as monkey-fight stay outside the Python-managed list.
MANAGED_PROJECTS=(
    "summitflow"
    "agent-hub"
    "a-term"
    "portfolio-ai"
    "vantage"
    "test1"
    "test2"
    "test3"
    "persona-sandbox"
)
export MANAGED_PROJECTS

# Project-specific venv locations (relative to project root)
# Format: project_name:venv_path:backend_path
PROJECT_VENV_MAP=(
    "summitflow:backend/.venv:backend"
    "agent-hub:backend/.venv:backend"
    "a-term:.venv:."
    "portfolio-ai:backend/.venv:backend"
    "vantage:backend/.venv:backend"
    "test1:backend/.venv:backend"
    "test2:backend/.venv:backend"
    "test3:backend/.venv:backend"
)
export PROJECT_VENV_MAP

# Docker container names for alembic fallback (project → container name)
DOCKER_SERVICE_MAP=(
    "summitflow:summitflow-stack-summitflow-api-1"
    "agent-hub:summitflow-stack-agent-hub-api-1"
    "portfolio-ai:summitflow-stack-portfolio-api-1"
)
export DOCKER_SERVICE_MAP

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
