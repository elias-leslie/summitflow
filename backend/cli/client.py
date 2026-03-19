"""API client for SummitFlow Tasks."""

from __future__ import annotations

from ._client_base import APIError, BaseHTTPClient
from ._client_mixins import (
    DependencyOperationsMixin,
    ExecutionOperationsMixin,
    SubtaskOperationsMixin,
    TaskOperationsMixin,
    TestOperationsMixin,
)


class STClient(
    BaseHTTPClient,
    TaskOperationsMixin,
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
        timeout: float = 330.0,  # Allow time for long API operations
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


__all__ = ["APIError", "STClient"]
