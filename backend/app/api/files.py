"""Files API - Proxy to project file audit endpoints.

Endpoints:
- GET /api/projects/{project_id}/files - List files with filters
- GET /api/projects/{project_id}/files/summary - Get file statistics
- GET /api/projects/{project_id}/files/tree - Get hierarchical tree
- GET /api/projects/{project_id}/files/children - Get folder contents
- GET /api/projects/{project_id}/files/history - Get git history for file
- POST /api/projects/{project_id}/files/scan - Trigger file scan
"""

from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query

from ..storage.connection import get_connection

router = APIRouter()

HTTP_TIMEOUT = 30  # File scanning can be slow


def _get_project_backend(project_id: str) -> str:
    """Get project backend URL from database."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT base_url, backend_port
                FROM projects WHERE id = %s
                """,
                (project_id,),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError(f"Project {project_id} not found")

            base_url = row[0]
            backend_port = row[1] or 8000

            # Extract host from base_url
            if "://" in base_url:
                host = base_url.split("://")[1]
            else:
                host = base_url
            if ":" in host:
                host = host.split(":")[0]

            return f"http://{host}:{backend_port}"


async def _proxy_get(project_id: str, path: str, params: dict | None = None) -> Any:
    """Proxy GET request to project backend."""
    try:
        backend_url = _get_project_backend(project_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    url = f"{backend_url}{path}"

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Project backend timeout")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=str(e))
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Cannot reach project backend: {e}")


async def _proxy_post(project_id: str, path: str) -> Any:
    """Proxy POST request to project backend."""
    try:
        backend_url = _get_project_backend(project_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    url = f"{backend_url}{path}"

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            response = await client.post(url)
            response.raise_for_status()
            return response.json()
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Project backend timeout")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=str(e))
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Cannot reach project backend: {e}")


# =========================================================================
# Endpoints
# =========================================================================


@router.get("/{project_id}/files")
async def list_files(
    project_id: str,
    path: str | None = Query(None, description="Filter by path prefix"),
    extension: str | None = Query(None, description="Filter by extension (e.g., .py)"),
    bloat: str | None = Query(None, description="Filter by bloat level (warning, critical)"),
    stale: str | None = Query(None, description="Filter by stale status (fresh, stale, orphan)"),
    is_directory: bool | None = Query(None, description="Filter files or directories"),
    sort: str = Query("path", description="Sort by: path, lines_of_code, size_bytes, last_commit_days, reference_count"),
    dir: str = Query("asc", description="Sort direction: asc, desc"),
    limit: int = Query(100, ge=1, le=500, description="Results per page"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
) -> dict:
    """List files with filtering, sorting, and pagination."""
    params = {
        "sort": sort,
        "dir": dir,
        "limit": limit,
        "offset": offset,
    }
    if path:
        params["path"] = path
    if extension:
        params["extension"] = extension
    if bloat:
        params["bloat"] = bloat
    if stale:
        params["stale"] = stale
    if is_directory is not None:
        params["is_directory"] = str(is_directory).lower()

    return await _proxy_get(project_id, "/api/files", params)


@router.get("/{project_id}/files/summary")
async def get_summary(project_id: str) -> dict:
    """Get aggregate statistics from file audit."""
    return await _proxy_get(project_id, "/api/files/summary")


@router.get("/{project_id}/files/tree")
async def get_tree(
    project_id: str,
    path: str = Query("", description="Path prefix to filter tree"),
    depth: int | None = Query(None, description="Set to 1 for lazy loading"),
) -> list:
    """Get hierarchical tree structure for UI."""
    params = {"path": path}
    if depth is not None:
        params["depth"] = depth
    return await _proxy_get(project_id, "/api/files/tree", params)


@router.get("/{project_id}/files/children")
async def get_children(
    project_id: str,
    path: str = Query("", description="Parent path (empty for root)"),
    sort: str = Query("name", description="Sort by: name, loc, size, modified, files"),
    dir: str = Query("asc", description="Sort direction: asc, desc"),
    folders_first: bool = Query(True, description="Show folders before files"),
    include_files: bool = Query(True, description="Include files in response"),
) -> list:
    """Get immediate children (folders and files) for explorer view."""
    params = {
        "path": path,
        "sort": sort,
        "dir": dir,
        "folders_first": str(folders_first).lower(),
        "include_files": str(include_files).lower(),
    }
    return await _proxy_get(project_id, "/api/files/children", params)


@router.get("/{project_id}/files/history")
async def get_file_history(
    project_id: str,
    path: str = Query(..., description="File path relative to project root"),
    limit: int = Query(10, ge=1, le=50, description="Number of commits to return"),
) -> dict:
    """Get git commit history for a specific file."""
    params = {"path": path, "limit": limit}
    return await _proxy_get(project_id, "/api/files/history", params)


@router.post("/{project_id}/files/scan")
async def trigger_scan(project_id: str) -> dict:
    """Trigger a file scan. Runs in background on project backend."""
    return await _proxy_post(project_id, "/api/files/scan")
