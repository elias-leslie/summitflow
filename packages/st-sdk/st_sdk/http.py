"""HTTP primitives for ST and project APIs."""

from __future__ import annotations

from typing import Any, cast

import httpx


class APIError(Exception):
    """API request error with status code and structured detail."""

    def __init__(self, status_code: int, detail: Any) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"[{status_code}] {detail}")


class BaseHTTPClient:
    """Base class providing ST project URL and response handling."""

    def __init__(
        self,
        base_url: str,
        project_id: str,
        timeout: float | None = 150.0,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.project_id = project_id
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> BaseHTTPClient:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def _url(self, path: str) -> str:
        return f"{self.base_url}/projects/{self.project_id}{path}"

    def _global_url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        if response.status_code >= 400:
            try:
                data = response.json()
                detail = data.get("detail", data) if isinstance(data, dict) else data
            except Exception:
                detail = response.text
            raise APIError(response.status_code, detail)
        return cast(dict[str, Any], response.json())

    def get(self, url: str) -> dict[str, Any]:
        return self._handle_response(self._client.get(url))

    def post(
        self,
        url: str,
        json: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return self._handle_response(self._client.post(url, json=json, params=params))

