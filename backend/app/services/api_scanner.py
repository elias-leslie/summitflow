"""API endpoint scanner for SummitFlow.

Scans FastAPI routes to discover API endpoints per project.
Detects endpoint metadata: paths, methods, function names, table dependencies.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.logging_config import get_logger
from app.storage.connection import get_connection

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

    return "api"


def calculate_api_health(
    depends_on_tables: list[str],
    frontend_callers: list[str],
) -> str:
    """Calculate health status for an API endpoint.

    Args:
        depends_on_tables: Tables this endpoint depends on
        frontend_callers: Frontend files that call this endpoint

    Returns:
        Health status: "active", "orphaned", "unknown"
    """
    # If frontend calls this endpoint, it's active
    if frontend_callers:
        return "active"

    # Orphaned: No dependencies on any tables AND no frontend callers
    if not depends_on_tables:
        return "orphaned"

    # Default: Active (has table dependencies)
    return "active"


class APIScanner:
    """Scans API routes for a project."""

    def __init__(self, project_id: str, root_path: str, backend_dir: str | None = None) -> None:
        """Initialize scanner.

        Args:
            project_id: The project ID to associate results with
            root_path: Root path of the project
            backend_dir: Relative path to backend directory (default: "backend")
        """
        self.project_id = project_id
        self.root_path = Path(root_path)
        self.backend_dir = backend_dir or "backend"

    def scan(self) -> list[dict[str, Any]]:
        """Scan all API route files.

        Returns:
            List of endpoint capability dicts
        """
        logger.info("scanning_api_endpoints", project=self.project_id)

        capabilities = []

        # Find API directories
        api_dirs = [
            self.root_path / self.backend_dir / "app" / "api",
            self.root_path / self.backend_dir / "app" / "routes",
        ]

        route_files = []
        for api_dir in api_dirs:
            if api_dir.exists():
                route_files.extend([f for f in api_dir.glob("*.py") if not f.name.startswith("_")])

        if not route_files:
            logger.warning("no_api_files_found", project=self.project_id)
            return []

        for route_file in route_files:
            try:
                endpoints = self._scan_route_file(route_file)
                capabilities.extend(endpoints)
            except Exception as e:
                logger.error("route_file_scan_failed", file=route_file.name, error=str(e))

        logger.info("api_scan_complete", project=self.project_id, endpoints=len(capabilities))
        return capabilities

    def _scan_route_file(self, route_file: Path) -> list[dict[str, Any]]:
        """Scan a single route file for API endpoints."""
        content = route_file.read_text()
        endpoints = []

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
            # Skip health/docs/admin endpoints
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

            # Detect frontend usage
            frontend_callers = self._detect_frontend_usage(full_path)

            # Categorize endpoint
            category = categorize_endpoint(full_path)

            # Calculate health status
            health_status = calculate_api_health(depends_on_tables, frontend_callers)

            endpoints.append({
                "endpoint_path": full_path,
                "http_method": method.upper(),
                "category": category,
                "route_file": str(route_file.name),
                "function_name": function_name or "unknown",
                "depends_on_tables": depends_on_tables,
                "frontend_callers": frontend_callers,
                "health_status": health_status,
            })

        return endpoints

    def _extract_function_name(self, content: str, method: str, path: str) -> str | None:
        """Extract function name for a route decorator."""
        try:
            decorator_pattern = rf'@router\.{method}\(["\']' + re.escape(path) + r'["\']\)'
            decorator_match = re.search(decorator_pattern, content)

            if not decorator_match:
                return None

            remaining_content = content[decorator_match.end():]
            func_pattern = r"^\s*(?:async\s+)?def\s+([a-z_][a-z0-9_]*)"
            func_match = re.search(func_pattern, remaining_content, re.MULTILINE)

            if func_match:
                return func_match.group(1)

        except Exception as e:
            logger.debug("failed_to_extract_function_name", error=str(e))

        return None

    def _detect_table_dependencies(self, content: str) -> list[str]:
        """Detect which tables an endpoint depends on."""
        try:
            tables = set()

            # Extract SQL string content
            sql_string_patterns = [
                r'"""([^"]*?)"""',
                r"'''([^']*?)'''",
                r'"([^"\n]*?)"',
                r"'([^'\n]*?)'",
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

            # Filter out SQL keywords and common Python module names
            exclude_names = {
                "select", "where", "order", "group", "limit", "offset", "values",
                "__future__", "typing", "datetime", "pydantic", "fastapi",
                "app", "decimal", "json", "re", "os", "sys", "pathlib", "logging",
            }
            tables = {t for t in tables if t.lower() not in exclude_names}

            return sorted(tables)

        except Exception as e:
            logger.debug("failed_to_detect_table_dependencies", error=str(e))
            return []

    def _detect_frontend_usage(self, endpoint_path: str) -> list[str]:
        """Detect frontend files that call this API endpoint."""
        try:
            callers = set()
            path_no_slash = endpoint_path.lstrip("/")

            # Handle path parameters
            path_pattern = re.sub(r"\{[^}]+\}", r"[^/'\"]+", path_no_slash)
            path_pattern = re.sub(r":[a-zA-Z_]+", r"[^/'\"]+", path_pattern)

            patterns = [
                rf"['\"`]/api/{path_pattern}['\"`]",
                rf"['\"`]/{path_pattern}['\"`]",
                rf"`/api/{path_pattern}`",
                rf"`/{path_pattern}`",
                rf"api\.(get|post|put|delete|patch)\s*\(\s*['\"`]/?{path_pattern}",
            ]

            # Search in frontend directory
            frontend_dir = self.root_path / "frontend"
            if not frontend_dir.exists():
                return []

            for pattern_glob in ["**/*.ts", "**/*.tsx", "**/*.js", "**/*.jsx"]:
                for frontend_file in frontend_dir.glob(pattern_glob):
                    if "node_modules" in str(frontend_file) or ".next" in str(frontend_file):
                        continue

                    try:
                        content = frontend_file.read_text()
                        for pattern in patterns:
                            if re.search(pattern, content, re.IGNORECASE):
                                rel_path = str(frontend_file.relative_to(frontend_dir))
                                callers.add(rel_path)
                                break
                    except Exception:
                        continue

            return sorted(callers)

        except Exception as e:
            logger.debug("failed_to_detect_frontend_usage", endpoint=endpoint_path, error=str(e))
            return []

    def save(self, capabilities: list[dict[str, Any]]) -> int:
        """Save scan results to scanner_api table.

        Args:
            capabilities: List of endpoint capability dicts

        Returns:
            Number of rows upserted
        """
        if not capabilities:
            return 0

        scan_time = datetime.now(UTC)

        with get_connection() as conn, conn.cursor() as cur:
            for cap in capabilities:
                cur.execute(
                    """
                    INSERT INTO scanner_api (
                        project_id, endpoint_path, http_method, category,
                        route_file, function_name, depends_on_tables,
                        frontend_callers, health_status, last_scanned_at, updated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()
                    )
                    ON CONFLICT (project_id, endpoint_path, http_method) DO UPDATE SET
                        category = EXCLUDED.category,
                        route_file = EXCLUDED.route_file,
                        function_name = EXCLUDED.function_name,
                        depends_on_tables = EXCLUDED.depends_on_tables,
                        frontend_callers = EXCLUDED.frontend_callers,
                        health_status = EXCLUDED.health_status,
                        last_scanned_at = EXCLUDED.last_scanned_at,
                        updated_at = NOW()
                    """,
                    [
                        self.project_id,
                        cap["endpoint_path"],
                        cap["http_method"],
                        cap["category"],
                        cap["route_file"],
                        cap["function_name"],
                        json.dumps(cap["depends_on_tables"]),
                        json.dumps(cap["frontend_callers"]),
                        cap["health_status"],
                        scan_time,
                    ],
                )

            # Cleanup stale entries
            cur.execute(
                """
                DELETE FROM scanner_api
                WHERE project_id = %s AND last_scanned_at < %s
                """,
                [self.project_id, scan_time],
            )

            conn.commit()

        return len(capabilities)


def get_project_paths(project_id: str) -> tuple[str | None, str | None]:
    """Get root path and backend dir for a project.

    Args:
        project_id: The project ID

    Returns:
        Tuple of (root_path, backend_dir) or (None, None) if not found
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT root_path, backend_dir FROM projects WHERE id = %s",
            [project_id],
        )
        row = cur.fetchone()
        if row:
            return row[0], row[1]
    return None, None
