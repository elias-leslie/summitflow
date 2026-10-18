"""API client for SummitFlow Tasks."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from ._client_base import APIError, BaseHTTPClient
from ._client_mixins import (
    DependencyOperationsMixin,
    ExecutionOperationsMixin,
    SubtaskOperationsMixin,
    TaskOperationsMixin,
    TestOperationsMixin,
)
from ._client_mixins_tasks import _TaskWorkflowMixin

_COMMAND_TOKEN = re.compile(r"^[a-z][a-z0-9_-]{0,30}$")


def request_source() -> str:
    """Name the st subcommand for the backend's request usage log."""
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    return f"st-cli/{command}" if _COMMAND_TOKEN.match(command) else "st-cli"


def agent_token_headers() -> dict[str, str]:
    """The agent token header when SUMMITFLOW_AGENT_TOKEN_FILE names a readable file, else nothing."""
    path = os.environ.get("SUMMITFLOW_AGENT_TOKEN_FILE", "").strip()
    try:
        token = Path(path).read_text(encoding="utf-8").strip() if path else ""
    except (OSError, ValueError):
        return {}
    return {"X-SummitFlow-Agent-Token": token} if token else {}


class STClient(
    BaseHTTPClient,
    TaskOperationsMixin,
    _TaskWorkflowMixin,
    DependencyOperationsMixin,
    TestOperationsMixin,
    SubtaskOperationsMixin,
    ExecutionOperationsMixin,
):
    """HTTP client for SummitFlow Tasks API."""

    def __init__(
        self,
        base_url: str | None = None,
        project_id: str | None = None,
        timeout: float | None = 330.0,  # Allow time for regular API operations
        require_project: bool = True,
    ) -> None:
        from .config import get_config, get_config_optional

        if require_project:
            config = get_config()
            resolved_base_url = base_url or config.api_base
            resolved_project_id = project_id or config.project_id
        else:
            config = get_config_optional()
            resolved_base_url = base_url or config.api_base
            resolved_project_id = project_id or config.project_id

        super().__init__(resolved_base_url, resolved_project_id, timeout)
        self._client.headers.setdefault("X-Request-Source", request_source())
        self._client.headers.update(agent_token_headers())


__all__ = ["APIError", "STClient"]
