"""Small public ST client for owner project APIs and task promotion."""

from __future__ import annotations

from typing import Any

import httpx

from .config import get_config, get_config_optional
from .http import BaseHTTPClient


class STClient(BaseHTTPClient):
    """Generic JSON client scoped to a selected SummitFlow project."""

    def __init__(
        self,
        base_url: str | None = None,
        project_id: str | None = None,
        timeout: float | None = 330.0,
        require_project: bool = True,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        resolved_base_url = base_url
        resolved_project_id = project_id
        if base_url is None or project_id is None:
            config = get_config() if require_project else get_config_optional()
            resolved_base_url = base_url or config.api_base
            resolved_project_id = project_id or config.project_id
        assert resolved_base_url is not None
        assert resolved_project_id is not None
        super().__init__(
            resolved_base_url,
            resolved_project_id,
            timeout,
            transport=transport,
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        project_scoped: bool = True,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Request a project-scoped API path, or a global path when requested."""
        if not path.startswith("/"):
            path = f"/{path}"
        url = self._url(path) if project_scoped else self._global_url(path)
        response = self._client.request(method, url, params=params, json=json)
        return self._handle_response(response)

    def create_task(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a task in the selected project (the Learn promotion seam)."""
        return self.request("POST", "/tasks", json=data)
