"""Task categorization utilities."""

_CATEGORY_KEYWORDS: list[tuple[str, list[str]]] = [
    ("data-fetch", ["fetch", "sync", "pull"]),
    ("maintenance", ["cleanup", "prune", "archive"]),
    ("reporting", ["report", "summary", "digest"]),
    ("alerts", ["alert", "notify"]),
    ("backup", ["backup", "snapshot"]),
    ("analytics", ["analytics", "metric", "stat"]),
    ("market-data", ["market", "price", "quote"]),
    ("news", ["news", "headline"]),
    ("indicators", ["indicator", "signal"]),
]

_DEFAULT_CATEGORY = "scheduled"

# Flat keyword-to-category map built once at import time for efficient lookup.
_KEYWORD_MAP: dict[str, str] = {
    kw: category
    for category, keywords in _CATEGORY_KEYWORDS
    for kw in keywords
}


def _match_category(name: str) -> str | None:
    """Return the first category whose keyword appears in *name*, or None."""
    return next((cat for kw, cat in _KEYWORD_MAP.items() if kw in name), None)


def categorize_task(task_name: str) -> str:
    """Categorize a task by its name pattern."""
    name = task_name.lower()
    return _match_category(name) or _DEFAULT_CATEGORY
