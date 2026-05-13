"""Base HTTP client functionality for SummitFlow API."""

from __future__ import annotations

from typing import Any, cast

import httpx


class APIError(Exception):
    """API request error with status code and detail."""

    def __init__(self, status_code: int, detail: Any) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"[{status_code}] {detail}")


class BaseHTTPClient:
    """Base class providing HTTP request methods and response handling."""

    def __init__(self, base_url: str, project_id: str, timeout: float | None = 150.0) -> None:
        self.base_url = base_url
        self.project_id = project_id
        self._client = httpx.Client(timeout=timeout)

    def _url(self, path: str) -> str:
        """Build project-scoped URL."""
        return f"{self.base_url}/projects/{self.project_id}{path}"

    def _global_url(self, path: str) -> str:
        """Build non-project-scoped URL for global operations."""
        return f"{self.base_url}{path}"

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Handle response and raise APIError on failure."""
        if response.status_code >= 400:
            try:
                data = response.json()
                detail = data.get("detail", response.text)
            except Exception:
                detail = response.text
            raise APIError(response.status_code, detail)
        return cast(dict[str, Any], response.json())

    def get(self, url: str) -> dict[str, Any]:
        """Generic GET request to any URL."""
        response = self._client.get(url)
        return self._handle_response(response)

    def post(
        self,
        url: str,
        json: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Generic POST request to any URL."""
        response = self._client.post(url, json=json, params=params)
        return self._handle_response(response)
