"""Table categorization utilities for database scanner.

Provides logic to categorize database tables by their naming patterns.
"""

from __future__ import annotations

_DEFAULT_CATEGORY = "data"

# Maps a category name to the substrings that indicate membership.
# Ordered from most specific to most general to ensure correct precedence.
_CATEGORY_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("auth",      ("user", "auth", "credential")),
    ("logging",   ("log", "history", "audit")),
    ("config",    ("config", "setting", "pref")),
    ("cache",     ("cache", "temp")),
    ("analytics", ("metric", "stat", "analytic")),
    ("tasks",     ("task", "job", "queue")),
    ("features",  ("feature", "capability")),
    ("sitemap",   ("sitemap", "endpoint", "route")),
    ("evidence",  ("evidence", "artifact")),
    ("vision",    ("vision", "goal")),
    ("files",     ("file", "scan", "explorer")),
    ("projects",  ("project",)),
]


def _first_matching_category(name: str) -> str | None:
    """Return the first category whose keywords appear in *name*, or None."""
    for category, keywords in _CATEGORY_PATTERNS:
        if any(keyword in name for keyword in keywords):
            return category
    return None


def categorize_table(table_name: str) -> str:
    """Categorize a table by its name pattern.

    Args:
        table_name: The name of the database table

    Returns:
        Category string (e.g., 'auth', 'logging', 'data')
    """
    name = table_name.lower()
    return _first_matching_category(name) or _DEFAULT_CATEGORY
