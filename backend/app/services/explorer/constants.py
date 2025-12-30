"""Shared constants for explorer and codebase scanning.

Merged patterns from executor.py and files.py for consistent directory exclusion.
"""

from __future__ import annotations

# Directories to skip during scanning (union of all skip patterns)
SKIP_DIRS: frozenset[str] = frozenset(
    {
        # Version control
        ".git",
        # Package/dependency directories
        "node_modules",
        ".venv",
        "venv",
        # Build/output directories
        ".next",
        "dist",
        "build",
        # Cache directories
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        # Data directories (project-specific)
        "data",
        "solution_state",
        ".beads",
    }
)
