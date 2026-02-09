"""Task categorization utilities."""


def categorize_task(task_name: str) -> str:
    """Categorize a task by its name pattern."""
    name = task_name.lower()

    if "fetch" in name or "sync" in name or "pull" in name:
        return "data-fetch"
    if "cleanup" in name or "prune" in name or "archive" in name:
        return "maintenance"
    if "report" in name or "summary" in name or "digest" in name:
        return "reporting"
    if "alert" in name or "notify" in name:
        return "alerts"
    if "backup" in name or "snapshot" in name:
        return "backup"
    if "analytics" in name or "metric" in name or "stat" in name:
        return "analytics"
    if "market" in name or "price" in name or "quote" in name:
        return "market-data"
    if "news" in name or "headline" in name:
        return "news"
    if "indicator" in name or "signal" in name:
        return "indicators"

    return "scheduled"
