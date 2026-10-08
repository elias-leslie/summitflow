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
    lead_root: str | None = None
    facet: str | None = Field(default=None, min_length=1, max_length=128)
    root: str | None = None
    resume_session: str | None = Field(default=None, min_length=1, max_length=128)


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


class Bounds(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: int = Field(ge=-100000, le=100000, strict=True)
    y: int = Field(ge=-100000, le=100000, strict=True)
    width: int = Field(ge=360, le=100000, strict=True)
    height: int = Field(ge=240, le=100000, strict=True)


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


@router.post("/roots/{root}/activate")
def activate(root: str, request: Request, response: Response) -> dict[str, Any]:
    _mutation(request, response)
    return _call(service.arrange_root, root)


@router.post("/roots/{root}/position")
def position(root: str, body: Bounds, request: Request, response: Response) -> dict[str, Any]:
    _mutation(request, response)
    return _call(service.arrange_root, root, bounds=body.model_dump())


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
