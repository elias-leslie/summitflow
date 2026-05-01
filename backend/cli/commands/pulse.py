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


def _scope_preview(owner: dict[str, Any]) -> str:
    scope = owner.get("scope_paths") or []
    return ",".join(str(path) for path in scope[:3]) if isinstance(scope, list) else ""


def _format_owner(owner: dict[str, Any]) -> str:
    scope_preview = _scope_preview(owner)
    kind = str(owner.get("ownership_kind") or "unknown")
    if kind == "unscoped" and owner.get("task_id"):
        kind = "task_checkout"
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
    return "WRITE " + " | ".join(details)


def _format_reader(reader: dict[str, Any]) -> str:
    paths = reader.get("observed_read_paths") or reader.get("scope_paths") or []
    path_preview = ",".join(str(path) for path in paths[:3]) if isinstance(paths, list) else ""
    details = [
        str(reader.get("task_id") or "-"),
        str(reader.get("agent_slug") or reader.get("source_client") or "?"),
        str(reader.get("session_id") or "?")[:8],
    ]
    if path_preview:
        details.append(f"paths={path_preview}")
    if reader.get("scope_confidence"):
        details.append(f"scope={reader['scope_confidence']}")
    return "READ " + " | ".join(details)


def _session_actor_label(session: dict[str, Any]) -> str:
    for key in ("agent_slug", "source_client", "request_source", "session_type"):
        value = session.get(key)
        if isinstance(value, str) and value:
            return value
    return "?"


