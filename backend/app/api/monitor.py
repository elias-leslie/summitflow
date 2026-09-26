"""Owner-only HTTP adapter for the local host monitor query model."""

from __future__ import annotations

import threading
from ipaddress import ip_address
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from monitor_control import MonitorControlError, control_request, enrich_status, monitor_state_dir
from monitor_extended import export_capture, query_disk_space, run_benchmark
from monitor_observe import (
    ObserveQueryError,
    query_apps,
    query_connections,
    query_drivers,
    query_logs,
    query_sensors,
    query_startup,
    query_system_info,
    query_users,
)
from monitor_reader import MonitorQueryError, MonitorReader, MonitorSchemaError

from ..access_control import AccessPrincipal, require_owner
from .backups.key_endpoints import _require_same_origin

router = APIRouter(prefix="/api/monitor/v1", tags=["monitor"])

def require_monitor_owner(request: Request) -> AccessPrincipal:
    """Reject forwarded nonlocal callers that could inherit the desktop bypass."""
    principal = require_owner(request)
    if not principal.is_local_bypass:
        return principal
    # Caddy and Next.js append their peer addresses. Check every hop so a
    # client-supplied leftmost value cannot conceal a remote origin.
    for header in ("x-forwarded-for", "x-real-ip"):
        for values in request.headers.getlist(header):
            for value in values.split(","):
                value = value.strip()
                if not value:
                    continue
                try:
                    if not ip_address(value).is_loopback:
                        raise HTTPException(status_code=403, detail="Monitor requires local owner access")
                except ValueError as exc:
                    raise HTTPException(status_code=403, detail="Invalid forwarded client address") from exc
    return principal


Owner = Annotated[AccessPrincipal, Depends(require_monitor_owner)]
_diagnostic_slots = threading.BoundedSemaphore(2)


def _private(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"


class CaptureLeaseRequest(BaseModel):
    ttl_seconds: int = Field(default=30, ge=1, le=300)


class CaptureLeaseChange(CaptureLeaseRequest):
    lease_id: str


class BenchmarkRequest(BaseModel):
    kind: str
    duration_seconds: float = Field(default=1.0, gt=0, le=3)
    max_bytes: int = Field(default=4096, ge=512, le=65536)


def _read(method: str, **kwargs: Any) -> dict[str, Any]:
    try:
        return getattr(MonitorReader(monitor_state_dir()), method)(**kwargs)
    except MonitorSchemaError as exc:
        raise HTTPException(status_code=503, detail="Monitor store schema is incompatible") from exc
    except MonitorQueryError as exc:
        message = str(exc)
        if ("store unavailable" in message or "store read failed" in message
                or "store maintenance" in message or "malformed monitor store" in message):
            raise HTTPException(status_code=503, detail="Monitor history unavailable") from exc
        raise HTTPException(status_code=400, detail=message) from exc


def _control(command: str, **kwargs: Any) -> dict[str, Any]:
    try:
        response = control_request(command, **kwargs)
    except MonitorControlError as exc:
        raise HTTPException(status_code=503, detail="Monitor collector control unavailable") from exc
    if not response["ok"]:
        raise HTTPException(status_code=409, detail="Monitor collector rejected lease operation")
    return response


def _observe(query: Any, **kwargs: Any) -> dict[str, Any]:
    try:
        return query(**kwargs)
    except ObserveQueryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _export(**kwargs: Any) -> dict[str, Any]:
    try:
        return export_capture(MonitorReader(monitor_state_dir()), **kwargs)
    except ObserveQueryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except MonitorSchemaError as exc:
        raise HTTPException(status_code=503, detail="Monitor store schema is incompatible") from exc
    except MonitorQueryError as exc:
        raise HTTPException(status_code=503, detail="Monitor history unavailable") from exc


def _bounded(handler: Any, **kwargs: Any) -> dict[str, Any]:
    if not _diagnostic_slots.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="Monitor diagnostics are busy")
    try:
        return handler(**kwargs)
    finally:
        _diagnostic_slots.release()


