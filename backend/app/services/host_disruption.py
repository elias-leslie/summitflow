"""The Runtime page's view of "may I disrupt this host now?", from the same snapshot as st sessions may-disrupt."""

from __future__ import annotations

from typing import Any

import httpx
from agent_hub.exceptions import ServerError
from starlette.concurrency import run_in_threadpool

from app.services._agent_hub_config import get_async_client, resolve_agent_hub_request_source
from app.storage import backups as backup_store
from cli.lib import coord_disrupt

_TIMEOUT = 10.0


async def _active_sessions() -> list[dict[str, Any]]:
    source = resolve_agent_hub_request_source("summitflow-host-disruption")
    async with get_async_client(timeout=_TIMEOUT, request_source=source) as client:
        listing = await client.list_sessions(None, "active", page=1, page_size=100)
    return [session.model_dump(mode="json") for session in listing.sessions]


async def host_disruption(target: str = coord_disrupt.HOST_TARGET) -> dict[str, Any]:
    sessions: list[dict[str, Any]] | None = None
    failure: Exception | None = None
    try:
        sessions = await _active_sessions()
    except (httpx.HTTPError, ServerError, OSError) as exc:
        failure = exc

    def _sessions() -> list[dict[str, Any]]:
        if failure is not None:
            raise failure
        return sessions or []

    def _running() -> list[dict[str, Any]]:
        rows, _ = backup_store.list_backups(status="running", limit=50)
        return rows

    return await run_in_threadpool(
        coord_disrupt.snapshot, target, everyone=True, sessions=_sessions, running_backups=_running
    )
