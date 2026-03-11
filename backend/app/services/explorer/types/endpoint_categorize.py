"""Endpoint categorization and entry-building helpers for EndpointScanner."""

from __future__ import annotations

from ..models import ExplorerEntryCreate

# Ordered list of (path_fragments, category) for endpoint categorization.
_CATEGORY_RULES: list[tuple[tuple[str, ...], str]] = [
    (("/auth", "/login", "/logout"), "auth"),
    (("/user", "/profile"), "users"),
    (("/admin",), "admin"),
    (("/health", "/status"), "health"),
    (("/metrics", "/stats", "/analytics"), "analytics"),
    (("/config", "/settings"), "config"),
    (("/file", "/upload", "/download"), "files"),
    (("/task", "/job"), "tasks"),
    (("/feature", "/capability"), "features"),
    (("/project",), "projects"),
    (("/sitemap", "/endpoint"), "sitemap"),
    (("/evidence", "/artifact"), "evidence"),
    (("/vision", "/goal"), "vision"),
    (("/bead",), "beads"),
    (("/explorer",), "explorer"),
]

SQL_KEYWORDS: frozenset[str] = frozenset(
    {"select", "where", "order", "group", "limit", "offset", "values"}
)

TABLE_PATTERNS: list[str] = [
    r"FROM\s+([a-z_][a-z0-9_]*)",
    r"JOIN\s+([a-z_][a-z0-9_]*)",
    r"INTO\s+([a-z_][a-z0-9_]*)",
    r"UPDATE\s+([a-z_][a-z0-9_]*)",
]


def categorize_endpoint(endpoint_path: str) -> str:
    """Categorize an endpoint by its path pattern."""
    path = endpoint_path.lower()
    for fragments, category in _CATEGORY_RULES:
        if any(frag in path for frag in fragments):
            return category
    return "api"


def build_full_path(router_prefix: str, path: str) -> str:
    """Combine router prefix and route path into a full endpoint path."""
    if path in ("", "/"):
        return router_prefix or "/"
    if router_prefix:
        return router_prefix.rstrip("/") + "/" + path.lstrip("/")
    return path


def make_endpoint_entry(
    method: str,
    full_path: str,
    function_name: str | None,
    source_file: str,
    depends_on_tables: list[str],
) -> ExplorerEntryCreate:
    """Build an ExplorerEntryCreate for a single route."""
    return ExplorerEntryCreate(
        path=f"{method.upper()} {full_path}",
        name=function_name or full_path.split("/")[-1] or "root",
        health_status="unknown",
        metadata={
            "method": method.upper(),
            "port": 8001,
            "source_file": source_file,
            "function_name": function_name or "unknown",
            "category": categorize_endpoint(full_path),
            "depends_on_tables": depends_on_tables,
            "called_by_frontend": [],
            "http_status": None,
            "response_time_ms": None,
            "console_errors": None,
            "console_warnings": None,
            "last_health_check": None,
        },
    )
