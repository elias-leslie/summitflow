"""Browser endpoint helpers for live sessions."""

from __future__ import annotations

from fastapi import HTTPException

from ...services.browser_targets import BrowserTargetError, resolve_browser_endpoint
from .live_session_models import BrowserTargetStatus


def _browser_target_status() -> BrowserTargetStatus:
    try:
        endpoint = resolve_browser_endpoint(live=True)
    except BrowserTargetError:
        return BrowserTargetStatus()
    return BrowserTargetStatus(
        host=endpoint.host,
        port=endpoint.port,
        source=endpoint.source,
        debug_local=endpoint.debug_local,
    )


def _browser_endpoint() -> tuple[str, int]:
    try:
        endpoint = resolve_browser_endpoint(live=True)
    except BrowserTargetError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return endpoint.host, endpoint.port


def _normalize_ws_url(ws_url: str, host: str) -> str:
    return ws_url.replace("ws://0.0.0.0:", f"ws://{host}:").replace(
        "ws://127.0.0.1:",
        f"ws://{host}:",
    )
