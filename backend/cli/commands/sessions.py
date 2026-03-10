"""Agent session and ownership commands for the CLI."""

from __future__ import annotations

from itertools import combinations
from typing import Annotated

import typer

from .._output_state import is_compact
from ..client import APIError, STClient
from ..output import handle_api_error, output_json

app = typer.Typer(
    help="Agent session management",
    invoke_without_command=True,
    no_args_is_help=False,
)


def _normalize_status_filter(status_filter: str | None) -> str | None:
    """Normalize CLI-friendly session status aliases to Agent Hub values."""
    if status_filter == "running":
        return "active"
    return status_filter


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


def _collect_project_owners(client: STClient, pid: str) -> list[dict[str, object]]:
    payload = client.get(client._global_url(f"/agent-hub/ownership/projects/{pid}/live"))
    owners = payload.get("active_owners", []) if isinstance(payload, dict) else []
    if not isinstance(owners, list):
        return []
    return [{"project_id": pid, **owner} for owner in owners if isinstance(owner, dict)]


def _render_ownership_list(project_id: str | None) -> None:
    client = STClient(require_project=False)
    rows: list[dict[str, object]] = []

    try:
        for pid in _resolve_projects(client, project_id):
            rows.extend(_collect_project_owners(client, pid))
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


def _owner_write_paths(owner: dict[str, object]) -> set[str]:
    write_paths = owner.get("observed_write_paths")
    declared_paths = owner.get("declared_scope_paths")
    fallback = owner.get("scope_paths")
    normalized: set[str] = set()
    for values in (declared_paths, write_paths, fallback):
        if not isinstance(values, list):
            continue
        for value in values:
            if isinstance(value, str) and value:
                normalized.add(value)
        if normalized:
            return normalized
    return normalized


def _owner_read_paths(owner: dict[str, object]) -> set[str]:
    values = owner.get("observed_read_paths")
    if not isinstance(values, list):
        return set()
    return {value for value in values if isinstance(value, str) and value}


def _shared_plumbing(paths: set[str]) -> list[str]:
    prefixes = (
        "backend/app/adapters/",
        "backend/app/api/complete/",
        "backend/app/services/tools/",
    )
    return sorted(path for path in paths if any(path.startswith(prefix) for prefix in prefixes))