@router.get("/status")
def status(_owner: Owner, response: Response, max_bytes: Annotated[int, Query(ge=512, le=65536)] = 4096) -> dict[str, Any]:
    _private(response)
    return enrich_status(_read("status", max_bytes=max_bytes), max_bytes)


@router.get("/series")
def series(
    _owner: Owner,
    response: Response,
    metric: str,
    entity: str = "host",
    since: str | None = None,
    until: str | None = None,
    step: Annotated[int, Query(ge=5, le=3600)] = 60,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
    cursor: str | None = None,
    max_bytes: Annotated[int, Query(ge=512, le=65536)] = 4096,
) -> dict[str, Any]:
    _private(response)
    if cursor and (since is None or until is None):
        raise HTTPException(status_code=400, detail="Cursor pages require explicit since and until")
    return _read("series", metric=metric, entity=entity, since=since, until=until,
                 step=step, limit=limit, cursor=cursor, max_bytes=max_bytes)


@router.get("/processes")
def processes(
    _owner: Owner,
    response: Response,
    at: str | None = None,
    name: str | None = None,
    user: str | None = None,
    service: str | None = None,
    sort: str = "rss",
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
    cursor: str | None = None,
    max_bytes: Annotated[int, Query(ge=512, le=65536)] = 4096,
) -> dict[str, Any]:
    _private(response)
    return _read("processes", at=at, name=name, user=user, service=service,
                 sort=sort, limit=limit, cursor=cursor, max_bytes=max_bytes)


@router.get("/events")
def events(
    _owner: Owner,
    response: Response,
    since: str | None = None,
    until: str | None = None,
    kind: str | None = None,
    severity: str | None = None,
    entity: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
    cursor: str | None = None,
    max_bytes: Annotated[int, Query(ge=512, le=65536)] = 4096,
) -> dict[str, Any]:
    _private(response)
    if cursor and (since is None or until is None):
        raise HTTPException(status_code=400, detail="Cursor pages require explicit since and until")
    return _read("events", since=since, until=until, kind=kind,
                 severity=severity, entity=entity, limit=limit, cursor=cursor, max_bytes=max_bytes)


@router.post("/capture")
def capture(_owner: Owner, response: Response, http_request: Request,
            request: CaptureLeaseRequest | None = None) -> dict[str, Any]:
    _require_same_origin(http_request)
    _private(response)
    return _control("lease_start", ttl_seconds=request.ttl_seconds if request else 30)


@router.post("/capture/renew")
def capture_renew(_owner: Owner, response: Response, http_request: Request,
                  request: CaptureLeaseChange) -> dict[str, Any]:
    _require_same_origin(http_request)
    _private(response)
    return _control("lease_renew", lease_id=request.lease_id, ttl_seconds=request.ttl_seconds)


@router.post("/capture/end")
def capture_end(_owner: Owner, response: Response, http_request: Request,
                request: CaptureLeaseChange) -> dict[str, Any]:
    _require_same_origin(http_request)
    _private(response)
    return _control("lease_end", lease_id=request.lease_id)


