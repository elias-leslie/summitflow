"""Table categorization utilities for database scanner.

Provides logic to categorize database tables by their naming patterns.
"""

from __future__ import annotations


def categorize_table(table_name: str) -> str:
    """Categorize a table by its name pattern.

    Args:
        table_name: The name of the database table

    Returns:
        Category string (e.g., 'auth', 'logging', 'data')
    """
    name = table_name.lower()

    if "user" in name or "auth" in name or "credential" in name:
        return "auth"
    if "log" in name or "history" in name or "audit" in name:
        return "logging"
    if "config" in name or "setting" in name or "pref" in name:
        return "config"
    if "cache" in name or "temp" in name:
        return "cache"
    if "metric" in name or "stat" in name or "analytic" in name:
        return "analytics"
    if "task" in name or "job" in name or "queue" in name:
        return "tasks"
    if "feature" in name or "capability" in name:
        return "features"
    if "sitemap" in name or "endpoint" in name or "route" in name:
        return "sitemap"
    if "evidence" in name or "artifact" in name:
        return "evidence"
    if "vision" in name or "goal" in name:
        return "vision"
    if "file" in name or "scan" in name or "explorer" in name:
        return "files"
    if "project" in name:
        return "projects"

    return "data"
