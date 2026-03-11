"""Ownership listing helpers for the sessions CLI."""

from __future__ import annotations

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
    if location := owner.get("worktree_path"):
        parts.append(f"cwd={location}")
    if isinstance(scope_paths := owner.get("scope_paths"), list) and scope_paths:
        parts.append(f"paths={','.join(str(path) for path in scope_paths[:3])}")
    if scope_confidence := owner.get("scope_confidence"):
        parts.append(f"scope={scope_confidence}")
    if owner.get("is_stale"):
        parts.append("stale=yes")
    return "OWN " + " | ".join(parts)


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

    if not is_compact():
        output_json({"owners": rows, "total": len(rows)})
        return

    print(f"OWNERSHIP[{len(rows)}]")
    for row in rows:
        print(_format_ownership_line(str(row.get("project_id") or "?"), row))