@router.get("/logs")
def logs(
    _owner: Owner, response: Response, service: str,
    since: str | None = None, until: str | None = None, cursor: str | None = None,
    priority: Annotated[int | None, Query(ge=0, le=7)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
    max_bytes: Annotated[int, Query(ge=512, le=65536)] = 4096,
) -> dict[str, Any]:
    _private(response)
    if cursor and (since is None or until is None):
        raise HTTPException(status_code=400, detail="Cursor pages require explicit since and until")
    return _observe(query_logs, service=service, since=since, until=until,
                    cursor=cursor, priority=priority, limit=limit, max_bytes=max_bytes)


@router.get("/sensors")
def sensors(_owner: Owner, response: Response,
            limit: Annotated[int, Query(ge=1, le=100)] = 10,
            max_bytes: Annotated[int, Query(ge=512, le=65536)] = 4096) -> dict[str, Any]:
    _private(response)
    return _observe(query_sensors, limit=limit, max_bytes=max_bytes)


@router.get("/connections")
def connections(_owner: Owner, response: Response,
                limit: Annotated[int, Query(ge=1, le=100)] = 10,
                show_addresses: bool = False, include_process: bool = False,
                max_bytes: Annotated[int, Query(ge=512, le=65536)] = 4096) -> dict[str, Any]:
    _private(response)
    return _observe(query_connections, limit=limit, max_bytes=max_bytes,
                    include_addresses=show_addresses, include_process=include_process)


@router.get("/system-info")
def system_info(_owner: Owner, response: Response,
                max_bytes: Annotated[int, Query(ge=512, le=65536)] = 4096) -> dict[str, Any]:
    _private(response)
    return _observe(query_system_info, max_bytes=max_bytes)


@router.get("/users")
def users(_owner: Owner, response: Response,
          limit: Annotated[int, Query(ge=1, le=100)] = 10,
          max_bytes: Annotated[int, Query(ge=512, le=65536)] = 4096) -> dict[str, Any]:
    _private(response)
    return _observe(query_users, limit=limit, max_bytes=max_bytes)


@router.get("/startup")
def startup(_owner: Owner, response: Response,
            limit: Annotated[int, Query(ge=1, le=100)] = 10,
            max_bytes: Annotated[int, Query(ge=512, le=65536)] = 4096) -> dict[str, Any]:
    _private(response)
    return _observe(query_startup, limit=limit, max_bytes=max_bytes)


@router.get("/apps")
def apps(_owner: Owner, response: Response,
         limit: Annotated[int, Query(ge=1, le=100)] = 10,
         max_bytes: Annotated[int, Query(ge=512, le=65536)] = 4096) -> dict[str, Any]:
    _private(response)
    return _observe(query_apps, limit=limit, max_bytes=max_bytes)


@router.get("/drivers")
def drivers(_owner: Owner, response: Response,
            limit: Annotated[int, Query(ge=1, le=100)] = 10,
            max_bytes: Annotated[int, Query(ge=512, le=65536)] = 4096) -> dict[str, Any]:
    _private(response)
    return _observe(query_drivers, limit=limit, max_bytes=max_bytes)


@router.get("/disk-space")
def disk_space(_owner: Owner, response: Response, path: str,
               max_entries: Annotated[int, Query(ge=1, le=10000)] = 1024,
               max_depth: Annotated[int, Query(ge=0, le=12)] = 6,
               timeout_seconds: Annotated[float, Query(gt=0, le=5)] = 2.0,
               limit: Annotated[int, Query(ge=1, le=100)] = 10,
               max_bytes: Annotated[int, Query(ge=512, le=65536)] = 4096) -> dict[str, Any]:
    _private(response)
    return _bounded(_observe, query=query_disk_space, path=path, max_entries=max_entries,
                    max_depth=max_depth, timeout_seconds=timeout_seconds,
                    limit=limit, max_bytes=max_bytes)


@router.post("/benchmark")
def benchmark(_owner: Owner, response: Response, http_request: Request,
              request: BenchmarkRequest) -> dict[str, Any]:
    _require_same_origin(http_request)
    _private(response)
    return _bounded(_observe, query=run_benchmark, kind=request.kind,
                    duration_seconds=request.duration_seconds, max_bytes=request.max_bytes)


@router.get("/export")
def capture_export(_owner: Owner, response: Response, since: str, until: str,
                   limit: Annotated[int, Query(ge=1, le=20)] = 10,
                   cursor: str | None = None,
                   max_bytes: Annotated[int, Query(ge=512, le=65536)] = 4096) -> dict[str, Any]:
    _private(response)
    return _bounded(_export, since=since, until=until, limit=limit,
                    cursor=cursor, max_bytes=max_bytes)