def _format_session(session: dict[str, Any]) -> str:
    raw_live = session.get("live_activity")
    live: dict[str, Any] = raw_live if isinstance(raw_live, dict) else {}
    touched = live.get("files_touched") if isinstance(live, dict) else []
    touched_preview = ",".join(str(path) for path in touched[:2]) if isinstance(touched, list) else ""
    observed_writes = session.get("observed_write_paths") if isinstance(session.get("observed_write_paths"), list) else []
    write_preview = ",".join(str(path) for path in observed_writes[:2]) if observed_writes else ""
    model = session.get("effective_model") or session.get("requested_model") or "unknown"
    details = [
        str(session.get("lane_role") or "observer"),
        _session_actor_label(session),
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
    raw_live = session.get("live_activity")
    live: dict[str, Any] = raw_live if isinstance(raw_live, dict) else {}
    model = session.get("effective_model") or session.get("requested_model") or "unknown"
    state = live.get("lifecycle_state") or live.get("health") or session.get("status") or "unknown"
    details = [
        str(session.get("lane_role") or "observer"),
        _session_actor_label(session),
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


def _truthy_count(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _dirty_residue_count(cleanup: dict[str, Any]) -> int:
    dirty = _truthy_count(cleanup.get("dirty_checkpoints")) + _truthy_count(
        cleanup.get("dirty_repositories")
    )
    if dirty == 0 and _truthy_count(cleanup.get("dirty_main_repo")):
        dirty = 1
    return dirty


def _needs_ownerless_review(summary: dict[str, Any], cleanup: dict[str, Any]) -> bool:
    active_agents = (
        _truthy_count(summary.get("active_owners"))
        + _truthy_count(summary.get("active_specialists"))
    )
    if active_agents:
        return False
    return bool(
        _truthy_count(cleanup.get("active_checkpoints"))
        or _dirty_residue_count(cleanup)
        or _truthy_count(summary.get("stranded_tasks"))
    )


def _format_ownerless_review(project_id: Any, summary: dict[str, Any], cleanup: dict[str, Any]) -> str | None:
    if not _needs_ownerless_review(summary, cleanup):
        return None
    return (
        f"REVIEW:{project_id}|ownerless=yes|dirty={_dirty_residue_count(cleanup)}|"
        f"checkpoints={_truthy_count(cleanup.get('active_checkpoints'))}|"
        f"stranded={_truthy_count(summary.get('stranded_tasks'))}|"
        "action=agent-inspect-context-status-logs-then-commit-push-prune-or-leave-explicit-handoff"
    )


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


def _format_jj_state(project_id: Any, status: JJRepoStatus) -> str:
    return (
        f"JJSTATE:{project_id}|state={status.state}|described={str(status.described).lower()}|"
        f"conflicts={str(status.conflicted).lower()}|unpublished={status.unpublished}|"
        f"change={status.change_id}|commit={status.commit_id}"
    )


def _preflight_reasons(
    summary: dict[str, Any],
    cleanup: dict[str, Any],
    jj_status: JJRepoStatus | None = None,
) -> list[str]:
    reasons: list[str] = []
    if jj_status and jj_status.colocated and jj_status.conflicted:
        reasons.append("jj_conflicts")
    return reasons


def _format_preflight(
    project_id: Any,
    summary: dict[str, Any],
    cleanup: dict[str, Any],
    jj_status: JJRepoStatus | None = None,
) -> str:
    reasons = _preflight_reasons(summary, cleanup, jj_status)
    state = "blocked" if reasons else "clear"
    detail = ",".join(reasons) if reasons else "-"
    return f"PREFLIGHT:{project_id}|claim={state}|edit={state}|reasons={detail}|source=st-pulse"


def _payload_for_allowed_task(payload: dict[str, Any], task_id: str | None) -> dict[str, Any]:
    if not task_id:
        return payload
    allowed_session_ids = {
        str(owner.get("session_id") or "")
        for owner in [*payload.get("active_owners", []), *payload.get("active_specialists", [])]
        if isinstance(owner, dict) and owner.get("task_id") == task_id
    }
    filtered = dict(payload)
    filtered["active_owners"] = [
        owner for owner in payload.get("active_owners", [])
        if not (isinstance(owner, dict) and owner.get("task_id") == task_id)
    ]
    filtered["active_specialists"] = [
        owner for owner in payload.get("active_specialists", [])
        if not (isinstance(owner, dict) and owner.get("task_id") == task_id)
    ]
    filtered["active_sessions"] = [
        session for session in payload.get("active_sessions", [])
        if not (isinstance(session, dict) and str(session.get("id") or "") in allowed_session_ids)
    ]
    filtered["running_tasks"] = [
        task for task in payload.get("running_tasks", [])
        if not (isinstance(task, dict) and task.get("id") == task_id)
    ]
    filtered["stranded_tasks"] = [
        task for task in payload.get("stranded_tasks", [])
        if not (isinstance(task, dict) and task.get("id") == task_id)
    ]
    summary = dict(payload.get("summary", {}))
    summary["active_owners"] = len(filtered["active_owners"])
    summary["active_specialists"] = len(filtered["active_specialists"])
    summary["active_sessions"] = len(filtered["active_sessions"])
    summary["running_tasks"] = len(filtered["running_tasks"])
    summary["stranded_tasks"] = len(filtered["stranded_tasks"])
    filtered["summary"] = summary
    cleanup = dict(payload.get("cleanup", {}))
    checkpoint_ids = cleanup.get("checkpoint_task_ids")
    if isinstance(checkpoint_ids, list) and task_id in {str(item) for item in checkpoint_ids}:
        cleanup["checkpoint_task_ids"] = [item for item in checkpoint_ids if str(item) != task_id]
        cleanup["active_checkpoints"] = max(0, _truthy_count(cleanup.get("active_checkpoints")) - 1)
    filtered["cleanup"] = cleanup
    return filtered


def preflight_reasons_for_payload(payload: dict[str, Any], *, allow_task_id: str | None = None) -> list[str]:
    filtered = _payload_for_allowed_task(payload, allow_task_id)
    summary = filtered.get("summary", {})
    cleanup = filtered.get("cleanup", {})
    project_id = filtered.get("project_id", "?")
    return _preflight_reasons(summary, cleanup, _jj_status_for_project(project_id))


def _print_compact(payloads: list[dict[str, Any]], *, details: bool = False) -> None:
    for payload in payloads:
        summary = payload.get("summary", {})
        cleanup = payload.get("cleanup", {})
        project_id = payload.get("project_id", "?")
        jj_status = _jj_status_for_project(project_id)
        print(
            "PULSE:{project}|tasks={tasks}|writers={writers}|readers={readers}|specialists={specialists}|"
            "sessions={sessions}|stale={stale}|reapable={reapable}|checkpoints={checkpoints}|dirty={dirty}|cleanup={cleanup_needed}|stranded={stranded}".format(
                project=project_id,
                tasks=summary.get("running_tasks", 0),
                writers=summary.get("active_owners", 0),
                readers=summary.get("active_readers", 0),
                specialists=summary.get("active_specialists", 0),
                sessions=summary.get("active_sessions", 0),
                stale=summary.get("stale_sessions", 0),
                reapable=summary.get("reapable_sessions", 0),
                checkpoints=cleanup.get("active_checkpoints", 0),
                dirty=_dirty_residue_count(cleanup),
                cleanup_needed="yes" if cleanup.get("needs_cleanup") else "no",
                stranded=summary.get("stranded_tasks", 0),
            )
        )
        if jj_status is not None:
            print(_format_jj_state(project_id, jj_status))
        print(_format_preflight(project_id, summary, cleanup, jj_status))
        review_line = _format_ownerless_review(project_id, summary, cleanup)
        if review_line:
            print(review_line)
        if review_line or (jj_status is not None and jj_status.state != "clean"):
            print(
                f"ACTION:{project_id}|if_dirty=inspect-diff-once-then-commit-or-continue-narrow|"
                "ownership=diagnostic-only"
            )
        if not details:
            continue
        for task in payload.get("running_tasks", [])[:4]:
            if isinstance(task, dict):
                print(_format_task(task))
        for task in payload.get("stranded_tasks", [])[:4]:
            if isinstance(task, dict):
                print(_format_stranded_task(task))
        for owner in payload.get("active_owners", [])[:4]:
            if isinstance(owner, dict):
                print(_format_owner(owner))
        for reader in payload.get("active_readers", [])[:4]:
            if isinstance(reader, dict):
                print(_format_reader(reader))
        summarized_session_ids = {
            str(row.get("session_id") or "")
            for key in ("active_owners", "active_readers", "active_specialists")
            for row in payload.get(key, [])
            if isinstance(row, dict)
        }
        visible_sessions = [
            session for session in payload.get("active_sessions", [])
            if isinstance(session, dict)
            and str(session.get("id") or "") not in summarized_session_ids
        ]
        for session in visible_sessions[:4]:
            if isinstance(session, dict):
                print(_format_session(session))
        for session in payload.get("stale_sessions", [])[:4]:
            if isinstance(session, dict):
                print(_format_stale_session(session))


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
        payloads = [
            client.get(client._global_url(f"/projects/{resolved_project_id}/pulse"))
            for resolved_project_id in _resolve_project_ids(
                client,
                project_id,
                all_projects=all_projects,
                require_current=gate and not all_projects,
            )
        ]
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
