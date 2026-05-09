"""Thin httpx client for the portfolio-ai backend.

This is the only HTTP transport surface used by ``st portfolio …``. It
deliberately does NOT subclass :class:`cli._client_base.BaseHTTPClient`
because that class scopes every URL with ``/projects/<id>``; portfolio-ai
exposes its endpoints at the application root (``/api/portfolio/...``,
``/api/catalysts/...``, ``/api/retirement/...``), not under SummitFlow's
project router.

The ``api_url`` resolver implements the precedence stack from the plan:

1. ``ST_PORTFOLIO_API_URL`` environment variable
2. ``ports.json`` ``api_url`` of the nearest portfolio-ai checkout
3. ``project.identity.json`` ``runtime.backend_port`` of the same checkout
4. SummitFlow project registry lookup (works from any cwd)
5. ``--remote`` flag → ``hosts.production_api`` from identity
6. ``http://localhost:8000``

Errors are mapped to deterministic exit codes by the command layer:
``2`` for connection failures, ``1`` for HTTP errors, ``3`` for invalid
input — see :mod:`cli.commands.portfolio`.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import httpx

from ._client_base import APIError

ENV_PORTFOLIO_API_URL = "ST_PORTFOLIO_API_URL"
PORTFOLIO_PROJECT_ID = "portfolio-ai"
DEFAULT_PORTFOLIO_API_URL = "http://localhost:8000"


class PortfolioConnectError(Exception):
    """Raised when the portfolio-ai backend is unreachable.

    Carries the URL that was tried so the CLI can surface it in the
    ``portfolio_api_unreachable`` envelope without re-deriving it.
    """

    def __init__(self, url: str, detail: str) -> None:
        self.url = url
        self.detail = detail
        super().__init__(f"unreachable: {url} ({detail})")


@dataclass(frozen=True)
class ResolvedURL:
    """Result of :func:`_resolve_portfolio_api_url`."""

    url: str
    source: str


def _identity_for(repo_root: Path) -> dict[str, Any] | None:
    identity = repo_root / "project.identity.json"
    if not identity.is_file():
        return None
    try:
        return cast(dict[str, Any], json.loads(identity.read_text()))
    except (OSError, json.JSONDecodeError):
        return None


def _walk_for_portfolio_repo(start: Path) -> Path | None:
    """Walk parents of ``start`` looking for a portfolio-ai checkout.

    Identified by ``project.identity.json`` with ``project.id ==
    "portfolio-ai"``. Returns the repo root or ``None``.
    """
    for candidate in [start, *start.parents]:
        identity = _identity_for(candidate)
        if identity and identity.get("project", {}).get("id") == PORTFOLIO_PROJECT_ID:
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


def _from_summitflow_registry() -> str | None:
    """Look up portfolio-ai in the SummitFlow registry from any cwd.

    Reads ``root_path`` from the registry, then resolves the backend
    port from that root's ``project.identity.json``. Falls back to
    ``DEFAULT_API_BASE`` for the registry call so it works regardless
    of cwd.
    """
    try:
        from app.config import DEFAULT_API_BASE
    except Exception:
        return None

    url = f"{DEFAULT_API_BASE}/projects/{PORTFOLIO_PROJECT_ID}"
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.get(url)
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
    if not repo_root.is_dir():
        return None
    local = _from_identity_local(repo_root)
    if local:
        return local
    return None


def _from_remote_flag(start: Path) -> str | None:
    repo_root = _walk_for_portfolio_repo(start)
    identity: dict[str, Any] | None = _identity_for(repo_root) if repo_root else None
    if identity is None:
        # Try registry to find the root, then read identity from there.
        try:
            from app.config import DEFAULT_API_BASE
        except Exception:
            return None
        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.get(f"{DEFAULT_API_BASE}/projects/{PORTFOLIO_PROJECT_ID}")
        except httpx.HTTPError:
            return None
        if response.status_code != 200:
            return None
        try:
            payload = response.json()
        except ValueError:
            return None
        root = payload.get("root_path")
        if isinstance(root, str) and root:
            identity = _identity_for(Path(root))
    if not identity:
        return None
    host = identity.get("hosts", {}).get("production_api")
    if isinstance(host, str) and host.strip():
        return f"https://{host.strip()}"
    return None


def resolve_portfolio_api_url(*, remote: bool = False, cwd: Path | None = None) -> ResolvedURL:
    """Resolve the portfolio-ai API base URL by precedence.

    See module docstring for the full ordering. ``cwd`` is exposed for
    tests; production callers leave it ``None`` to use the process cwd.
    """
    env_url = os.environ.get(ENV_PORTFOLIO_API_URL)
    if env_url and env_url.strip():
        return ResolvedURL(url=env_url.strip().rstrip("/"), source="env")

    start = (cwd or Path.cwd()).resolve()
    repo_root = _walk_for_portfolio_repo(start)

    if repo_root is not None:
        ports_url = _from_ports_json(repo_root)
        if ports_url:
            return ResolvedURL(url=ports_url, source="ports_json")
        identity_url = _from_identity_local(repo_root)
        if identity_url:
            return ResolvedURL(url=identity_url, source="identity")

    registry_url = _from_summitflow_registry()
    if registry_url:
        return ResolvedURL(url=registry_url, source="registry")

    if remote:
        remote_url = _from_remote_flag(start)
        if remote_url:
            return ResolvedURL(url=remote_url, source="remote")

    return ResolvedURL(url=DEFAULT_PORTFOLIO_API_URL, source="default")


class PortfolioClient:
    """Minimal httpx wrapper for the portfolio-ai backend."""

    def __init__(self, base_url: str, *, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> PortfolioClient:
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

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        url = self._full(path)
        try:
            response = self._client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise PortfolioConnectError(url, str(exc)) from exc
        return self._handle(response)

    def post(self, path: str, *, json_body: dict[str, Any] | None = None) -> Any:
        url = self._full(path)
        try:
            response = self._client.post(url, json=json_body)
        except httpx.HTTPError as exc:
            raise PortfolioConnectError(url, str(exc)) from exc
        return self._handle(response)

    def put(self, path: str, *, json_body: dict[str, Any] | None = None) -> Any:
        url = self._full(path)
        try:
            response = self._client.put(url, json=json_body)
        except httpx.HTTPError as exc:
            raise PortfolioConnectError(url, str(exc)) from exc
        return self._handle(response)
