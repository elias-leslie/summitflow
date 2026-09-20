"""Resolve and call a SummitFlow-managed project's own API."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import httpx

from .config import get_api_base
from .http import APIError


@dataclass(frozen=True)
class ProjectApi:
    project_id: str
    env_var: str
    default_url: str


@dataclass(frozen=True)
class ResolvedURL:
    url: str
    source: str


class ProjectApiConnectError(Exception):
    def __init__(self, url: str, detail: str) -> None:
        self.url = url
        self.detail = detail
        super().__init__(f"unreachable: {url} ({detail})")


def _identity_for(repo_root: Path) -> dict[str, Any] | None:
    identity = repo_root / "project.identity.json"
    if not identity.is_file():
        return None
    try:
        return cast(dict[str, Any], json.loads(identity.read_text()))
    except (OSError, json.JSONDecodeError):
        return None


def _walk_for_repo(api: ProjectApi, start: Path) -> Path | None:
    for candidate in [start, *start.parents]:
        identity = _identity_for(candidate)
        if identity and identity.get("project", {}).get("id") == api.project_id:
            return candidate
    return None


def _from_ports_json(repo_root: Path) -> str | None:
    ports_file = repo_root / "ports.json"
    if not ports_file.is_file():
        return None
    try:
        data = json.loads(ports_file.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    api_url = data.get("api_url")
    if isinstance(api_url, str) and api_url.strip():
        return api_url.strip().rstrip("/")
    backend_port = data.get("backend_port")
    if isinstance(backend_port, int) and backend_port > 0:
        return f"http://localhost:{backend_port}"
    return None


def _from_identity_local(repo_root: Path) -> str | None:
    identity = _identity_for(repo_root)
    if not identity:
        return None
    backend_port = identity.get("runtime", {}).get("backend_port")
    if isinstance(backend_port, int) and backend_port > 0:
        return f"http://localhost:{backend_port}"
    return None


def _registry_root(api: ProjectApi) -> Path | None:
    api_base = get_api_base()
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.get(f"{api_base}/projects/{api.project_id}")
    except httpx.HTTPError:
        return None
    if response.status_code != 200:
        return None
    try:
        payload = response.json()
    except ValueError:
        return None
    root_path = payload.get("root_path")
    if not isinstance(root_path, str) or not root_path:
        return None
    repo_root = Path(root_path)
    return repo_root if repo_root.is_dir() else None


def _from_remote(api: ProjectApi, start: Path) -> str | None:
    repo_root = _walk_for_repo(api, start) or _registry_root(api)
    identity = _identity_for(repo_root) if repo_root else None
    if not identity:
        return None
    host = identity.get("hosts", {}).get("production_api")
    if isinstance(host, str) and host.strip():
        return f"https://{host.strip()}"
    return None


def resolve_api_url(
    api: ProjectApi, *, remote: bool = False, cwd: Path | None = None
) -> ResolvedURL:
    env_url = os.environ.get(api.env_var)
    if env_url and env_url.strip():
        return ResolvedURL(env_url.strip().rstrip("/"), "env")
    start = (cwd or Path.cwd()).resolve()
    repo_root = _walk_for_repo(api, start)
    if repo_root is not None:
        if ports_url := _from_ports_json(repo_root):
            return ResolvedURL(ports_url, "ports_json")
        if identity_url := _from_identity_local(repo_root):
            return ResolvedURL(identity_url, "identity")
    if (registry_root := _registry_root(api)) and (
        registry_url := _from_identity_local(registry_root)
    ):
        return ResolvedURL(registry_url, "registry")
    if remote and (remote_url := _from_remote(api, start)):
        return ResolvedURL(remote_url, "remote")
    return ResolvedURL(api.default_url, "default")


class ProjectApiClient:
    """Minimal JSON client for a managed project's own backend."""

    def __init__(self, base_url: str, *, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> ProjectApiClient:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def _full(self, path: str) -> str:
        return f"{self.base_url}{path}" if path.startswith("/") else f"{self.base_url}/{path}"

    def _handle(self, response: httpx.Response) -> Any:
        if response.status_code >= 400:
            try:
                payload = response.json()
                detail = payload.get("detail", payload)
            except ValueError:
                detail = response.text
            raise APIError(response.status_code, detail)
        if response.status_code == 204:
            return None
        try:
            return response.json()
        except ValueError:
            return response.text

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        url = self._full(path)
        try:
            response = self._client.request(method, url, params=params, json=json_body)
        except httpx.HTTPError as exc:
            raise ProjectApiConnectError(url, str(exc)) from exc
        return self._handle(response)

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        return self._request("GET", path, params=params)

    def post(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        return self._request("POST", path, params=params, json_body=json_body)

    def patch(self, path: str, *, json_body: dict[str, Any] | None = None) -> Any:
        return self._request("PATCH", path, json_body=json_body)

    def put(self, path: str, *, json_body: dict[str, Any] | None = None) -> Any:
        return self._request("PUT", path, json_body=json_body)
