"""Agent Hub bootstrap helpers for SummitFlow project registration."""

from __future__ import annotations

import inspect
from collections.abc import Iterable
from typing import Any

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


def _dedupe_project_ids(values: Iterable[str]) -> list[str]:
    """Return project ids in first-seen order without blanks."""
    ordered: list[str] = []
    for value in values:
        project_id = value.strip()
        if project_id and project_id not in ordered:
            ordered.append(project_id)
    return ordered


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


def _coerce_permission_bootstrap(
    payload: dict[str, Any],
    *,
    root_path: str | None,
) -> ProjectPermissionBootstrap:
    """Convert an Agent Hub permission response into a bootstrap payload."""
    return ProjectPermissionBootstrap(
        permission_tier=str(payload["permission_tier"]),
        auto_exec_enabled=bool(payload["auto_exec_enabled"]),
        execution_start_hour=int(payload["execution_start_hour"]),
        execution_end_hour=int(payload["execution_end_hour"]),
        root_path=root_path or payload.get("root_path"),
        daily_cost_budget_usd=payload.get("daily_cost_budget_usd"),
        monthly_cost_budget_usd=payload.get("monthly_cost_budget_usd"),
        budget_alert_threshold=float(payload.get("budget_alert_threshold", 0.8)),
    )


def _choose_permission_payload(
    payloads: list[dict[str, Any]],
    *,
    requested_project_id: str,
    canonical_project_id: str,
) -> dict[str, Any]:
    """Prefer canonical permission state when present, otherwise requested or first."""
    payload_by_id = {
        str(payload.get("project_id") or ""): payload
        for payload in payloads
        if isinstance(payload, dict)
    }
    return (
        payload_by_id.get(canonical_project_id)
        or payload_by_id.get(requested_project_id)
        or payloads[0]
    )


async def _fetch_agent_hub_project_permission(project_id: str) -> dict[str, Any] | None:
    """Fetch one Agent Hub project permission row, returning None when absent."""
    headers = _build_headers()
    url = f"{AGENT_HUB_URL}/api/projects/{project_id}/permissions"
    async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS, headers=headers) as client:
        response = await client.get(url)
    if response.status_code == 404:
        return None
    if response.status_code >= 400:
        detail = _extract_error_detail(response)
        raise HTTPException(
            status_code=502,
            detail=(
                f"Failed to fetch Agent Hub permission for project '{project_id}': {detail}"
            ),
        )
    payload = response.json()
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=502,
            detail=(
                f"Failed to fetch Agent Hub permission for project '{project_id}': "
                "unexpected response payload"
            ),
        )
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


async def reconcile_agent_hub_project_identity(
    *,
    requested_project_id: str,
    canonical_project_id: str,
    aliases: Iterable[str],
    root_path: str | None,
) -> None:
    """Reconcile legacy Agent Hub permission ids onto the canonical project id."""
    project_ids = _dedupe_project_ids([canonical_project_id, requested_project_id, *aliases])
    payloads: list[dict[str, Any]] = []
    for project_id in project_ids:
        payload = await _fetch_agent_hub_project_permission(project_id)
        if payload is not None:
            payloads.append(payload)

    if payloads:
        source_payload = _choose_permission_payload(
            payloads,
            requested_project_id=requested_project_id,
            canonical_project_id=canonical_project_id,
        )
        await sync_agent_hub_project_permission(
            canonical_project_id,
            _coerce_permission_bootstrap(source_payload, root_path=root_path),
            root_path,
        )

    for legacy_project_id in project_ids:
        if legacy_project_id == canonical_project_id:
            continue
        await delete_agent_hub_project_permission(legacy_project_id)


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
