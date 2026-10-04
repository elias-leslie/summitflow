"""Public versioned fleet client; telemetry is advisory and source-revision keyed."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from urllib.parse import quote

from st_sdk.http import BaseHTTPClient


class FleetClient:
    """Reuse an authenticated ST HTTP client without importing backend internals."""

    def __init__(self, client: BaseHTTPClient) -> None:
        self.client = client

    def _url(self, root: str = "", suffix: str = "") -> str:
        path = "/fleet/v1/roots"
        if root:
            path += "/" + quote(root, safe="")
        return self.client._global_url(path + suffix)

    def start(self, **capsule: Any) -> dict[str, Any]:
        return self.client.post(self._url(), json=capsule)

    def show(self, root: str) -> dict[str, Any]:
        return self.client.get(self._url(root))

    def list(self, project_id: str | None = None, limit: int = 20) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if project_id:
            params["project_id"] = project_id
        return self.client._handle_response(self.client._client.get(self._url(), params=params))

    def send(self, root: str, *, instruction: str, source_key: str, scope: dict[str, str]) -> dict[str, Any]:
        return self.client.post(self._url(root, "/send"), json={
            "instruction": instruction, "source_key": source_key, "scope": scope,
        })

    def wait(self, root: str, *, cursor: int = 0, timeout: float = 300) -> dict[str, Any]:
        response = self.client._client.get(self._url(root, "/wait"), params={"cursor": cursor, "timeout": timeout}, timeout=timeout + 30)
        return self.client._handle_response(response)

    def close(self, root: str) -> dict[str, Any]:
        return self.client.post(self._url(root, "/close"))

    def activate(self, root: str) -> dict[str, Any]:
        return self.client.post(self._url(root, "/activate"))

    def position(self, root: str, *, x: int, y: int, width: int, height: int) -> dict[str, Any]:
        return self.client.post(self._url(root, "/position"), json={"x": x, "y": y, "width": width, "height": height})

    def append(self, root: str, *, source_key: str, event_type: str, attributes: dict[str, Any]) -> dict[str, Any]:
        """Caller supplies sanitized compact refs, not transcript/terminal content."""
        encoded = json.dumps([event_type, attributes], sort_keys=True, separators=(",", ":"), allow_nan=False)
        return self.client.post(self._url(root, "/events"), json={
            "source_key": source_key, "event_type": event_type, "attributes": attributes,
            "digest": hashlib.sha256(encoded.encode()).hexdigest(),
        })
