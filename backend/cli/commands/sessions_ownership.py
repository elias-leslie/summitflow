"""Ownership listing helpers for the sessions CLI."""

from __future__ import annotations

from app.services._ownership_roles import is_read_only_owner

from .._output_state import is_compact
from ..client import APIError, STClient
from ..output import handle_api_error, output_json


def _resolve_projects(client: STClient, project_id: str | None) -> list[str]:
    if project_id:
        return [project_id]
    payload = client.get(client._global_url("/projects"))
    if isinstance(payload, list):
        projects = payload
    elif isinstance(payload, dict):
        projects = payload.get("projects", [])
    else:
        projects = []
    return [
        project.get("id") or project.get("project_id")
        for project in projects
        if isinstance(project, dict) and (project.get("id") or project.get("project_id"))
    ]


def collect_project_owners(client: STClient, pid: str) -> list[dict[str, object]]:
    payload = client.get(client._global_url(f"/agent-hub/ownership/projects/{pid}/live"))
    owners = payload.get("active_owners", []) if isinstance(payload, dict) else []
    if not isinstance(owners, list):
        return []
    return [{"project_id": pid, **owner} for owner in owners if isinstance(owner, dict)]


def _format_ownership_line(project_id: str, owner: dict[str, object]) -> str:
    parts = [
        project_id,
        str(owner.get("task_id") or "-"),
        str(owner.get("agent_slug") or "?"),
        str(owner.get("session_id") or "?"),
        f"kind={owner.get('ownership_kind') or 'unknown'}",
    ]
    if branch := owner.get("branch"):
        parts.append(f"branch={branch}")
    if location := owner.get("working_dir") or owner.get("checkout_path"):
        parts.append(f"cwd={location}")
    if isinstance(scope_paths := owner.get("scope_paths"), list) and scope_paths:
        parts.append(f"paths={','.join(str(path) for path in scope_paths[:3])}")
    if scope_confidence := owner.get("scope_confidence"):
        parts.append(f"scope={scope_confidence}")
    if owner.get("is_stale"):
        parts.append("stale=yes")
    return "WRITE " + " | ".join(parts)


def _format_reader_line(project_id: str, owner: dict[str, object]) -> str:
    paths = owner.get("observed_read_paths") or owner.get("scope_paths")
    parts = [
        project_id,
        str(owner.get("task_id") or "-"),
        str(owner.get("agent_slug") or "?"),
        str(owner.get("session_id") or "?"),
    ]
    if isinstance(paths, list) and paths:
        parts.append(f"paths={','.join(str(path) for path in paths[:3])}")
    if scope_confidence := owner.get("scope_confidence"):
        parts.append(f"scope={scope_confidence}")
    return "READ " + " | ".join(parts)


def _partition_owner_rows(
    rows: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    writers: list[dict[str, object]] = []
    readers: list[dict[str, object]] = []
    for row in rows:
        if is_read_only_owner(row):
            readers.append(row)
        else:
            writers.append(row)
    return writers, readers


def render_ownership_list(client: STClient, project_id: str | None) -> None:
    rows: list[dict[str, object]] = []

    try:
        for pid in _resolve_projects(client, project_id):
            rows.extend(collect_project_owners(client, pid))
    except APIError as e:
        handle_api_error(e)
        return

    rows.sort(
        key=lambda row: (
            str(row.get("project_id") or ""),
            str(row.get("task_id") or ""),
            str(row.get("agent_slug") or ""),
            str(row.get("session_id") or ""),
        )
    )

    writers, readers = _partition_owner_rows(rows)

    if not is_compact():
        output_json({"owners": writers, "readers": readers, "total": len(rows)})
        return

    print(f"OWNERSHIP[writers={len(writers)}|readers={len(readers)}]")
    for row in writers:
        print(_format_ownership_line(str(row.get("project_id") or "?"), row))
    for row in readers:
        print(_format_reader_line(str(row.get("project_id") or "?"), row))
