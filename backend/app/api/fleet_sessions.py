"""Versioned, owner-authenticated fleet control and compact source append seam."""

from __future__ import annotations

import asyncio
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from ..services import fleet_sessions as service
from ..storage.fleet_events import (
    SourceKeyConflict,
    StaleCursor,
    append_fleet_event,
    list_fleet_roots,
)
from ..storage.projects import get_project_root_path
from .backups.key_endpoints import _require_same_origin
from .monitor import require_monitor_owner

router = APIRouter(prefix="/fleet/v1", dependencies=[Depends(require_monitor_owner)])
# Agents call this one (st sessions send on an agent host, with the agent token),
# so it keeps the app-wide owner-or-agent check instead of the owner-only one.
coordination_router = APIRouter(prefix="/fleet/v1")


def _mutation(request: Request, response: Response) -> None:
    # Non-browser authenticated clients carry no Origin. Browser requests must
    # match origin and the existing owner/forwarded-address authorization.
    if request.headers.get("origin") or request.headers.get("sec-fetch-site"):
        _require_same_origin(request)
    response.headers["Cache-Control"] = "no-store"


def _call(fn: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return fn(*args, **kwargs)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SourceKeyConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class StartRoot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str
    tool: Literal["codex", "claude-code"] = "codex"
    surface: service.RootSurface = "aico"
    instruction: str = Field(min_length=1, max_length=4000)
    scope: dict[str, str] = Field(default_factory=dict)
    role: service.RootRole = "portfolio-root"
    work_role: str | None = Field(default=None, min_length=1, max_length=128)
    work_role_name: str | None = Field(default=None, min_length=1, max_length=128)
    lead_root: str | None = None
    facet: str | None = Field(default=None, min_length=1, max_length=128)
    root: str | None = None
    resume_session: str | None = Field(default=None, min_length=1, max_length=128)
    execution_root: str | None = Field(default=None, min_length=1, max_length=4096)


class Instruction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instruction: str = Field(min_length=1, max_length=4000)
    source_key: str = Field(min_length=1, max_length=256)
    scope: dict[str, str] = Field(default_factory=dict)


class SourceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_key: str = Field(min_length=1, max_length=256)
    event_type: str = Field(min_length=1, max_length=128)
    attributes: dict[str, Any]
    digest: str = Field(pattern="^[0-9a-f]{64}$")


class HostRequest(BaseModel):
    """A coordination request from an agent on an agent host (cli/lib/coord_remote.py)."""

    model_config = ConfigDict(extra="forbid")
    target: str = Field(min_length=1, max_length=256)
    text: str = Field(min_length=1, max_length=2000)
    sender: str = Field(min_length=1, max_length=128)
    host: str = Field(min_length=1, max_length=32)
    reply_to: str | None = Field(default=None, min_length=8, max_length=8)


@coordination_router.post("/coordination/requests")
def host_request(body: HostRequest, request: Request, response: Response) -> dict[str, Any]:
    """Record a host agent's st sessions send in this computer's ledger; the
    host's own ledger cannot hold a request for an agent here."""
    from cli.lib import coord_remote

    _mutation(request, response)
    row = _call(coord_remote.record_from_host, body.target, body.text, sender=body.sender,
                host=body.host, reply_to=body.reply_to)
    return {key: row.get(key) for key in ("id", "to", "state", "duplicate")}


class HostAck(BaseModel):
    """A host agent's st sessions ack for a request this ledger holds for its window."""

    model_config = ConfigDict(extra="forbid")
    intent: str = Field(min_length=1, max_length=16)
    note: str | None = Field(default=None, max_length=2000)
    sender: str = Field(min_length=1, max_length=128)
    host: str = Field(min_length=1, max_length=32)
    window: str = Field(min_length=8, max_length=8)


class HostConfirm(BaseModel):
    """A host agent's st sessions confirm for a request it sent here."""

    model_config = ConfigDict(extra="forbid")
    senders: list[str] = Field(min_length=1, max_length=16)
    host: str = Field(min_length=1, max_length=32)
    withdraw: bool = False


_ROW_KEYS = ("id", "from", "to", "state", "intent", "eta_min", "note", "acked_by", "withdrawn")


@coordination_router.post("/coordination/requests/{message_id}/ack")
def host_ack(message_id: str, body: HostAck, request: Request, response: Response) -> dict[str, Any]:
    from cli.lib import coord_remote

    _mutation(request, response)
    row = _call(coord_remote.ack_from_host, message_id, body.intent, body.note, sender=body.sender,
                host=body.host, window=body.window)
    return {key: row.get(key) for key in _ROW_KEYS}


@coordination_router.post("/coordination/requests/{message_id}/confirm")
def host_confirm(message_id: str, body: HostConfirm, request: Request, response: Response) -> dict[str, Any]:
    from cli.lib import coord_remote

    _mutation(request, response)
    row = _call(coord_remote.confirm_from_host, message_id, senders=body.senders, host=body.host,
                withdraw=body.withdraw)
    return {key: row.get(key) for key in _ROW_KEYS}


@coordination_router.get("/coordination/requests")
def host_inbox(response: Response, host: str, sender: Annotated[list[str], Query(max_length=16)],
               window: str | None = None) -> dict[str, Any]:
    """A host agent's st sessions inbox: what this ledger holds for or from it."""
    from cli.lib import coord_remote

    response.headers["Cache-Control"] = "no-store"
    rows = _call(coord_remote.inbox_for_host, senders=sender, host=host, window=window)
    return {"requests": [{key: row.get(key) for key in (*_ROW_KEYS, "text")} for row in rows]}


@router.post("/roots")
def start(body: StartRoot, request: Request, response: Response) -> dict[str, Any]:
    _mutation(request, response)
    project_root = get_project_root_path(body.project_id)
    if not project_root:
        raise HTTPException(status_code=404, detail="Project has no registered root")
    return _call(service.start_root, project_root=project_root, **body.model_dump())


@router.get("/roots")
def roots(response: Response, project_id: str | None = None, limit: Annotated[int, Query(ge=1, le=100)] = 20) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return {"roots": [service.root_state(root) for root in list_fleet_roots(project_id, limit=limit)]}


@router.get("/roots/{root}")
def show(root: str, response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return _call(service.reconcile_root, root)


@router.post("/roots/{root}/send")
def send(root: str, body: Instruction, request: Request, response: Response) -> dict[str, Any]:
    _mutation(request, response)
    return _call(service.send_instruction, root, **body.model_dump())


@router.post("/roots/{root}/close")
def close(root: str, request: Request, response: Response) -> dict[str, Any]:
    _mutation(request, response)
    return _call(service.close_root, root)


@router.post("/roots/{root}/events")
def append(root: str, body: SourceEvent, request: Request, response: Response) -> dict[str, Any]:
    _mutation(request, response)
    state = _call(service.root_state, root)
    if body.event_type.startswith(("root.", "instruction.")):
        raise HTTPException(status_code=422, detail="Control events use their owning command")
    return _call(append_fleet_event, state["project_id"], root, require_open=True, **body.model_dump())


@router.get("/roots/{root}/wait")
async def wait(
    root: str, request: Request, response: Response,
    cursor: Annotated[int, Query(ge=0)] = 0,
    timeout: Annotated[float, Query(ge=0, le=300)] = 300,
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    pending = asyncio.create_task(service.wait_events(root, cursor=cursor, timeout=timeout))
    try:
        while not pending.done():
            if await request.is_disconnected():
                raise asyncio.CancelledError
            await asyncio.wait({pending}, timeout=0.25)
        return await pending
    except StaleCursor as exc:
        raise HTTPException(status_code=409, detail={
            "code": "stale_cursor", "cursor": exc.cursor, "next_sequence": exc.next_sequence,
        }) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
