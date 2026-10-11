"""Per-request usage log for value audits.

One JSON line per HTTP request goes to backend/logs/access.log, rotated daily
and kept for 35 days. A line holds only the route template, never the raw path,
query string, headers or body, so IDs, tokens and emails stay out of it.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import re
import time
from datetime import UTC, datetime
from pathlib import Path

from starlette.types import ASGIApp, Message, Receive, Scope, Send

ACCESS_LOGGER_NAME = "summitflow.access"
_DEFAULT_LOG_DIR = Path(__file__).resolve().parents[1] / "logs"
_LOG_FILE = "access.log"
_BACKUP_DAYS = 35
_SKIPPED_PATHS = ("/health", "/api/health")
_CALLER_MAX_CHARS = 40
_UNSAFE_CALLER_CHARS = re.compile(r"[^A-Za-z0-9._/+-]")

access_logger = logging.getLogger(ACCESS_LOGGER_NAME)
access_logger.propagate = False
access_logger.setLevel(logging.INFO)


def configure_access_log(log_dir: Path = _DEFAULT_LOG_DIR) -> None:
    """Attach the rotating access.log handler (idempotent)."""
    if access_logger.handlers:
        return
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.TimedRotatingFileHandler(
        filename=str(log_dir / _LOG_FILE),
        when="midnight",
        backupCount=_BACKUP_DAYS,
        encoding="utf-8",
        utc=True,
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    access_logger.addHandler(handler)


def _header(scope: Scope, name: bytes) -> str:
    for key, value in scope.get("headers") or ():
        if key.lower() == name:
            return value.decode("latin-1")
    return ""


def caller_token(scope: Scope) -> str:
    """Name the calling product, e.g. 'st-cli/commit', 'python-httpx' or 'Mozilla'."""
    source = _header(scope, b"x-request-source").strip()
    if source:
        token = source.split()[0]
    else:
        agent = _header(scope, b"user-agent").strip()
        token = agent.split()[0].split("/")[0] if agent else ""
    if "@" in token:
        return "redacted"
    token = _UNSAFE_CALLER_CHARS.sub("", token)[:_CALLER_MAX_CHARS]
    return token or "unknown"


def route_template(scope: Scope) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) and path else "unmatched"


def _skipped(path: str) -> bool:
    return any(path == skip or path.startswith(f"{skip}/") for skip in _SKIPPED_PATHS)


class AccessLogMiddleware:
    """Pure ASGI middleware so it sees the route FastAPI matched."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or not access_logger.handlers
            or _skipped(scope.get("path", ""))
        ):
            await self.app(scope, receive, send)
            return

        status = 500
        started = time.perf_counter()

        async def send_with_status(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, send_with_status)
        finally:
            access_logger.info(
                json.dumps(
                    {
                        "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
                        "method": scope.get("method", ""),
                        "route": route_template(scope),
                        "status": status,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                        "caller": caller_token(scope),
                    },
                    separators=(",", ":"),
                )
            )
