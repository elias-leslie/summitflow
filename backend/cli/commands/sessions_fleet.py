"""Fleet start/send/wait, registered on the existing sessions lifecycle."""

from __future__ import annotations

import json
import uuid
from typing import Annotated, Any, Literal

import typer
from st_sdk.fleet import FleetClient
from st_sdk.usage import usage

from ..client import APIError, STClient
from ..config import get_config, get_project_override
from ..output import handle_api_error, output_json


def _scope(value: str) -> dict[str, str]:
    try:
        result = json.loads(value)
    except ValueError as exc:
        raise typer.BadParameter("Scope must be a JSON object of exact source references") from exc
    if not isinstance(result, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in result.items()):
        raise typer.BadParameter("Scope must be a JSON object with string values")
    return result


def _client() -> FleetClient:
    return FleetClient(STClient(require_project=False))


def _call(method: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
    try:
        return getattr(_client(), method)(*args, **kwargs)
    except APIError as exc:
        handle_api_error(exc)
        raise typer.Exit(1) from exc


def start(
    instruction: Annotated[str, typer.Argument(help="Short sanitized starting instruction")],
    tool: Annotated[str, typer.Option(help="Aico host tool: codex or claude-code")] = "codex",
    surface: Annotated[str, typer.Option(help="Owner surface: aico or a-term")] = "aico",
    scope: Annotated[str, typer.Option(help="Exact scope/source references as JSON")] = "{}",
    role: Annotated[str, typer.Option(help="portfolio-root, neri-target-root, or neri-support-root")] = "portfolio-root",
    lead_root: Annotated[str | None, typer.Option(help="Opaque target lead root for a support allocation")] = None,
    facet: Annotated[str | None, typer.Option(help="Disjoint bounded support facet or capsule reference")] = None,
    request_id: Annotated[str | None, typer.Option(help="Retained opaque root handle for an idempotent retry")] = None,
    resume_session: Annotated[str | None, typer.Option(help="Exact saved native session ID to resume in a new root; the owner adapter validates it")] = None,
    execution_root: Annotated[str | None, typer.Option(help="Existing project checkout directory for execution")] = None,
) -> None:
    """Register a fleet root, then request it from the owner.

    --resume-session resumes one exact saved native session in a newly allocated
    root (no picker or latest-thread inference). The instruction plus fleet
    directions must fit 2000 UTF-8 bytes. Only a digest of the ID is retained;
    retry with the same --request-id, instruction and resume ID.
    """
    capsule: dict[str, Any] = {"project_id": get_project_override() or get_config().project_id,
                               "tool": tool, "surface": surface, "instruction": instruction,
                               "scope": _scope(scope), "role": role, "lead_root": lead_root, "facet": facet,
                               "root": request_id or "root-" + uuid.uuid4().hex}
    if resume_session is not None:
        capsule["resume_session"] = resume_session
    if execution_root is not None:
        capsule["execution_root"] = execution_root
    output_json(_call("start", **capsule))


@usage(
    surface="st.sessions.send",
    cmd="st -P PROJECT sessions send ROOT_OR_UUID 'instruction' --source-key REVISION [--delivery native-thread]",
    when="deliver an authorized bounded instruction through the fleet stream or native Codex thread queue",
    precautions=(
        "Default fleet-stream is passive retention consumed through wait; native-thread uses exact project/UUID provenance and local owner transport.",
        "Native-thread requires exact UUID + stable revision and <=2000 sanitized UTF-8 bytes. Queued/durable does not mean working or observed consumption and is not generation-fenced; offline input can execute on same-thread resume.",
        "Reuse the source key to reconcile pending/uncertain attempts; never blindly replay with a new key. No secrets or transcripts.",
        "Use sessions verify UUID --source-key REVISION for content-free correlated queue/consumption/turn status; missing queue entries alone prove nothing.",
        "Use current-client native delegation for subagents; this addresses existing root threads, not spawned children.",
    ),
    tier="reference",
)
def send(
    root: str,
    instruction: Annotated[str, typer.Argument(help="Short non-secret instruction for the fleet root or exact native thread; no credentials/private target data")],
    scope: Annotated[str, typer.Option(help="Must exactly match the root scope JSON")] = "{}",
    source_key: Annotated[str | None, typer.Option(help="Stable instruction revision key; reuse on retry")] = None,
    delivery: Annotated[Literal["fleet-stream", "native-thread", "handshake"], typer.Option(help="Native mode addresses an exact bound Codex UUID, including offline resume; handshake records an agent request that needs ack and confirm")] = "fleet-stream",
) -> None:
    """Default delivery is passive fleet retention.

    Native-thread requires an exact bound UUID, stable --source-key revision,
    and <=2000 sanitized UTF-8 bytes. Queued/durable does not mean working or
    observed consumption and is not generation-fenced; offline input may run
    when that same thread resumes.
    """
    if delivery == "handshake":
        from .sessions_handshake import send_request

        send_request(root, instruction)
        return
    if delivery == "native-thread":
        from .sessions_native_delivery import send_native_instruction

        if scope != "{}":
            raise typer.BadParameter("Native delivery uses the exact project/thread binding, without fleet scope")
        if source_key is None:
            raise typer.BadParameter("Native delivery requires --source-key for safe reconciliation")
        try:
            result = send_native_instruction(root, instruction, project=get_project_override() or get_config().project_id, source_key=source_key)
        except (ValueError, OSError) as exc:
            raise typer.BadParameter(str(exc)) from exc
        output_json(result)
        return
    output_json(_call("send", root, instruction=instruction, scope=_scope(scope), source_key=source_key or "instruction:" + uuid.uuid4().hex))


@usage(
    surface="st.sessions.wait",
    cmd="st sessions wait ROOT --cursor SEQUENCE [--timeout SECONDS]",
    when="consume the existing fleet root's durable advisory instruction and result stream",
    precautions=("Carry the returned cursor; quiet timeout emits nothing. Fleet retrieval is not native TUI submission or observed receipt.",),
    tier="reference",
)
def wait(
    root: str,
    cursor: Annotated[int, typer.Option(min=0, help="Exclusive durable stream sequence cursor")] = 0,
    timeout: Annotated[float, typer.Option(min=0, max=300, help="Quiet wait seconds (default 300)")] = 300,
) -> None:
    result = _call("wait", root, cursor=cursor, timeout=timeout)
    if result.get("events"):
        output_json(result)


def register(app: typer.Typer) -> None:
    app.command("start")(start)
    app.command("send")(send)
    app.command("verify")(verify)
    app.command("wait")(wait)
    app.command("activate")(activate)
    app.command("position")(position)
    app.command("emit")(emit)
    from .sessions_handshake import register as _register_handshake

    _register_handshake(app)


@usage(
    surface="st.sessions.verify",
    cmd="st -P PROJECT sessions verify UUID --source-key REVISION [--timeout SECONDS]",
    when="verify a prior native-thread delivery using its exact retained request/queue/client identity without message text",
    precautions=(
        "Read-only and bounded (>0, <=30 seconds); never resends, resumes, starts turns, or changes native queues. Timeout/unsupported protocol returns unknown.",
        "Only a correlated user-message clientId proves consumption. Queue absence is deleted-or-unknown; unrelated active turns do not prove this brief started.",
        "Reports queue, consumption with turn/item IDs, correlated execution status and offline/unloaded state without content. Queue/history reads are separate observations, not an atomic snapshot.",
        "Native-thread send remains <=2000 sanitized UTF-8 bytes and source-key idempotent; generation-fenced send and /clear remain owner-side gaps.",
    ),
    tier="reference",
)
def verify(
    thread: Annotated[str, typer.Argument(help="Exact native Codex UUID from the prior send receipt")],
    source_key: Annotated[str, typer.Option(help="Exact stable revision used by the prior native-thread send")],
    request_id: Annotated[str | None, typer.Option(help="Optional exact retained request ID guard")] = None,
    queue_id: Annotated[str | None, typer.Option(help="Optional exact native queue UUID guard")] = None,
    client_id: Annotated[str | None, typer.Option(help="Optional exact client-user-message UUID guard")] = None,
    timeout: Annotated[float, typer.Option(min=0.001, max=30, help="Bound for read-only native inspection; timeout returns unknown")] = 5,
) -> None:
    """Verify prior native delivery without message or terminal text; never resend.

    Queue absence means deleted-or-unknown. Only an exact correlated user-message
    clientId proves consumption; execution status belongs to that turn. Offline,
    timeout and unsupported protocol stay explicit. No generation fence or /clear.
    """
    from .sessions_native_delivery import verify_native_instruction

    try:
        result = verify_native_instruction(thread, project=get_project_override() or get_config().project_id,
                                           source_key=source_key, request_id=request_id, queue_id=queue_id,
                                           client_id=client_id, timeout=timeout)
    except (ValueError, OSError) as exc:
        # Never surface provider/transcript/DB contents through diagnostic text.
        raise typer.BadParameter("Native receipt identity or provenance is unavailable") from exc
    output_json(result)


def activate(root: str) -> None:
    """Show or reattach the exact owned root generation."""
    output_json(_call("activate", root))


def position(root: str, x: int, y: int, width: Annotated[int, typer.Argument(min=360)], height: Annotated[int, typer.Argument(min=240)]) -> None:
    """Arrange an Aico root through its generation-fenced owner endpoint."""
    output_json(_call("position", root, x=x, y=y, width=width, height=height))


def emit(
    root: str, event_type: str,
    source_key: Annotated[str, typer.Option(help="Stable source revision key; reuse on retry")],
    attributes: Annotated[str, typer.Option(help="Compact non-secret typed refs/delta JSON; no transcripts or private target data")],
) -> None:
    """Return a compact source revision to the fleet's durable advisory stream."""
    if event_type.startswith(("root.", "instruction.")):
        raise typer.BadParameter("Control events use their owning command")
    try:
        refs = json.loads(attributes)
        json.dumps(refs, allow_nan=False)
    except ValueError as exc:
        raise typer.BadParameter("Attributes must be a JSON object of compact source references") from exc
    if not isinstance(refs, dict):
        raise typer.BadParameter("Attributes must be a JSON object")
    output_json(_call("append", root, source_key=source_key, event_type=event_type, attributes=refs))
