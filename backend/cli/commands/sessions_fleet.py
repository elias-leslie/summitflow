"""Fleet start/send/wait, registered on the existing sessions lifecycle."""

from __future__ import annotations

import json
import re
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


_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)


def _agent_hub_sessions() -> list[dict[str, Any]]:
    """Agent Hub sessions a label may name; empty when Agent Hub is unreachable.

    Active sessions, plus completed ones whose harness is still live: Agent Hub
    marks an idle Claude Code session completed between turns.
    """
    from ..lib import coord_route

    try:
        client = STClient(require_project=False)
        rows = client.list_sessions(status="active", limit=100)
        live = coord_route.live_sessions()
        rows += [row for row in client.list_sessions(status="completed", limit=100)
                 if isinstance(row, dict) and str(row.get("id") or "") in live]
        return rows
    except (APIError, OSError, ValueError):
        return []


def _tether_aliases(target: str) -> list[str]:
    """Widget ids and tmux names of Aico/Tether windows named exactly (case-insensitive).

    A window answers to its widget id, its st aico create request id, or its
    title; its live harness can resolve without an Agent Hub session record.
    """
    from ..lib import coord_remote

    out: list[str] = []
    for item in coord_remote.windows(target):
        tmux = item.get("tmux")
        tmux_name = tmux.get("sessionName") if isinstance(tmux, dict) else None
        out.extend(value for value in (item.get("id"), tmux_name) if isinstance(value, str) and value)
    return out


def _resolve_agent(target: str) -> str:
    """An agent id, a known session prefix, or a label naming exactly one live agent; else exit 2."""
    from ..lib import coord, coord_route, coordinators

    if coord_route.AGENT_ID.fullmatch(target) or coord.known_target(target):
        return target
    sessions = _agent_hub_sessions()
    found, unreachable = coord_route.resolve_label(target, sessions)
    if not found:
        for alias in dict.fromkeys([target.strip().casefold(), *_tether_aliases(target)]):
            agent = coordinators.agent_for_widget(alias)
            if agent:
                found.setdefault(agent, f"aico widget {alias}")
            for aid, how in coord_route.resolve_label(alias, sessions)[0].items():
                found.setdefault(aid, f"aico window {alias}, {how}")
    if len(found) == 1:
        agent_id = next(iter(found))
        typer.echo(f"→ {agent_id}")
        return agent_id
    candidates = [f"{aid} ({how})" for aid, how in sorted(found.items())] + unreachable
    if found:
        typer.echo(f"ERROR {target!r} names {len(found)} live agents; send to one id: " + "; ".join(candidates), err=True)
    else:
        live = ", ".join(coord.live_agents()) or "none"
        detail = f" Candidates: {'; '.join(candidates)}." if candidates else ""
        typer.echo(f"ERROR {target!r} names no live agent.{detail} Live agents: {live}. Address an agent id, "
                   "an Aico window's widget id, st aico create request id or title; fleet-started root-* "
                   "handles go to the fleet stream.", err=True)
    raise typer.Exit(2)


def _send_across_machines(target: str, text: str) -> bool:
    """A window on an agent host gets the text through the Tether hub; on an agent
    host, a target that is none of its own agents goes to the workstation."""
    from ..lib import coord_remote

    try:
        if window := coord_remote.to_host_window(target, text):
            typer.echo(f"sent to window {window['id']} on {window['host']}; it has no ledger here, "
                       "so its answer comes back as a new request to you")
            return True
        host = coord_remote.agent_host()
        if not host or coord_remote.names_local_agent(target):
            return False
        agent_id, widget = coord_remote._sender()
        client = STClient(require_project=False)
        row = client.post(client._global_url("/fleet/v1/coordination/requests"), json={
            "target": target, "text": text, "sender": agent_id, "host": host, "reply_to": widget or None})
    except ValueError as exc:
        typer.echo(f"ERROR {exc}", err=True)
        raise typer.Exit(2) from exc
    except APIError as exc:
        handle_api_error(exc)
        raise typer.Exit(1) from exc
    typer.echo(f"sent {row.get('id')} -> {row.get('to')} on the workstation; it answers with st sessions send")
    return True


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
    surface: Annotated[str, typer.Option(help="Owner surface: aico, tether or a-term. aico goes through Tether when it is running, else Aico's sockets")] = "aico",
    scope: Annotated[str, typer.Option(help="Exact scope/source references as JSON")] = "{}",
    role: Annotated[str, typer.Option(help="portfolio-root, neri-target-root, or neri-support-root")] = "portfolio-root",
    work_role: Annotated[str | None, typer.Option(help="Fixed native-session work role; required for new roots, separate from --role")] = None,
    work_role_name: Annotated[str | None, typer.Option(help="Optional work-role display name (1-128 characters)")] = None,
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
    if work_role is not None:
        capsule["work_role"] = work_role
    if work_role_name is not None:
        capsule["work_role_name"] = work_role_name
    if resume_session is not None:
        capsule["resume_session"] = resume_session
    if execution_root is not None:
        capsule["execution_root"] = execution_root
    output_json(_call("start", **capsule))


