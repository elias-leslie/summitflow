"""Agent Hub bootstrap helpers for SummitFlow project registration."""

from __future__ import annotations

import inspect

import httpx
from fastapi import HTTPException

from ...config import AGENT_HUB_URL
from ...services._agent_hub_config import build_agent_hub_headers
from .models import ProjectPermissionBootstrap

_SOURCE_CLIENT = "summitflow"
_SOURCE_PATH_HEADER = "X-Source-Path"
_SOURCE_CLIENT_HEADER = "X-Source-Client"
_REQUEST_SOURCE = "summitflow-project-bootstrap"
_TIMEOUT_SECONDS = 10.0


def _build_headers() -> dict[str, str]:
    """Build standard Agent Hub headers with SummitFlow source metadata."""
    frame = inspect.currentframe()
    source_path = __file__
    if frame is not None and frame.f_code.co_filename:
        source_path = frame.f_code.co_filename
    return build_agent_hub_headers(
        request_source=_REQUEST_SOURCE,
        extra_headers={
            _SOURCE_CLIENT_HEADER: _SOURCE_CLIENT,
            _SOURCE_PATH_HEADER: source_path,
        },
    )


def _extract_error_detail(response: httpx.Response) -> str:
    """Return the best available API error detail."""
    try:
        payload = response.json()
    except ValueError:
        return response.text or response.reason_phrase
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if isinstance(detail, str) and detail:
        return detail
    return response.text or response.reason_phrase


def _build_permission_payload(
    project_id: str,
    permission: ProjectPermissionBootstrap,
    root_path: str | None,
) -> dict[str, object]:
    """Build the Agent Hub permission payload for a project."""
    effective_root_path = permission.root_path or root_path
    payload: dict[str, object] = {
        "project_id": project_id,
        "permission_tier": permission.permission_tier,
        "auto_exec_enabled": permission.auto_exec_enabled,
        "execution_start_hour": permission.execution_start_hour,
        "execution_end_hour": permission.execution_end_hour,
        "budget_alert_threshold": permission.budget_alert_threshold,
    }
    if effective_root_path is not None:
        payload["root_path"] = effective_root_path
    if permission.daily_cost_budget_usd is not None:
        payload["daily_cost_budget_usd"] = permission.daily_cost_budget_usd
    if permission.monthly_cost_budget_usd is not None:
        payload["monthly_cost_budget_usd"] = permission.monthly_cost_budget_usd
    return payload


async def sync_agent_hub_project_permission(
    project_id: str,
    permission: ProjectPermissionBootstrap,
    root_path: str | None,
) -> None:
    """Create or update the matching Agent Hub project permission row."""
    payload = _build_permission_payload(project_id, permission, root_path)
    headers = _build_headers()
    create_url = f"{AGENT_HUB_URL}/api/projects/permissions"
    update_url = f"{AGENT_HUB_URL}/api/projects/{project_id}/permissions"

    async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS, headers=headers) as client:
        response = await client.post(create_url, json=payload)
        if response.status_code in {200, 201}:
            return
        if response.status_code == 409:
            update_payload = {k: v for k, v in payload.items() if k != "project_id"}
            response = await client.patch(update_url, json=update_payload)
            if response.status_code in {200, 201}:
                return

    detail = _extract_error_detail(response)
    raise HTTPException(
        status_code=502,
        detail=f"Failed to sync Agent Hub permission for project '{project_id}': {detail}",
    )


async def delete_agent_hub_project_permission(project_id: str) -> None:
    """Delete the matching Agent Hub project permission row if it exists."""
    headers = _build_headers()
    delete_url = f"{AGENT_HUB_URL}/api/projects/{project_id}/permissions"

    async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS, headers=headers) as client:
        response = await client.delete(delete_url)
        if response.status_code in {200, 204, 404}:
            return

    detail = _extract_error_detail(response)
    raise HTTPException(
        status_code=502,
        detail=f"Failed to delete Agent Hub permission for project '{project_id}': {detail}",
    )
