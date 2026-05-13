"""Veeam host system-image backup commands."""

from __future__ import annotations

import time
from typing import Annotated, Any

import typer

from ..client import APIError, STClient
from ..lib.usage import usage
from ..output import handle_api_error, output_error, output_json
from .backup_api import BackupSystemImageAPI

app = typer.Typer(help="Veeam host system-image backup controls")


def _api() -> BackupSystemImageAPI:
    client = STClient(require_project=False)
    return BackupSystemImageAPI(client.base_url)


def _yn(value: object) -> str:
    return "yes" if bool(value) else "no"


def _session_label(session: dict[str, Any] | None) -> str:
    if not session:
        return "-"
    state = str(session.get("state") or "?")
    session_id = str(session.get("id") or "?")
    return f"{state}:{session_id}"


def _emit_status_compact(prefix: str, payload: dict[str, Any]) -> None:
    print(
        f"{prefix}|installed={_yn(payload.get('installed'))}"
        f"|service={_yn(payload.get('service_active'))}"
        f"|repo={_yn(payload.get('repository_accessible'))}"
        f"|job={_yn(payload.get('job_configured'))}"
        f"|can_start={_yn(payload.get('can_start'))}"
        f"|active={_session_label(payload.get('active_session'))}"
        f"|last={_session_label(payload.get('last_session'))}"
        f"|next={payload.get('next_action') or '-'}"
    )


def _emit_action_compact(prefix: str, payload: dict[str, Any]) -> None:
    print(
        f"{prefix}|status={payload.get('status') or '-'}"
        f"|session={payload.get('session_id') or '-'}"
        f"|message={payload.get('message') or '-'}"
    )


def _wait_for_completion(
    api: BackupSystemImageAPI,
    *,
    session_id: str | None,
    poll_seconds: int,
    timeout_minutes: int,
) -> dict[str, Any]:
    deadline = time.monotonic() + (timeout_minutes * 60)
    started = time.monotonic()

    while True:
        payload = api.status()
        active = payload.get("active_session")
        last = payload.get("last_session")

        if not active and (session_id is None or (last and last.get("id") == session_id)):
            _emit_status_compact("VEEAM_DONE", payload)
            return payload

        elapsed = int(time.monotonic() - started)
        print(
            f"VEEAM_WAIT|elapsed={elapsed}s"
            f"|active={_session_label(active)}"
            f"|last={_session_label(last)}"
        )
        if time.monotonic() >= deadline:
            output_error(f"Timed out waiting for Veeam backup after {timeout_minutes} minutes.")
            raise typer.Exit(1)
        time.sleep(poll_seconds)


@app.command("status")
def status(ctx: typer.Context) -> None:
    """Show Veeam system-image backup status."""
    try:
        payload = _api().status()
    except APIError as exc:
        handle_api_error(exc)
        return
    if ctx.obj.is_compact:
        _emit_status_compact("VEEAM_STATUS", payload)
    else:
        output_json(payload)


@app.command("start")
@usage(
    surface="st.backup.veeam",
    cmd="st backup veeam start --wait",
    when="kick off and monitor the host-level Veeam system-image backup before risky system/project changes",
    precautions=(
        "wait for completion before starting risky mitigations",
        "use this st surface instead of raw veeamconfig/veeam commands",
        "if another Veeam session is active, use st backup veeam wait",
    ),
    examples=("st backup veeam status", "st backup veeam start --wait", "st backup veeam wait"),
    task_types=("devops", "security", "backup"),
    tier="reference",
)
def start(
    ctx: typer.Context,
    wait: Annotated[bool, typer.Option("--wait", help="Wait until the Veeam session completes")] = False,
    poll_seconds: Annotated[int, typer.Option("--poll-seconds", help="Polling interval while waiting")] = 60,
    timeout_minutes: Annotated[int, typer.Option("--timeout-minutes", help="Maximum wait time")] = 360,
) -> None:
    """Start the configured Veeam system-image backup job."""
    try:
        api = _api()
        payload = api.start()
        if ctx.obj.is_compact:
            _emit_action_compact("VEEAM_START", payload)
        else:
            output_json(payload)
        if wait:
            _wait_for_completion(
                api,
                session_id=str(payload.get("session_id") or "") or None,
                poll_seconds=poll_seconds,
                timeout_minutes=timeout_minutes,
            )
    except APIError as exc:
        handle_api_error(exc)


@app.command("wait")
def wait(
    session_id: Annotated[str | None, typer.Option("--session-id", help="Specific session ID to wait for")] = None,
    poll_seconds: Annotated[int, typer.Option("--poll-seconds", help="Polling interval while waiting")] = 60,
    timeout_minutes: Annotated[int, typer.Option("--timeout-minutes", help="Maximum wait time")] = 360,
) -> None:
    """Wait for the active Veeam system-image backup session to complete."""
    try:
        _wait_for_completion(
            _api(),
            session_id=session_id,
            poll_seconds=poll_seconds,
            timeout_minutes=timeout_minutes,
        )
    except APIError as exc:
        handle_api_error(exc)


@app.command("stop")
def stop(ctx: typer.Context) -> None:
    """Stop the active Veeam system-image backup session."""
    try:
        payload = _api().stop()
    except APIError as exc:
        handle_api_error(exc)
        return
    if ctx.obj.is_compact:
        _emit_action_compact("VEEAM_STOP", payload)
    else:
        output_json(payload)
