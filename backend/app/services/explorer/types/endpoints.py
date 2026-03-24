"""Endpoint scanner for Explorer.

Scans FastAPI routes, producing entries for explorer_entries table.
Frontend pages are handled by PageScanner.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ....config import SUMMITFLOW_BACKEND_PORT
from ....logging_config import get_logger
from ..base import BaseScanner, get_project_config
from ..health import calculate_health_for_entry
from ..models import ExplorerEntryCreate

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Endpoint categorization & entry-building helpers
# ---------------------------------------------------------------------------

_ENDPOINT_CATEGORY_RULES: list[tuple[tuple[str, ...], str]] = [
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


def _categorize_endpoint(endpoint_path: str) -> str:
    """Categorize an endpoint by its path pattern."""
    path = endpoint_path.lower()
    for fragments, category in _ENDPOINT_CATEGORY_RULES:
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
            "port": SUMMITFLOW_BACKEND_PORT,
            "source_file": source_file,
            "function_name": function_name or "unknown",
            "category": _categorize_endpoint(full_path),
            "depends_on_tables": depends_on_tables,
            "called_by_frontend": [],
            "http_status": None,
            "response_time_ms": None,
            "console_errors": None,
            "console_warnings": None,
            "last_health_check": None,
        },
    )


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

_SKIP_PATHS = ("/health", "/docs", "/openapi", "/redoc")
_ROUTE_PATTERN = r'@router\.(get|post|put|delete|patch)\(["\']([^"\']+)["\']\)'
_PREFIX_PATTERN = r'APIRouter\s*\([^)]*prefix\s*=\s*["\']([^"\']+)["\']'


class EndpointScanner(BaseScanner):
    """Scans API endpoints for explorer entries."""

    entry_type = "endpoint"

    def __init__(self, project_id: str, config: dict[str, Any] | None = None) -> None:
        super().__init__(project_id, config)
        self.root_path: Path | None = None
        self.backend_dir: str = "backend"

    def _load_config(self, project_config: dict[str, Any]) -> None:
        """Apply project and override config to set root_path and backend_dir."""
        if project_config.get("root_path"):
            self.root_path = Path(project_config["root_path"])
        if project_config.get("backend_dir"):
            self.backend_dir = project_config["backend_dir"]
        if self.config:
            if self.config.get("root_path"):
                self.root_path = Path(self.config["root_path"])
            if self.config.get("backend_dir"):
                self.backend_dir = self.config["backend_dir"]

    def scan(self) -> list[ExplorerEntryCreate]:
        """Scan API routes and return endpoint entries."""
        project_config = get_project_config(self.project_id)
        if not project_config:
            logger.error("Project not found: %s", self.project_id)
            return []
        self._load_config(project_config)
        if not self.root_path:
            logger.error("No root_path for project %s", self.project_id)
            return []
        logger.info("Endpoint scan started for %s", self.project_id)
        entries = self._scan_api_routes()
        logger.info("Endpoint scan found %d API endpoints", len(entries))
        return entries

    def _scan_api_routes(self) -> list[ExplorerEntryCreate]:
        """Scan FastAPI route files for endpoints."""
        if not self.root_path:
            return []
        api_dirs = [
            self.root_path / self.backend_dir / "app" / "api",
            self.root_path / self.backend_dir / "app" / "routes",
        ]
        route_files = [
            f
            for api_dir in api_dirs
            if api_dir.exists()
            for f in api_dir.glob("*.py")
            if not f.name.startswith("_")
        ]
        entries: list[ExplorerEntryCreate] = []
        for route_file in route_files:
            try:
                entries.extend(self._scan_route_file(route_file))
            except Exception as e:
                logger.warning("Failed to scan route file %s: %s", route_file, e)
        return entries

    def _scan_route_file(self, route_file: Path) -> list[ExplorerEntryCreate]:
        """Scan a single route file for API endpoints."""
        content = route_file.read_text()
        prefix_match = re.search(_PREFIX_PATTERN, content)
        router_prefix = prefix_match.group(1) if prefix_match else ""
        depends_on_tables = self._detect_table_dependencies(content)
        source_file = str(route_file.relative_to(self.root_path)) if self.root_path else "unknown"
        entries = []
        for method, path in re.findall(_ROUTE_PATTERN, content):
            if path in _SKIP_PATHS:
                continue
            full_path = build_full_path(router_prefix, path)
            function_name = self._extract_function_name(content, method, path)
            entries.append(make_endpoint_entry(method, full_path, function_name, source_file, depends_on_tables))
        return entries

    def _extract_function_name(self, content: str, method: str, path: str) -> str | None:
        """Extract function name for a route decorator."""
        try:
            decorator_pattern = rf'@router\.{method}\(["\']' + re.escape(path) + r'["\']\)'
            decorator_match = re.search(decorator_pattern, content)
            if not decorator_match:
                return None
            remaining = content[decorator_match.end():]
            func_match = re.search(r"^\s*(?:async\s+)?def\s+([a-z_][a-z0-9_]*)", remaining, re.MULTILINE)
            if func_match:
                return func_match.group(1)
        except Exception:
            logger.debug("Failed to extract function name for route %s %s", method, path, exc_info=True)
        return None

    def _detect_table_dependencies(self, content: str) -> list[str]:
        """Detect which tables an endpoint depends on."""
        sql_content = " ".join(
            m
            for pattern in (r'"""([^"]*?)"""', r"'''([^']*?)'''")
            for m in re.findall(pattern, content, re.DOTALL)
        )
        tables: set[str] = set()
        for pattern in TABLE_PATTERNS:
            tables.update(re.findall(pattern, sql_content, re.IGNORECASE))
        return sorted(t for t in tables if t.lower() not in SQL_KEYWORDS)

    def get_health_status(self, entry: ExplorerEntryCreate) -> str:
        """Determine health status for an endpoint entry."""
        return calculate_health_for_entry(self.entry_type, entry.metadata)