@usage(
    surface="st.sessions.send",
    cmd="st sessions send AGENT_OR_WINDOW 'question' | st sessions ack ID yes|no 'reason'|eta:MIN | st sessions confirm ID [--withdraw]",
    when="ask another agent a question (<=500 chars; a brief file only for long material): it acks, you confirm",
    precautions=("address the coordinating parent; workers answer only their own requests; "
                 "don't-touch: st lease --hold; fleet roots/native threads: --help",),
    tier="reference",
)
def send(
    root: str,
    instruction: Annotated[str, typer.Argument(help="Short non-secret instruction for the fleet root or exact native thread; no credentials/private target data")],
    scope: Annotated[str, typer.Option(help="Must exactly match the root scope JSON")] = "{}",
    source_key: Annotated[str | None, typer.Option(help="Stable instruction revision key; reuse on retry")] = None,
    delivery: Annotated[Literal["fleet-stream", "native-thread", "handshake"] | None, typer.Option(help="Default: handshake for agent ids/labels, fleet-stream for root-*/UUIDs")] = None,
) -> None:
    """Send to another agent: agent ids/labels -> handshake; root-* handles and UUIDs -> fleet stream.

    Handshake (<=500 chars, else a brief file): recipient acks yes, no 'reason' or eta:MIN; then
    st sessions confirm (--withdraw if unacked). Only channel; never also type it in the window.
    Labels (Aico widget/title/tmux, session name, short id) must match one live agent.

    Native-thread: bound Codex UUID, stable --source-key, <=2000 bytes; woken if live, else queued.
    Retry with the same --source-key; st sessions verify UUID --source-key REV. No secrets.
    """
    if delivery is None:
        # Coordination agent ids are never fleet roots; route them to the ledger.
        # Fleet handles and UUIDs keep the fleet stream; anything else is a label.
        fleet = root.startswith("root-") or _UUID.fullmatch(root)
        delivery = "fleet-stream" if fleet else "handshake"
    if delivery == "handshake":
        from .sessions_handshake import send_request

        if _send_across_machines(root, instruction):
            return
        send_request(_resolve_agent(root), instruction, source_key)
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
    cmd="st sessions wait ROOT --cursor SEQ | --until idle,blocked [--timeout S]",
    when="read a fleet root's stream, or wait for a session's agent state",
    precautions=("Carry the cursor; quiet timeout prints nothing. --until exits 1 on timeout.",),
    tier="reference",
)
def wait(
    root: str,
    cursor: Annotated[int, typer.Option(min=0, help="Exclusive durable stream sequence cursor")] = 0,
    timeout: Annotated[float, typer.Option(min=0, max=300, help="Quiet wait seconds (default 300)")] = 300,
    until: Annotated[str | None, typer.Option(help="Wait until the session's agent state is one of these (comma list of working, idle, blocked, unknown) instead of reading the fleet stream")] = None,
) -> None:
    if until is not None:
        _wait_for_state(root, _states(until), timeout)
        return
    result = _call("wait", root, cursor=cursor, timeout=timeout)
    if result.get("events"):
        output_json(result)


AGENT_STATES = ("working", "idle", "blocked", "unknown")
_SESSION_ID = re.compile(r"[0-9a-f]{8}")
_STATE_POLL_SECONDS = 1.0


def _states(value: str) -> set[str]:
    states = {part.strip() for part in value.split(",") if part.strip()}
    unknown = states - set(AGENT_STATES)
    if not states or unknown:
        raise typer.BadParameter(f"--until takes a comma list of {', '.join(AGENT_STATES)}")
    return states


def _tether_get(path: str) -> dict[str, Any]:
    from urllib.parse import quote

    from app.services import tether

    try:
        status, body = tether.request_first("GET", quote(path))
    except (OSError, ValueError) as exc:
        typer.echo(f"ERROR Tether is not reachable at {tether.socket_path()}: {exc}", err=True)
        raise typer.Exit(2) from exc
    if status != 200 or not isinstance(body, dict):
        code = body.get("error") if isinstance(body, dict) else None
        typer.echo(f"ERROR Tether answered {status} for {path}" + (f" ({code})" if code else ""), err=True)
        raise typer.Exit(2)
    return body


def _session_id(target: str) -> str:
    """An 8-hex Tether session ID as given, else the session behind a root request ID."""
    if _SESSION_ID.fullmatch(target):
        return target
    host = _tether_get(f"/v1/roots/{target}").get("hostIdentity")
    if not isinstance(host, str) or not _SESSION_ID.fullmatch(host):
        typer.echo(f"ERROR root {target!r} has no Tether session", err=True)
        raise typer.Exit(2)
    return host


def _wait_for_state(target: str, states: set[str], timeout: float) -> None:
    import time

    session = _session_id(target)
    deadline = time.monotonic() + timeout
    while True:
        descriptor = _tether_get(f"/v1/sessions/{session}")
        state = descriptor.get("state")
        if state is None:
            typer.echo("ERROR this Tether does not report agent state; update Tether", err=True)
            raise typer.Exit(2)
        if state in states:
            output_json({key: descriptor.get(key) for key in ("id", "state", "stateSource", "stateAt", "stateDetail")})
            return
        if time.monotonic() >= deadline:
            typer.echo(f"Timed out after {timeout:g}s; {session} is {state}", err=True)
            raise typer.Exit(1)
        time.sleep(min(_STATE_POLL_SECONDS, max(0.0, deadline - time.monotonic())))


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
    when="check a prior native-thread send by its retained identity (no message text)",
    precautions=(
        "read-only, <=30s; never resends or starts turns; timeout or unsupported protocol = unknown",
        "only a correlated clientId proves consumption; an ack is not execution proof; expired receipts = unknown",
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

    Live sends read their exact coordination inbox receipt: queued, seen, acked
    or closed. An ack proves a reply, not task execution. Offline sends inspect
    native queue/history; only the correlated clientId proves consumption and
    execution belongs to that turn. Expired receipts and timeouts stay unknown.
    No generation fence or /clear.
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
