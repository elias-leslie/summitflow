"""Project database workbench API powered by Pgweb."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import NoReturn

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..services.db_workbench import (
    DbWorkbenchError,
    start_workbench,
    status_payload,
    status_workbench,
    stop_workbench,
    workbench_targets,
)

router = APIRouter()

_TIMEOUT = httpx.Timeout(300.0, connect=2.0)
_HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}
_STRIPPED_FRAME_HEADERS = {
    "content-security-policy",
    "content-length",
    "x-frame-options",
}
_PGWEB_DARK_STYLE = """
<style>
  :root {
    color-scheme: dark;
    --sf-pgweb-bg: #060a0f;
    --sf-pgweb-panel: #0b111a;
    --sf-pgweb-panel-2: #111925;
    --sf-pgweb-panel-3: #172235;
    --sf-pgweb-border: #263449;
    --sf-pgweb-text: #d8e1ec;
    --sf-pgweb-muted: #8794a8;
    --sf-pgweb-accent: #047857;
    --sf-pgweb-accent-hover: #0f766e;
  }
  html,
  body,
  #app,
  #body,
  #main,
  #content,
  #results,
  #input,
  #output,
  #custom_query,
  .content,
  .container,
  .container-fluid,
  .tab-content,
  .tab-pane,
  .query,
  .query-box,
  .table-container,
  .table-responsive,
  .table-information,
  .schema-table,
  .panel,
  .panel-body,
  .well,
  .actions,
  .toolbar,
  .toolbar-actions,
  .results-header,
  .results-footer,
  .alert,
  .popover,
  .dropdown-menu,
  .modal,
  .modal-content,
  .modal-header,
  .modal-body,
  .modal-footer {
    background: var(--sf-pgweb-bg) !important;
    color: var(--sf-pgweb-text) !important;
  }
  body {
    scrollbar-color: #607087 var(--sf-pgweb-panel) !important;
  }
  #nav,
  #sidebar,
  .sidebar,
  .navbar,
  .navbar-default,
  .navbar-inner,
  .list-group,
  .list-group-item {
    background: var(--sf-pgweb-panel) !important;
    color: var(--sf-pgweb-text) !important;
  }
  .current-database,
  .current-database .wrap,
  #current_database,
  .database-name,
  .connection-details {
    background: var(--sf-pgweb-panel-2) !important;
    color: #f7fbff !important;
  }
  #current_database {
    font-weight: 700 !important;
  }
  #input .actions,
  #results .actions,
  #custom_query .actions,
  .panel-heading,
  .modal-header,
  .modal-footer,
  .nav-tabs,
  .tab-header,
  .context-menu,
  .connection-actions {
    background: var(--sf-pgweb-panel-2) !important;
    border-color: var(--sf-pgweb-border) !important;
  }
  *,
  *::before,
  *::after {
    border-color: var(--sf-pgweb-border) !important;
    box-shadow: none !important;
  }
  #nav ul li,
  #nav .connection-actions a,
  #sidebar .wrap,
  #sidebar label,
  #sidebar span,
  .table-information,
  .help-block,
  .text-muted,
  .metadata,
  label,
  legend {
    color: var(--sf-pgweb-muted) !important;
  }
  #nav ul li.selected,
  #nav ul li:hover,
  #objects li:hover,
  #objects li.selected,
  .list-group-item:hover,
  .list-group-item.active,
  .nav-tabs > li.active > a,
  .nav-tabs > li.active > a:focus,
  .nav-tabs > li.active > a:hover,
  .dropdown-menu > li > a:focus,
  .dropdown-menu > li > a:hover {
    background: var(--sf-pgweb-panel-3) !important;
    color: #f7fbff !important;
  }
  #objects li,
  #objects .schema,
  #objects .table,
  #tables li,
  #schemas li,
  .tables-list li,
  .schema-name,
  .table-name {
    background: transparent !important;
    color: var(--sf-pgweb-text) !important;
  }
  #pagination,
  #pagination *,
  .pagination,
  .pagination *,
  .pager,
  .pager *,
  .filters,
  .filters *,
  #rows_filter,
  #rows_filter *,
  #table_filter,
  #table_filter *,
  .dataTables_filter,
  .dataTables_filter *,
  .dataTables_wrapper,
  .dataTables_wrapper *,
  .page-selector,
  .current-page,
  #total_records,
  .btn-group {
    background-color: var(--sf-pgweb-panel) !important;
    color: var(--sf-pgweb-text) !important;
  }
  #pagination,
  .pagination,
  .pager,
  .filters,
  #rows_filter,
  #table_filter,
  .dataTables_filter,
  .page-selector,
  .btn-group {
    border-color: var(--sf-pgweb-border) !important;
  }
  #rows_filter > span,
  #rows_filter label,
  #table_filter label,
  .dataTables_filter label,
  .current-page,
  #total_records {
    color: #cbd5e1 !important;
  }
  input,
  select,
  textarea,
  option,
  optgroup,
  pre,
  code,
  .form-control,
  .input-group-addon,
  .select2-choice,
  .select2-drop,
  .select2-results,
  .select2-search input {
    background: var(--sf-pgweb-panel) !important;
    color: #e8eef7 !important;
    border-color: var(--sf-pgweb-border) !important;
  }
  input::placeholder,
  textarea::placeholder {
    color: #6f7d91 !important;
  }
  .ace_editor,
  .ace_gutter,
  .ace_scroller,
  .ace_content,
  .ace_marker-layer,
  .ace_print-margin {
    background: var(--sf-pgweb-bg) !important;
    color: #e8eef7 !important;
  }
  .ace_gutter,
  .ace_gutter-cell {
    color: #6f7d91 !important;
  }
  .ace_active-line,
  .ace_gutter-active-line {
    background: #111b2a !important;
  }
  .ace_cursor {
    color: #f7fbff !important;
  }
  .ace-tm .ace_keyword,
  .ace-tm .ace_meta,
  .ace-tm .ace_storage,
  .ace-tm .ace_support {
    color: #93c5fd !important;
  }
  .ace-tm .ace_string,
  .ace-tm .ace_string * {
    color: #86efac !important;
  }
  .ace-tm .ace_constant,
  .ace-tm .ace_numeric,
  .ace-tm .ace_boolean {
    color: #fdba74 !important;
  }
  .ace-tm .ace_comment {
    color: #94a3b8 !important;
  }
  .ace-tm .ace_identifier,
  .ace-tm .ace_variable,
  .ace-tm .ace_entity,
  .ace-tm .ace_text {
    color: #e8eef7 !important;
  }
  .ace-tm .ace_operator,
  .ace-tm .ace_punctuation {
    color: #67e8f9 !important;
  }
  table,
  .table,
  .table > thead,
  .table > tbody,
  .table > tfoot,
  .table-striped > tbody > tr,
  .table-striped > tbody > tr:nth-of-type(odd),
  .table-hover > tbody > tr:hover,
  tr,
  td,
  th {
    background: var(--sf-pgweb-panel) !important;
    color: var(--sf-pgweb-text) !important;
  }
  .table > thead > tr > th,
  .table > tbody > tr > td,
  .table > tfoot > tr > td {
    border-color: var(--sf-pgweb-border) !important;
  }
  .btn,
  button,
  input[type="button"],
  input[type="submit"] {
    background: #121c2b !important;
    border-color: #32435c !important;
    color: var(--sf-pgweb-text) !important;
    text-shadow: none !important;
  }
  .btn:hover,
  button:hover,
  input[type="button"]:hover,
  input[type="submit"]:hover {
    background: #1a2638 !important;
    color: #f7fbff !important;
  }
  .btn-primary,
  .btn-success,
  input.btn-primary,
  input.btn-success {
    background: var(--sf-pgweb-accent) !important;
    border-color: #10b981 !important;
    color: #f7fbff !important;
  }
  .btn-primary:hover,
  .btn-success:hover,
  input.btn-primary:hover,
  input.btn-success:hover {
    background: var(--sf-pgweb-accent-hover) !important;
    border-color: #14b8a6 !important;
    color: #f7fbff !important;
  }
  .btn-danger {
    background: #8b2430 !important;
    border-color: #c24150 !important;
    color: #fff1f2 !important;
  }
  a,
  a:visited,
  .link {
    color: #70d8ff !important;
  }
  hr {
    border-color: var(--sf-pgweb-border) !important;
  }
