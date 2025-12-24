"""Endpoint scanner for Explorer.

Scans API routes (FastAPI), producing entries for explorer_entries table.
Frontend pages are scanned by PageScanner.

Metadata schema (per architecture doc):
{
  "method": "GET",
  "port": 8001,
  "source_file": "app/api/users.py",
  "function_name": "get_user",
  "category": "users",
  "http_status": 200,
  "response_time_ms": 45,
  "depends_on_tables": ["users", "profiles"],
  "called_by_frontend": ["/users/[id]", "/dashboard"],
  "last_health_check": "2025-12-18T10:30:00Z"
}
"""

from __future__ import annotations

import re
from pathlib import Path

from ....logging_config import get_logger
from ..base import BaseScanner, get_project_config
from ..models import ExplorerEntryCreate

logger = get_logger(__name__)


def categorize_endpoint(endpoint_path: str) -> str:
    """Categorize an endpoint by its path pattern."""
    path = endpoint_path.lower()

    if "/auth" in path or "/login" in path or "/logout" in path:
        return "auth"
    if "/user" in path or "/profile" in path:
        return "users"
    if "/admin" in path:
        return "admin"
    if "/health" in path or "/status" in path:
        return "health"
    if "/metrics" in path or "/stats" in path or "/analytics" in path:
        return "analytics"
    if "/config" in path or "/settings" in path:
        return "config"
    if "/file" in path or "/upload" in path or "/download" in path:
        return "files"
    if "/celery" in path or "/task" in path or "/job" in path:
        return "tasks"
    if "/feature" in path or "/capability" in path:
        return "features"
    if "/project" in path:
        return "projects"
    if "/sitemap" in path or "/endpoint" in path:
        return "sitemap"
    if "/evidence" in path or "/artifact" in path:
        return "evidence"
    if "/vision" in path or "/goal" in path:
        return "vision"
    if "/bead" in path:
        return "beads"
    if "/explorer" in path:
        return "explorer"

    return "api"


