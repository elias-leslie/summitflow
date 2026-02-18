"""Table categorization utilities for database scanner.

Provides logic to categorize database tables by their naming patterns.
"""

from __future__ import annotations

# Maps a category name to the substrings that indicate membership.
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


def _matches_category(name: str, keywords: tuple[str, ...]) -> bool:
    """Return True if *name* contains any of the given keywords."""
    return any(keyword in name for keyword in keywords)


def categorize_table(table_name: str) -> str:
    """Categorize a table by its name pattern.

    Args:
        table_name: The name of the database table

    Returns:
        Category string (e.g., 'auth', 'logging', 'data')
    """
    name = table_name.lower()

    for category, keywords in _CATEGORY_PATTERNS:
        if _matches_category(name, keywords):
            return category

    return "data"
