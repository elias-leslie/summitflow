"""Project coordination pulse command."""

from __future__ import annotations

from typing import Annotated, Any

import typer

from .._output_state import is_compact
from ..client import APIError, STClient
from ..output import handle_api_error, output_json

app = typer.Typer(help="Cross-agent coordination pulse")


def _resolve_project_ids(client: STClient, project_id: str | None) -> list[str]:
    """Return the project ids to query for pulse data."""
    if project_id:
        return [project_id]

    payload = client.get(client._global_url("/projects"))
    if not isinstance(payload, list):
        return []
    return [
        str(project.get("id") or "")
        for project in payload
        if isinstance(project, dict) and project.get("id")
    ]


def _format_owner(owner: dict[str, Any]) -> str:
    scope = owner.get("scope_paths") or []
    scope_preview = ",".join(str(path) for path in scope[:3]) if isinstance(scope, list) else ""
    kind = str(owner.get("ownership_kind") or "unknown")
    if kind == "unscoped" and owner.get("task_id") and owner.get("is_worktree"):
        kind = "task_worktree"
    details = [
        str(owner.get("task_id") or "-"),
        str(owner.get("agent_slug") or "?"),
        str(owner.get("session_id") or "?")[:8],
        f"kind={kind}",
    ]
    if scope_preview:
        details.append(f"paths={scope_preview}")
    if owner.get("scope_confidence"):
        details.append(f"scope={owner['scope_confidence']}")
    if owner.get("is_stale"):
        details.append("stale=yes")
    return "OWN " + " | ".join(details)


def _format_session(session: dict[str, Any]) -> str:
    live = session.get("live_activity") if isinstance(session.get("live_activity"), dict) else {}
    touched = live.get("files_touched") if isinstance(live, dict) else []
    touched_preview = ",".join(str(path) for path in touched[:2]) if isinstance(touched, list) else ""
    observed_writes = session.get("observed_write_paths") if isinstance(session.get("observed_write_paths"), list) else []
    write_preview = ",".join(str(path) for path in observed_writes[:2]) if observed_writes else ""
    model = session.get("effective_model") or session.get("requested_model") or "unknown"
    details = [
        str(session.get("lane_role") or "observer"),
        str(session.get("agent_slug") or session.get("session_type") or "?"),
        str(session.get("id") or "?")[:8],
        str(model).split("/")[-1],
        f"{live.get('health', session.get('status', 'unknown'))}/{live.get('phase', session.get('status', 'unknown'))}",
    ]
    if session.get("scope_confidence"):
        details.append(f"scope={session['scope_confidence']}")
    if write_preview:
        details.append(f"writes={write_preview}")
    if touched_preview:
        details.append(f"files={touched_preview}")
    return "SES " + " | ".join(details)


def _format_stale_session(session: dict[str, Any]) -> str:
    live = session.get("live_activity") if isinstance(session.get("live_activity"), dict) else {}
    model = session.get("effective_model") or session.get("requested_model") or "unknown"
    state = live.get("lifecycle_state") or live.get("health") or session.get("status") or "unknown"
    details = [
        str(session.get("lane_role") or "observer"),
        str(session.get("agent_slug") or session.get("session_type") or "?"),
        str(session.get("id") or "?")[:8],
        str(model).split("/")[-1],
        str(state),
    ]
    reapable_reason = live.get("reapable_reason")
    if isinstance(reapable_reason, str) and reapable_reason:
        details.append(f"reason={reapable_reason}")
    return "STALE " + " | ".join(details)


def _format_task(task: dict[str, Any]) -> str:
    return "RUN " + " | ".join(
        [
            str(task.get("id") or "?"),
            str(task.get("status") or "?"),
            f"P{task.get('priority') if task.get('priority') is not None else '?'}",
            str(task.get("title") or "")[:80],
        ]
    )


def _format_stranded_task(task: dict[str, Any]) -> str:
    return "STRANDED " + " | ".join(
        [
            str(task.get("id") or "?"),
            str(task.get("status") or "?"),
            "no_owner_session",
            str(task.get("title") or "")[:80],
        ]
    )


def _print_compact(payloads: list[dict[str, Any]]) -> None:
    for payload in payloads:
        summary = payload.get("summary", {})
        cleanup = payload.get("cleanup", {})
        project_id = payload.get("project_id", "?")
        print(
            "PULSE:{project}|tasks={tasks}|owners={owners}|specialists={specialists}|"
            "sessions={sessions}|stale={stale}|reapable={reapable}|worktrees={worktrees}|dirty={dirty}|cleanup={cleanup_needed}|stranded={stranded}".format(
                project=project_id,
                tasks=summary.get("running_tasks", 0),
                owners=summary.get("active_owners", 0),
                specialists=summary.get("active_specialists", 0),
                sessions=summary.get("active_sessions", 0),
                stale=summary.get("stale_sessions", 0),
                reapable=summary.get("reapable_sessions", 0),
                worktrees=cleanup.get("active_worktrees", 0),
                dirty=cleanup.get("dirty_worktrees", 0),
                cleanup_needed="yes" if cleanup.get("needs_cleanup") else "no",
                stranded=summary.get("stranded_tasks", 0),
            )
        )
        for task in payload.get("running_tasks", [])[:4]:
            if isinstance(task, dict):
                print(_format_task(task))
        for task in payload.get("stranded_tasks", [])[:4]:
            if isinstance(task, dict):
                print(_format_stranded_task(task))
        for owner in payload.get("active_owners", [])[:4]:
            if isinstance(owner, dict):
                print(_format_owner(owner))
        for session in payload.get("active_sessions", [])[:4]:
            if isinstance(session, dict):
                print(_format_session(session))
        for session in payload.get("stale_sessions", [])[:4]:
            if isinstance(session, dict):
                print(_format_stale_session(session))


@app.command()
def pulse(
    project_id: Annotated[
        str | None,
        typer.Option("--project", help="Show pulse for one project instead of the global overview"),
    ] = None,
    all_projects: Annotated[
        bool,
        typer.Option("--all", help="Show pulse for all managed projects (default; compatibility alias)"),
    ] = False,
) -> None:
    """Show the canonical live coordination pulse."""
    if project_id and all_projects:
        raise typer.BadParameter("Use either --project or --all, not both.")

    client = STClient(require_project=False)
    try:
        payloads = [
            client.get(client._global_url(f"/projects/{resolved_project_id}/pulse"))
            for resolved_project_id in _resolve_project_ids(client, project_id)
        ]
    except APIError as e:
        handle_api_error(e)
        return

    if is_compact():
        _print_compact(payloads)
        return

    output_json(payloads[0] if len(payloads) == 1 else {"projects": payloads, "total": len(payloads)})
