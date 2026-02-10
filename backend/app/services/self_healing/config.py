"""Configuration and constants for self-healing orchestration."""

from __future__ import annotations

# Budget cap per orchestration run. Prevents runaway costs from autonomous fixes.
# Set conservatively at $2 to limit exposure while allowing meaningful work.
BUDGET_CAP_USD = 2.0

# Priority order for check types: fix lint first, then types, then tests
# Rationale: Lint errors are usually simpler, type errors may cascade from lint,
# and test failures often require both to be clean first.
CHECK_TYPE_PRIORITY = ["ruff", "biome", "mypy", "tsc", "pytest"]

# Maximum errors to fix per orchestration run (prevents runaway)
MAX_ERRORS_PER_RUN = 20

# Maximum errors to fix per project per run
MAX_ERRORS_PER_PROJECT = 10