class EndpointScanner(BaseScanner):
    """Scans API endpoints for explorer entries."""

    entry_type = "endpoint"

    def __init__(self, project_id: str, config: dict | None = None) -> None:
        super().__init__(project_id, config)
        self.root_path: Path | None = None
        self.backend_dir: str = "backend"

    def scan(self) -> list[ExplorerEntryCreate]:
        """Scan API routes and return endpoint entries."""
        # Get project config
        project_config = get_project_config(self.project_id)
        if not project_config:
            logger.error(f"Project not found: {self.project_id}")
            return []

        if project_config.get("root_path"):
            self.root_path = Path(project_config["root_path"])
        if project_config.get("backend_dir"):
            self.backend_dir = project_config["backend_dir"]

        # Check config overrides
        if self.config:
            if self.config.get("root_path"):
                self.root_path = Path(self.config["root_path"])
            if self.config.get("backend_dir"):
                self.backend_dir = self.config["backend_dir"]

        if not self.root_path:
            logger.error(f"No root_path for project {self.project_id}")
            return []

        logger.info(f"Endpoint scan started for {self.project_id}")

        # Scan API routes only (frontend pages handled by PageScanner)
        entries = self._scan_api_routes()

        logger.info(f"Endpoint scan found {len(entries)} API endpoints")
        return entries

    def _scan_api_routes(self) -> list[ExplorerEntryCreate]:
        """Scan FastAPI route files for endpoints."""
        entries = []

        if not self.root_path:
            return entries

        api_dirs = [
            self.root_path / self.backend_dir / "app" / "api",
            self.root_path / self.backend_dir / "app" / "routes",
        ]

        route_files = []
        for api_dir in api_dirs:
            if api_dir.exists():
                route_files.extend([f for f in api_dir.glob("*.py") if not f.name.startswith("_")])

        for route_file in route_files:
            try:
                file_entries = self._scan_route_file(route_file)
                entries.extend(file_entries)
            except Exception as e:
                logger.warning(f"Failed to scan route file {route_file}: {e}")

        return entries

    def _scan_route_file(self, route_file: Path) -> list[ExplorerEntryCreate]:
        """Scan a single route file for API endpoints."""
        content = route_file.read_text()
        entries = []

        # Extract router prefix
        router_prefix = ""
        prefix_pattern = r'APIRouter\s*\([^)]*prefix\s*=\s*["\']([^"\']+)["\']'
        prefix_match = re.search(prefix_pattern, content)
        if prefix_match:
            router_prefix = prefix_match.group(1)

        # Find route decorators
        route_pattern = r'@router\.(get|post|put|delete|patch)\(["\']([^"\']+)["\']\)'
        matches = re.findall(route_pattern, content)

        for method, path in matches:
            # Skip health/docs endpoints
            if any(x in path for x in ["/health", "/docs", "/openapi", "/redoc"]):
                continue

            # Build full endpoint path
            if path in ("", "/"):
                full_path = router_prefix or "/"
            elif router_prefix:
                full_path = router_prefix.rstrip("/") + "/" + path.lstrip("/")
            else:
                full_path = path

            # Detect function name
            function_name = self._extract_function_name(content, method, path)

            # Detect table dependencies
            depends_on_tables = self._detect_table_dependencies(content)

            category = categorize_endpoint(full_path)

            entries.append(
                ExplorerEntryCreate(
                    path=f"{method.upper()} {full_path}",
                    name=function_name or full_path.split("/")[-1] or "root",
                    health_status="unknown",
                    metadata={
                        "method": method.upper(),
                        "port": 8001,
                        "source_file": str(route_file.relative_to(self.root_path))
                        if self.root_path
                        else "unknown",
                        "function_name": function_name or "unknown",
                        "category": category,
                        "depends_on_tables": depends_on_tables,
                        "called_by_frontend": [],
                        # Health check fields (to be populated by health scanner)
                        "http_status": None,
                        "response_time_ms": None,
                        "console_errors": None,
                        "console_warnings": None,
                        "last_health_check": None,
                    },
                )
            )

        return entries

    def _extract_function_name(self, content: str, method: str, path: str) -> str | None:
        """Extract function name for a route decorator."""
        try:
            decorator_pattern = rf'@router\.{method}\(["\']' + re.escape(path) + r'["\']\)'
            decorator_match = re.search(decorator_pattern, content)

            if not decorator_match:
                return None

            remaining_content = content[decorator_match.end() :]
            func_pattern = r"^\s*(?:async\s+)?def\s+([a-z_][a-z0-9_]*)"
            func_match = re.search(func_pattern, remaining_content, re.MULTILINE)

            if func_match:
                return func_match.group(1)

        except Exception:
            pass

        return None

    def _detect_table_dependencies(self, content: str) -> list[str]:
        """Detect which tables an endpoint depends on."""
        tables = set()

        # Extract SQL string content
        sql_string_patterns = [
            r'"""([^"]*?)"""',
            r"'''([^']*?)'''",
        ]

        sql_content = ""
        for pattern in sql_string_patterns:
            matches = re.findall(pattern, content, re.DOTALL)
            sql_content += " ".join(matches) + " "

        # Search for table references in SQL strings
        table_patterns = [
            r"FROM\s+([a-z_][a-z0-9_]*)",
            r"JOIN\s+([a-z_][a-z0-9_]*)",
            r"INTO\s+([a-z_][a-z0-9_]*)",
            r"UPDATE\s+([a-z_][a-z0-9_]*)",
        ]

        for pattern in table_patterns:
            matches = re.findall(pattern, sql_content, re.IGNORECASE)
            tables.update(matches)

        # Filter out SQL keywords
        exclude_names = {
            "select",
            "where",
            "order",
            "group",
            "limit",
            "offset",
            "values",
        }
        tables = {t for t in tables if t.lower() not in exclude_names}

        return sorted(tables)

    def get_health_status(self, entry: ExplorerEntryCreate) -> str:
        """Determine health status for an endpoint entry."""
        meta = entry.metadata

        # Check if health check data is available
        http_status = meta.get("http_status")

        if http_status is not None:
            if http_status >= 500:
                return "error"
            if http_status >= 400 and http_status != 404:
                return "error"
            if http_status == 404:
                return "warning"

        # Check for orphaned endpoints (no table dependencies and not called by frontend)
        depends_on = meta.get("depends_on_tables", [])
        called_by = meta.get("called_by_frontend", [])

        if not depends_on and not called_by:
            return "warning"

        return "healthy"
