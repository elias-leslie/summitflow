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


def categorize_task(task_name: str) -> str:
    """Categorize a task by its name pattern."""
    name = task_name.lower()
    for category, keywords in _CATEGORY_KEYWORDS:
        if any(kw in name for kw in keywords):
            return category
    return "scheduled"
