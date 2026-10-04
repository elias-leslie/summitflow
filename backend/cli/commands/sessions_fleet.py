"""Fleet start/send/wait, registered on the existing sessions lifecycle."""

from __future__ import annotations

import json
import uuid
from typing import Annotated, Any

import typer
from st_sdk.fleet import FleetClient

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
) -> None:
    result = _call("start", project_id=get_project_override() or get_config().project_id,
                   tool=tool, surface=surface, instruction=instruction, scope=_scope(scope), role=role,
                   lead_root=lead_root, facet=facet, root=request_id or "root-" + uuid.uuid4().hex)
    output_json(result)


def send(
    root: str,
    instruction: Annotated[str, typer.Argument(help="Short non-secret instruction for the addressed root's wait stream; no credentials/private target data")],
    scope: Annotated[str, typer.Option(help="Must exactly match the root scope JSON")] = "{}",
    source_key: Annotated[str | None, typer.Option(help="Stable instruction revision key; reuse on retry")] = None,
) -> None:
    output_json(_call("send", root, instruction=instruction, scope=_scope(scope), source_key=source_key or "instruction:" + uuid.uuid4().hex))


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
    app.command("wait")(wait)
    app.command("activate")(activate)
    app.command("position")(position)
    app.command("emit")(emit)


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
