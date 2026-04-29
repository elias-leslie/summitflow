"""Graphify project graph endpoints."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from .projects.db_helpers import get_project_from_db

router = APIRouter()

_GRAPHIFY_TIMEOUT_SECONDS = 180
_DEFAULT_GRAPHIFY_BIN = Path.home() / ".local" / "bin" / "graphify"


class GraphifyStatusResponse(BaseModel):
    """Graphify output status for a project."""

    project_id: str
    root_path: str
    graph_exists: bool
    html_available: bool
    report_available: bool
    node_count: int
    edge_count: int
    community_count: int
    graph_updated_at: datetime | None
    html_updated_at: datetime | None
    report_updated_at: datetime | None
    html_url: str | None
    report_url: str | None


class GraphifyUpdateResponse(GraphifyStatusResponse):
    """Graphify update response."""

    output: str


def _project_root(project_id: str) -> Path:
    project = get_project_from_db(project_id)
    if not project.root_path:
        raise HTTPException(status_code=404, detail="Project has no root_path")
    root = Path(project.root_path).resolve()
    if not root.exists() or not root.is_dir():
        raise HTTPException(status_code=404, detail="Project root not found")
    return root


def _graphify_dir(root: Path) -> Path:
    return root / "graphify-out"


def _mtime(path: Path) -> datetime | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, UTC)


def _graph_counts(graph_json: Path) -> tuple[int, int, int]:
    if not graph_json.exists():
        return 0, 0, 0
    try:
        data = json.loads(graph_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"Graphify graph unreadable: {exc}") from exc

    nodes = data.get("nodes", [])
    links = data.get("links", data.get("edges", []))
    communities = {
        node.get("community")
        for node in nodes
        if isinstance(node, dict) and node.get("community") is not None
    }
    return len(nodes), len(links), len(communities)


def _build_status(project_id: str, root: Path) -> GraphifyStatusResponse:
    out = _graphify_dir(root)
    graph_json = out / "graph.json"
    graph_html = out / "graph.html"
    report = out / "GRAPH_REPORT.md"
    node_count, edge_count, community_count = _graph_counts(graph_json)
    return GraphifyStatusResponse(
        project_id=project_id,
        root_path=str(root),
        graph_exists=graph_json.exists(),
        html_available=graph_html.exists(),
        report_available=report.exists(),
        node_count=node_count,
        edge_count=edge_count,
        community_count=community_count,
        graph_updated_at=_mtime(graph_json),
        html_updated_at=_mtime(graph_html),
        report_updated_at=_mtime(report),
        html_url=f"/api/projects/{project_id}/graphify/html" if graph_html.exists() else None,
        report_url=f"/api/projects/{project_id}/graphify/report" if report.exists() else None,
    )


def _graphify_bin() -> str:
    configured = os.getenv("GRAPHIFY_BIN")
    if configured:
        return configured
    found = shutil.which("graphify")
    if found:
        return found
    if _DEFAULT_GRAPHIFY_BIN.exists():
        return str(_DEFAULT_GRAPHIFY_BIN)
    raise HTTPException(status_code=500, detail="graphify executable not found")


@router.get("/{project_id}/graphify/status", response_model=GraphifyStatusResponse)
async def get_graphify_status(project_id: str) -> GraphifyStatusResponse:
    """Return Graphify output status for a project."""
    root = _project_root(project_id)
    return _build_status(project_id, root)


@router.get("/{project_id}/graphify/html")
async def get_graphify_html(project_id: str) -> FileResponse:
    """Serve Graphify's generated HTML visualization."""
    root = _project_root(project_id)
    graph_html = _graphify_dir(root) / "graph.html"
    if not graph_html.exists():
        raise HTTPException(status_code=404, detail="Graphify HTML not found")
    return FileResponse(graph_html, media_type="text/html")


@router.get("/{project_id}/graphify/report")
async def get_graphify_report(project_id: str) -> PlainTextResponse:
    """Serve Graphify's generated report."""
    root = _project_root(project_id)
    report = _graphify_dir(root) / "GRAPH_REPORT.md"
    if not report.exists():
        raise HTTPException(status_code=404, detail="Graphify report not found")
    return PlainTextResponse(report.read_text(encoding="utf-8"))


@router.post("/{project_id}/graphify/update", response_model=GraphifyUpdateResponse)
async def update_graphify(project_id: str) -> GraphifyUpdateResponse:
    """Refresh Graphify's code graph using AST-only update."""
    root = _project_root(project_id)
    command = [_graphify_bin(), "update", str(root)]
    result = await asyncio.to_thread(
        subprocess.run,
        command,
        cwd=root,
        text=True,
        capture_output=True,
        timeout=_GRAPHIFY_TIMEOUT_SECONDS,
        check=False,
    )
    raw_stdout = result.stdout or ""
    raw_stderr = result.stderr or ""
    stdout = raw_stdout if isinstance(raw_stdout, str) else raw_stdout.decode()
    stderr = raw_stderr if isinstance(raw_stderr, str) else raw_stderr.decode()
    output = "\n".join(part for part in (stdout.strip(), stderr.strip()) if part)
    if result.returncode != 0:
        detail: dict[str, Any] = {
            "message": "Graphify update failed",
            "output": output[-4000:],
        }
        raise HTTPException(status_code=500, detail=detail)
    status = _build_status(project_id, root)
    return GraphifyUpdateResponse(**status.model_dump(), output=output)
