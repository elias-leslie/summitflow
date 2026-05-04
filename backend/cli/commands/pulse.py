"""Project coordination pulse command."""

from __future__ import annotations

from typing import Annotated, Any

import typer

from .._observability import refresh_agent_observability
from .._output_state import is_compact
from ..client import APIError, STClient
from ..config import get_config_optional
from ..lib.jj import JJRepoStatus
from ..output import handle_api_error, output_error, output_json
from .pulse_formatters import (
    _payload_for_allowed_task,
    _preflight_reasons,
    print_compact_payload,
)

app = typer.Typer(help="Cross-agent coordination pulse")


def _resolve_project_ids(
    client: STClient,
    project_id: str | None,
    *,
    all_projects: bool = False,
    require_current: bool = False,
) -> list[str]:
    """Return the project ids to query for pulse data."""
    if project_id:
        return [project_id]
    if not all_projects:
        detected = get_config_optional().project_id
        if detected:
            return [detected]
        if require_current:
            raise typer.BadParameter(
                "Pulse gate requires a current project. Run inside a registered project, "
                "set ST_PROJECT_ID, pass --project / -P, or pass --all for a global gate."
            )

    payload = client.get(client._global_url("/projects"))
    if not isinstance(payload, list):
        return []
    return [
        str(project.get("id") or "")
        for project in payload
        if isinstance(project, dict) and project.get("id")
    ]


def _jj_status_for_project(project_id: Any) -> JJRepoStatus | None:
    try:
        from ..lib.jj import status_summary
        from .cleanup import _iter_target_repos

        repos = _iter_target_repos(False, str(project_id))
        repo = next((path for path in repos if path.name == str(project_id)), None)
        if repo is None or not (repo / ".jj").is_dir():
            return None
        return status_summary(repo)
    except Exception:
        return None


def preflight_reasons_for_payload(payload: dict[str, Any], *, allow_task_id: str | None = None) -> list[str]:
    filtered = _payload_for_allowed_task(payload, allow_task_id)
    summary = filtered.get("summary", {})
    cleanup = filtered.get("cleanup", {})
    project_id = filtered.get("project_id", "?")
    return _preflight_reasons(summary, cleanup, _jj_status_for_project(project_id), filtered)


def _print_compact(payloads: list[dict[str, Any]], *, details: bool = False) -> None:
    for payload in payloads:
        print_compact_payload(payload, details=details, jj_status_for_project=_jj_status_for_project)


def _payload_blocked(payload: dict[str, Any]) -> bool:
    return bool(preflight_reasons_for_payload(payload))


def fetch_pulse_payload(project_id: str) -> dict[str, Any]:
    client = STClient(require_project=False)
    payload = client.get(client._global_url(f"/projects/{project_id}/pulse"))
    return payload if isinstance(payload, dict) else {}


def require_pulse_gate(project_id: str | None, *, allow_task_id: str | None = None) -> None:
    if not project_id:
        return
    try:
        payload = fetch_pulse_payload(project_id)
    except APIError as exc:
        output_error(f"Pulse gate unavailable: {exc.detail}")
        raise typer.Exit(2) from None
    reasons = preflight_reasons_for_payload(payload, allow_task_id=allow_task_id)
    if not reasons:
        return
    output_error(f"Pulse gate blocked: {project_id} {','.join(reasons)}")
    raise typer.Exit(2)


def _pulse_payloads(
    client: STClient,
    project_id: str | None,
    *,
    all_projects: bool,
    gate: bool,
    details: bool,
) -> list[dict[str, Any]]:
    suffix = "" if details or gate or not is_compact() else "?compact=true"
    return [
        client.get(client._global_url(f"/projects/{resolved_project_id}/pulse{suffix}"))
        for resolved_project_id in _resolve_project_ids(
            client,
            project_id,
            all_projects=all_projects,
            require_current=gate and not all_projects,
        )
    ]


@app.command()
def pulse(
    project_id: Annotated[
        str | None,
        typer.Option("--project", "-P", help="Show pulse for one project instead of the global overview"),
    ] = None,
    all_projects: Annotated[
        bool,
        typer.Option("--all", help="Show pulse for all managed projects."),
    ] = False,
    gate: Annotated[
        bool,
        typer.Option("--gate", help="Exit 2 if any lane preflight is blocked."),
    ] = False,
    details: Annotated[
        bool,
        typer.Option("--details", help="Show diagnostic task, ownership, and session rows."),
    ] = False,
) -> None:
    """Show the canonical live coordination pulse and optional preflight gate."""
    if project_id and all_projects:
        raise typer.BadParameter("Use either --project or --all, not both.")

    refresh_agent_observability()
    client = STClient(require_project=False)
    try:
        payloads = _pulse_payloads(
            client,
            project_id,
            all_projects=all_projects,
            gate=gate,
            details=details,
        )
    except APIError as e:
        handle_api_error(e)
        return

    if is_compact():
        _print_compact(payloads, details=details)
        if gate and any(_payload_blocked(payload) for payload in payloads):
            raise typer.Exit(2)
        return

    output_json(payloads[0] if len(payloads) == 1 else {"projects": payloads, "total": len(payloads)})
    if gate and any(_payload_blocked(payload) for payload in payloads):
        raise typer.Exit(2)