</style>
"""


class DbWorkbenchStartRequest(BaseModel):
    readonly: bool = True


def _raise_workbench_error(exc: DbWorkbenchError) -> NoReturn:
    raise HTTPException(status_code=400, detail=str(exc)) from exc


def _response_headers(response: httpx.Response) -> dict[str, str]:
    return {
        key: value
        for key, value in response.headers.items()
        if key.lower() not in _HOP_BY_HOP_HEADERS
        and key.lower() not in _STRIPPED_FRAME_HEADERS
    }


def _request_headers(request: Request) -> dict[str, str]:
    return {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in _HOP_BY_HOP_HEADERS and key.lower() != "host"
    }


async def _stream_and_close(
    response: httpx.Response,
    client: httpx.AsyncClient,
) -> AsyncIterator[bytes]:
    try:
        async for chunk in response.aiter_bytes():
            yield chunk
    finally:
        await response.aclose()
        await client.aclose()


async def _html_response_with_base(
    response: httpx.Response,
    client: httpx.AsyncClient,
    project_id: str,
) -> Response:
    content = await response.aread()
    await response.aclose()
    await client.aclose()
    html = content.decode("utf-8", errors="replace")
    html = html.replace(
        "<head>",
        f'<head><base href="/api/projects/{project_id}/db-workbench/proxy/">',
        1,
    )
    html = html.replace("</head>", f"{_PGWEB_DARK_STYLE}</head>", 1)
    return Response(
        content=html,
        status_code=response.status_code,
        headers=_response_headers(response),
        media_type=response.headers.get("content-type"),
    )


@router.get("/db-workbench/targets")
async def get_db_workbench_targets() -> dict[str, object]:
    return {"targets": [target.__dict__ for target in workbench_targets()]}


@router.get("/{project_id}/db-workbench/status")
async def get_db_workbench_status(project_id: str) -> dict[str, object]:
    return status_payload(status_workbench(project_id))


@router.post("/{project_id}/db-workbench/start")
async def start_db_workbench(
    project_id: str,
    payload: DbWorkbenchStartRequest | None = None,
) -> dict[str, object]:
    try:
        readonly = payload.readonly if payload else True
        return status_payload(start_workbench(project_id, readonly=readonly))
    except DbWorkbenchError as exc:
        _raise_workbench_error(exc)


@router.post("/{project_id}/db-workbench/stop")
async def stop_db_workbench(project_id: str) -> dict[str, object]:
    return status_payload(stop_workbench(project_id))


@router.api_route(
    "/{project_id}/db-workbench/proxy",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
@router.api_route(
    "/{project_id}/db-workbench/proxy/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
@router.api_route(
    "/{project_id}/db-workbench/static/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
@router.api_route(
    "/{project_id}/db-workbench/api/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
@router.api_route(
    "/{project_id}/db-workbench/proxyapi/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_db_workbench(
    project_id: str,
    request: Request,
    path: str = "",
) -> Response:
    status = status_workbench(project_id)
    if not status.running or not status.direct_url:
        raise HTTPException(status_code=503, detail="Pgweb workbench is not running")

    route_path = request.url.path
    if f"/projects/{project_id}/db-workbench/static/" in route_path:
        path = f"static/{path}"
    elif (
        f"/projects/{project_id}/db-workbench/proxyapi/" in route_path
        or f"/projects/{project_id}/db-workbench/api/" in route_path
    ):
        path = f"api/{path}"

    base_url = status.direct_url.rstrip("/")
    upstream_url = f"{base_url}/{path.lstrip('/')}"
    if request.url.query:
        upstream_url = f"{upstream_url}?{request.url.query}"

    client = httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False)
    try:
        upstream_request = client.build_request(
            request.method,
            upstream_url,
            headers=_request_headers(request),
            content=await request.body(),
        )
        upstream_response = await client.send(upstream_request, stream=True)
    except httpx.RequestError as exc:
        await client.aclose()
        raise HTTPException(status_code=502, detail=f"Pgweb proxy unavailable: {exc}") from exc

    if (
        request.method == "GET"
        and path in {"", "."}
        and "text/html" in upstream_response.headers.get("content-type", "")
    ):
        return await _html_response_with_base(upstream_response, client, project_id)

    return StreamingResponse(
        _stream_and_close(upstream_response, client),
        status_code=upstream_response.status_code,
        headers=_response_headers(upstream_response),
        media_type=upstream_response.headers.get("content-type"),
    )
