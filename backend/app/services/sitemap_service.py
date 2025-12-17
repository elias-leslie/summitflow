"""Sitemap Service - Discovery and health monitoring for project endpoints.

This module provides:
- Discovery of backend API endpoints (via OpenAPI)
- Discovery of frontend pages (via HTTP probing)
- Health checks (HTTP status, response time)
- CRUD operations for sitemap entries
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from ..storage.connection import get_connection

# Configuration
HTTP_TIMEOUT = 10  # seconds
HEALTH_CHECK_TIMEOUT = 10  # seconds


@dataclass
class Project:
    """Project configuration for sitemap discovery."""

    id: str
    name: str
    base_url: str
    frontend_port: int
    backend_port: int


class SitemapService:
    """Discovers and monitors sitemap entries for a project."""

    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        self._project: Project | None = None

    @property
    def project(self) -> Project:
        """Get project configuration (cached)."""
        if self._project is None:
            self._project = self._load_project()
        return self._project

    def _load_project(self) -> Project:
        """Load project from database."""
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, name, base_url, frontend_port, backend_port
                    FROM projects WHERE id = %s
                    """,
                    (self.project_id,),
                )
                row = cur.fetchone()
                if not row:
                    raise ValueError(f"Project {self.project_id} not found")
                return Project(
                    id=row[0],
                    name=row[1],
                    base_url=row[2],
                    frontend_port=row[3] or 3000,
                    backend_port=row[4] or 8000,
                )

    def _get_host(self) -> str:
        """Extract host from project base_url."""
        # base_url is like "http://192.168.8.233:8000" or "http://localhost:8000"
        url = self.project.base_url
        # Remove protocol
        if "://" in url:
            url = url.split("://")[1]
        # Remove port if present
        if ":" in url:
            url = url.split(":")[0]
        return url

    # =========================================================================
    # Discovery Methods
    # =========================================================================

    async def discover_backend_endpoints(self) -> list[dict[str, Any]]:
        """Parse /openapi.json to discover backend API endpoints."""
        discovered = []
        host = self._get_host()
        port = self.project.backend_port

        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                response = await client.get(f"http://{host}:{port}/openapi.json")
                response.raise_for_status()
                openapi = response.json()

            paths = openapi.get("paths", {})
            for path, methods in paths.items():
                for method, details in methods.items():
                    if method.upper() in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                        # Skip health/docs endpoints
                        if any(x in path for x in ["/health", "/docs", "/openapi", "/redoc"]):
                            continue

                        discovered.append({
                            "port": port,
                            "path": path,
                            "method": method.upper(),
                            "entry_type": "api_endpoint",
                            "source": "openapi",
                            "title": details.get("summary") or details.get("operationId"),
                        })

        except Exception as e:
            print(f"Backend discovery failed: {e}")

        return discovered

    async def discover_frontend_pages(self) -> list[dict[str, Any]]:
        """Discover frontend pages by probing common routes."""
        discovered = []
        host = self._get_host()
        port = self.project.frontend_port

        # Common routes to probe
        common_routes = [
            "/",
            "/dashboard",
            "/watchlist",
            "/portfolio",
            "/ideas",
            "/status",
            "/capabilities",
            "/settings",
        ]

        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            for route in common_routes:
                try:
                    url = f"http://{host}:{port}{route}"
                    response = await client.get(url, follow_redirects=True)
                    if response.status_code == 200:
                        discovered.append({
                            "port": port,
                            "path": route,
                            "method": "GET",
                            "entry_type": "frontend_page",
                            "source": "probe",
                            "title": route.strip("/").title() or "Home",
                        })
                except Exception:
                    pass  # Route doesn't exist

        return discovered

    async def run_discovery(self) -> dict[str, Any]:
        """Run comprehensive discovery for the project."""
        # Run discoveries in parallel
        backend_task = asyncio.create_task(self.discover_backend_endpoints())
        frontend_task = asyncio.create_task(self.discover_frontend_pages())

        backend_entries = await backend_task
        frontend_entries = await frontend_task

        # Combine all entries
        all_entries = backend_entries + frontend_entries
        saved = 0

        with get_connection() as conn:
            with conn.cursor() as cur:
                for entry in all_entries:
                    try:
                        cur.execute(
                            """
                            INSERT INTO sitemap_entries
                                (project_id, port, path, method, entry_type, source, title, discovered_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                            ON CONFLICT (project_id, port, path, method) DO UPDATE SET
                                title = COALESCE(EXCLUDED.title, sitemap_entries.title),
                                source = EXCLUDED.source,
                                updated_at = NOW()
                            """,
                            (
                                self.project_id,
                                entry["port"],
                                entry["path"],
                                entry["method"],
                                entry["entry_type"],
                                entry["source"],
                                entry.get("title"),
                            ),
                        )
                        saved += 1
                    except Exception as e:
                        print(f"Failed to save entry {entry['path']}: {e}")

                conn.commit()

        return {
            "backend_discovered": len(backend_entries),
            "frontend_discovered": len(frontend_entries),
            "total_saved": saved,
        }

    # =========================================================================
    # Health Check Methods
    # =========================================================================

    async def check_entry_health(self, entry_id: int) -> dict[str, Any]:
        """Check health of a single sitemap entry."""
        entry = self.get_entry(entry_id)
        if not entry:
            return {"success": False, "error": "Entry not found"}

        port = entry["port"]
        path = entry["path"]
        method = entry["method"]

        # Build URL - substitute path parameters with test values
        test_path = path
        if "{" in path:
            test_path = re.sub(r"\{[^}]+\}", "test-value", path)

        host = self._get_host()
        url = f"http://{host}:{port}{test_path}"

        http_status = None
        response_time_ms = None
        health_status = "unknown"
        error_message = None

        # Skip mutating methods
        if method in ("POST", "PUT", "DELETE", "PATCH"):
            health_status = "healthy"
            http_status = 0  # Indicates skipped
            error_message = "Skipped (mutating method)"
        else:
            try:
                async with httpx.AsyncClient(timeout=HEALTH_CHECK_TIMEOUT) as client:
                    start = datetime.now(UTC)
                    response = await client.get(url)
                    elapsed = (datetime.now(UTC) - start).total_seconds() * 1000

                    http_status = response.status_code
                    response_time_ms = int(elapsed)

                    if response.status_code < 400:
                        health_status = "healthy"
                    elif response.status_code < 500:
                        health_status = "warning"
                    else:
                        health_status = "error"

            except httpx.TimeoutException:
                health_status = "error"
                error_message = "Timeout"
            except Exception as e:
                health_status = "error"
                error_message = str(e)

        # Update entry
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE sitemap_entries SET
                        health_status = %s,
                        http_status = %s,
                        response_time_ms = %s,
                        last_error_message = %s,
                        last_checked_at = NOW(),
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (health_status, http_status, response_time_ms, error_message, entry_id),
                )

                # Record history
                cur.execute(
                    """
                    INSERT INTO sitemap_health_history
                        (sitemap_entry_id, checked_at, health_status, http_status, response_time_ms)
                    VALUES (%s, NOW(), %s, %s, %s)
                    """,
                    (entry_id, health_status, http_status, response_time_ms),
                )

                conn.commit()

        return {
            "success": True,
            "entry_id": entry_id,
            "health_status": health_status,
            "http_status": http_status,
            "response_time_ms": response_time_ms,
            "error": error_message,
        }

    async def check_all_health(self) -> dict[str, Any]:
        """Check health of all entries for this project."""
        entries, _ = self.get_entries(limit=500)
        results = {"checked": 0, "healthy": 0, "warning": 0, "error": 0}

        for entry in entries:
            result = await self.check_entry_health(entry["id"])
            results["checked"] += 1
            if result.get("health_status") == "healthy":
                results["healthy"] += 1
            elif result.get("health_status") == "warning":
                results["warning"] += 1
            else:
                results["error"] += 1

        return results

    # =========================================================================
    # CRUD Methods
    # =========================================================================

    def get_entries(
        self,
        port: int | None = None,
        health_status: str | None = None,
        entry_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """Get sitemap entries with filters."""
        conditions = ["project_id = %s"]
        params: list[Any] = [self.project_id]

        if port is not None:
            conditions.append("port = %s")
            params.append(port)
        if health_status:
            conditions.append("health_status = %s")
            params.append(health_status)
        if entry_type:
            conditions.append("entry_type = %s")
            params.append(entry_type)

        where_clause = " AND ".join(conditions)

        with get_connection() as conn:
            with conn.cursor() as cur:
                # Get total count
                cur.execute(
                    f"SELECT COUNT(*) FROM sitemap_entries WHERE {where_clause}",
                    params,
                )
                total = cur.fetchone()[0]

                # Get entries
                cur.execute(
                    f"""
                    SELECT id, port, path, method, entry_type, source, title, parent_path,
                           health_status, console_errors, console_warnings, http_status,
                           response_time_ms, last_error_message, last_checked_at, discovered_at
                    FROM sitemap_entries
                    WHERE {where_clause}
                    ORDER BY port, path
                    LIMIT %s OFFSET %s
                    """,
                    [*params, limit, offset],
                )

                entries = []
                for row in cur.fetchall():
                    entries.append({
                        "id": row[0],
                        "port": row[1],
                        "path": row[2],
                        "method": row[3],
                        "entry_type": row[4],
                        "source": row[5],
                        "title": row[6],
                        "parent_path": row[7],
                        "health_status": row[8],
                        "console_errors": row[9],
                        "console_warnings": row[10],
                        "http_status": row[11],
                        "response_time_ms": row[12],
                        "last_error_message": row[13],
                        "last_checked_at": row[14].isoformat() if row[14] else None,
                        "discovered_at": row[15].isoformat() if row[15] else None,
                    })

                return entries, total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        """Get single entry by ID."""
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, port, path, method, entry_type, source, title, parent_path,
                           health_status, console_errors, console_warnings, http_status,
                           response_time_ms, last_error_message, last_checked_at, discovered_at
                    FROM sitemap_entries
                    WHERE id = %s AND project_id = %s
                    """,
                    (entry_id, self.project_id),
                )

                row = cur.fetchone()
                if not row:
                    return None

                return {
                    "id": row[0],
                    "port": row[1],
                    "path": row[2],
                    "method": row[3],
                    "entry_type": row[4],
                    "source": row[5],
                    "title": row[6],
                    "parent_path": row[7],
                    "health_status": row[8],
                    "console_errors": row[9],
                    "console_warnings": row[10],
                    "http_status": row[11],
                    "response_time_ms": row[12],
                    "last_error_message": row[13],
                    "last_checked_at": row[14].isoformat() if row[14] else None,
                    "discovered_at": row[15].isoformat() if row[15] else None,
                }

    def get_health_summary(self) -> dict[str, Any]:
        """Get aggregate health statistics."""
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        COUNT(*) as total,
                        COUNT(*) FILTER (WHERE health_status = 'healthy') as healthy,
                        COUNT(*) FILTER (WHERE health_status = 'warning') as warning,
                        COUNT(*) FILTER (WHERE health_status = 'error') as error,
                        COUNT(*) FILTER (WHERE health_status = 'unknown' OR health_status IS NULL) as unknown
                    FROM sitemap_entries
                    WHERE project_id = %s
                    """,
                    (self.project_id,),
                )
                row = cur.fetchone()

                # Get counts by port
                cur.execute(
                    """
                    SELECT port,
                        COUNT(*) FILTER (WHERE health_status = 'healthy') as healthy,
                        COUNT(*) FILTER (WHERE health_status = 'warning') as warning,
                        COUNT(*) FILTER (WHERE health_status = 'error') as error,
                        COUNT(*) FILTER (WHERE health_status = 'unknown' OR health_status IS NULL) as unknown
                    FROM sitemap_entries
                    WHERE project_id = %s
                    GROUP BY port
                    """,
                    (self.project_id,),
                )

                by_port = {}
                for port_row in cur.fetchall():
                    by_port[str(port_row[0])] = {
                        "healthy": port_row[1],
                        "warning": port_row[2],
                        "error": port_row[3],
                        "unknown": port_row[4],
                    }

                return {
                    "total": row[0],
                    "healthy": row[1],
                    "warning": row[2],
                    "error": row[3],
                    "unknown": row[4],
                    "by_port": by_port,
                }

    def register_entry(
        self,
        port: int,
        path: str,
        method: str = "GET",
        entry_type: str = "manual",
        title: str | None = None,
    ) -> dict[str, Any]:
        """Manually register a new sitemap entry."""
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO sitemap_entries (project_id, port, path, method, entry_type, source, title)
                    VALUES (%s, %s, %s, %s, %s, 'manual', %s)
                    RETURNING id
                    """,
                    (self.project_id, port, path, method, entry_type, title),
                )
                entry_id = cur.fetchone()[0]
                conn.commit()

        return self.get_entry(entry_id)  # type: ignore

    def delete_entry(self, entry_id: int) -> bool:
        """Remove a sitemap entry."""
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM sitemap_entries WHERE id = %s AND project_id = %s RETURNING id",
                    (entry_id, self.project_id),
                )
                deleted = cur.fetchone() is not None
                conn.commit()
                return deleted

    # =========================================================================
    # Maintenance
    # =========================================================================

    def cleanup_old_history(self, days: int = 7) -> int:
        """Delete health history older than specified days."""
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM sitemap_health_history
                    WHERE sitemap_entry_id IN (
                        SELECT id FROM sitemap_entries WHERE project_id = %s
                    )
                    AND checked_at < NOW() - INTERVAL '%s days'
                    RETURNING id
                    """,
                    (self.project_id, days),
                )
                deleted = len(cur.fetchall())
                conn.commit()

        return deleted

    def get_history_stats(self) -> dict[str, Any]:
        """Get health history statistics."""
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        COUNT(*) as total_rows,
                        MIN(checked_at) as oldest_entry
                    FROM sitemap_health_history
                    WHERE sitemap_entry_id IN (
                        SELECT id FROM sitemap_entries WHERE project_id = %s
                    )
                    """,
                    (self.project_id,),
                )
                row = cur.fetchone()

                return {
                    "total_rows": row[0],
                    "oldest_entry": row[1].isoformat() if row[1] else None,
                }
