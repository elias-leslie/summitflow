"""Graphify project graph endpoints."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

from ..services.graphify_tools import (
    GraphifyCommandResult,
    explain_graph,
    graphify_dir,
    graphify_status,
    path_graph,
    query_graph,
    refresh_graph,
)
from .projects.db_helpers import get_project_from_db

router = APIRouter()


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
    code_node_count: int = 0
    rationale_node_count: int = 0
    semantic_node_count: int = 0
    file_type_counts: dict[str, int] = Field(default_factory=dict)
    detected_source_counts: dict[str, int] = Field(default_factory=dict)
    semantic_source_count: int = 0
    semantic_coverage: str = "code_only"
    graph_stale: bool = False
    changed_files_since_graph: int = 0
    changed_files_sample: list[str] = Field(default_factory=list)
    graph_size_bytes: int = 0
    html_size_bytes: int = 0
    report_size_bytes: int = 0
    html_uses_cdn: bool = False
    diagnostics: list[str] = Field(default_factory=list)
    unreadable_error: str | None = None


class GraphifyUpdateResponse(GraphifyStatusResponse):
    """Graphify update response."""

    output: str


class GraphifyCommandResponse(BaseModel):
    """Measured Graphify command response."""

    command: list[str]
    output: str
    elapsed_ms: int
    output_chars: int
    estimated_tokens: int


class GraphifyQueryRequest(BaseModel):
    """Graphify query request."""

    question: str
    budget: int = Field(default=1200, ge=100, le=8000)
    dfs: bool = False


class GraphifyPathRequest(BaseModel):
    """Graphify path request."""

    source: str
    target: str


class GraphifyExplainRequest(BaseModel):
    """Graphify explain request."""

    node: str


def _project_root(project_id: str) -> Path:
    project = get_project_from_db(project_id)
    if not project.root_path:
        raise HTTPException(status_code=404, detail="Project has no root_path")
    root = Path(project.root_path).resolve()
    if not root.exists() or not root.is_dir():
        raise HTTPException(status_code=404, detail="Project root not found")
    return root


def _build_status(project_id: str, root: Path) -> GraphifyStatusResponse:
    return GraphifyStatusResponse(**graphify_status(project_id, root))


def _command_response(result: GraphifyCommandResult) -> GraphifyCommandResponse:
    return GraphifyCommandResponse(**asdict(result))


def _command_error(exc: Exception) -> HTTPException:
    status_code = 500 if isinstance(exc, FileNotFoundError) else 502
    return HTTPException(status_code=status_code, detail=str(exc))


@router.get("/{project_id}/graphify/status", response_model=GraphifyStatusResponse)
async def get_graphify_status(project_id: str) -> GraphifyStatusResponse:
    """Return Graphify output status for a project."""
    root = _project_root(project_id)
    return _build_status(project_id, root)


@router.get("/{project_id}/graphify/html")
async def get_graphify_html(project_id: str) -> FileResponse:
    """Serve Graphify's generated HTML visualization."""
    root = _project_root(project_id)
    graph_html = graphify_dir(root) / "graph.html"
    if not graph_html.exists():
        raise HTTPException(status_code=404, detail="Graphify HTML not found")
    return FileResponse(graph_html, media_type="text/html")


@router.get("/{project_id}/graphify/report")
async def get_graphify_report(project_id: str) -> PlainTextResponse:
    """Serve Graphify's generated report."""
    root = _project_root(project_id)
    report = graphify_dir(root) / "GRAPH_REPORT.md"
    if not report.exists():
        raise HTTPException(status_code=404, detail="Graphify report not found")
    return PlainTextResponse(report.read_text(encoding="utf-8"))


@router.post("/{project_id}/graphify/update", response_model=GraphifyUpdateResponse)
async def update_graphify(project_id: str) -> GraphifyUpdateResponse:
    """Refresh Graphify's code graph using AST-only update."""
    root = _project_root(project_id)
    try:
        result = refresh_graph(root)
    except (FileNotFoundError, RuntimeError) as exc:
        raise _command_error(exc) from exc
    status = _build_status(project_id, root)
    return GraphifyUpdateResponse(**status.model_dump(), output=result.output)


@router.post("/{project_id}/graphify/query", response_model=GraphifyCommandResponse)
async def run_graphify_query(project_id: str, request: GraphifyQueryRequest) -> GraphifyCommandResponse:
    """Run Graphify query against a project graph."""
    root = _project_root(project_id)
    try:
        return _command_response(query_graph(root, request.question, budget=request.budget, dfs=request.dfs))
    except (FileNotFoundError, RuntimeError) as exc:
        raise _command_error(exc) from exc


@router.post("/{project_id}/graphify/path", response_model=GraphifyCommandResponse)
async def run_graphify_path(project_id: str, request: GraphifyPathRequest) -> GraphifyCommandResponse:
    """Run Graphify path against a project graph."""
    root = _project_root(project_id)
    try:
        return _command_response(path_graph(root, request.source, request.target))
    except (FileNotFoundError, RuntimeError) as exc:
        raise _command_error(exc) from exc


@router.post("/{project_id}/graphify/explain", response_model=GraphifyCommandResponse)
async def run_graphify_explain(project_id: str, request: GraphifyExplainRequest) -> GraphifyCommandResponse:
    """Run Graphify explain against a project graph."""
    root = _project_root(project_id)
    try:
        return _command_response(explain_graph(root, request.node))
    except (FileNotFoundError, RuntimeError) as exc:
        raise _command_error(exc) from exc