def _overlap_rows(project_id: str, owners: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for left, right in combinations(owners, 2):
        left_id = str(left.get("task_id") or left.get("session_id") or "?")
        right_id = str(right.get("task_id") or right.get("session_id") or "?")
        left_write = _owner_write_paths(left)
        right_write = _owner_write_paths(right)
        left_read = _owner_read_paths(left)
        right_read = _owner_read_paths(right)

        exact = sorted(left_write & right_write)
        if exact:
            rows.append(
                {
                    "project_id": project_id,
                    "risk": "block",
                    "kind": "exact_write",
                    "left_id": left_id,
                    "right_id": right_id,
                    "paths": exact,
                }
            )
            continue

        shared = sorted(set(_shared_plumbing(left_write)) | set(_shared_plumbing(right_write)))
        if shared:
            rows.append(
                {
                    "project_id": project_id,
                    "risk": "block",
                    "kind": "shared_plumbing",
                    "left_id": left_id,
                    "right_id": right_id,
                    "paths": shared,
                }
            )
            continue

        read_overlap = sorted((left_write & right_read) | (right_write & left_read))
        if read_overlap:
            rows.append(
                {
                    "project_id": project_id,
                    "risk": "warn",
                    "kind": "read_overlap",
                    "left_id": left_id,
                    "right_id": right_id,
                    "paths": read_overlap,
                }
            )
            continue

        if not left_write and not left_read and not right_write and not right_read:
            rows.append(
                {
                    "project_id": project_id,
                    "risk": "warn",
                    "kind": "unscoped_pair",
                    "left_id": left_id,
                    "right_id": right_id,
                    "paths": [],
                }
            )
    return rows


def _render_overlap_list(project_id: str | None) -> None:
    client = STClient(require_project=False)
    rows: list[dict[str, object]] = []

    try:
        for pid in _resolve_projects(client, project_id):
            owners = _collect_project_owners(client, pid)
            rows.extend(_overlap_rows(pid, owners))
    except APIError as e:
        handle_api_error(e)
        return

    if not is_compact():
        output_json({"overlaps": rows, "total": len(rows)})
        return

    print(f"OVERLAPS[{len(rows)}]")
    for row in rows:
        parts = [
            str(row.get("project_id") or "?"),
            str(row.get("risk") or "?"),
            str(row.get("kind") or "?"),
            str(row.get("left_id") or "?"),
            str(row.get("right_id") or "?"),
        ]
        if isinstance(row.get("paths"), list) and row["paths"]:
            parts.append(f"paths={','.join(str(path) for path in row['paths'][:3])}")
        print("OVR " + " | ".join(parts))


def _render_session_list(
    status_filter: str | None,
    limit: int,
    agent_slug: str | None,
    parent_session_id: str | None,
    project_id: str | None,
    include_unassigned: bool = True,
) -> None:
    client = STClient()
    normalized_status = _normalize_status_filter(status_filter)

    try:
        sessions = client.list_sessions(
            status=normalized_status,
            limit=limit,
            page=1,
            agent_slug=agent_slug,
            parent_session_id=parent_session_id,
            project_id=project_id,
        )
    except APIError as e:
        handle_api_error(e)
        return

    if not include_unassigned:
        sessions = [session for session in sessions if session.get("agent_slug")]

    output_json(sessions)


@app.callback()
def sessions_callback(
    ctx: typer.Context,
    status_filter: Annotated[str | None, typer.Option("-s", "--status")] = None,
    limit: Annotated[int, typer.Option("--limit")] = 20,
    agent_slug: Annotated[str | None, typer.Option("--agent")] = None,
    parent_session_id: Annotated[str | None, typer.Option("--parent-session")] = None,
    project_id: Annotated[str | None, typer.Option("--project")] = None,
) -> None:
    """List agent sessions when no subcommand is provided."""
    if ctx.invoked_subcommand is not None:
        return
    _render_session_list(
        status_filter,
        limit,
        agent_slug,
        parent_session_id,
        project_id,
        include_unassigned=False,
    )


@app.command("list")
def list_sessions(
    status_filter: Annotated[str | None, typer.Option("-s", "--status")] = None,
    include_unassigned: Annotated[
        bool,
        typer.Option(
            "--include-unassigned",
            help="Include imported/unassigned sessions without an agent slug",
        ),
    ] = False,
    limit: Annotated[int, typer.Option("--limit")] = 20,
    agent_slug: Annotated[str | None, typer.Option("--agent")] = None,
    parent_session_id: Annotated[str | None, typer.Option("--parent-session")] = None,
    project_id: Annotated[str | None, typer.Option("--project")] = None,
) -> None:
    """List agent sessions.

    Examples:
        st sessions
        st sessions list
        st sessions list --status active
    """
    _render_session_list(
        status_filter,
        limit,
        agent_slug,
        parent_session_id,
        project_id,
        include_unassigned=include_unassigned,
    )


@app.command("show")
def show_session(
    session_id: str,
) -> None:
    """Show details of a specific session.

    Examples:
        st sessions show abc123
    """
    client = STClient()

    try:
        session = client.get_session(session_id)
    except APIError as e:
        handle_api_error(e)
        return

    output_json(session)


@app.command("close")
def close_session(
    session_id: str,
) -> None:
    """Close an active session."""
    client = STClient()

    try:
        result = client.close_session(session_id)
    except APIError as e:
        handle_api_error(e)
        return

    output_json(result)


@app.command("ownership")
def list_ownership(
    project_id: Annotated[str | None, typer.Option("--project")] = None,
) -> None:
    """List live active ownership lanes across projects or for one project."""
    _render_ownership_list(project_id)


@app.command("overlap")
def list_overlaps(
    project_id: Annotated[str | None, typer.Option("--project")] = None,
) -> None:
    """List current scope overlaps across active ownership lanes."""
    _render_overlap_list(project_id)
