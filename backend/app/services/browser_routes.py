"""Project-aware browser route resolution."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.project_identity import get_project_canonical_id, get_project_identity

_HOST_KEYS = ("browser_frontend", "lan_frontend", "production_frontend")
_URL_SCHEME_PREFIXES = ("http://", "https://", "data:", "file:", "about:", "chrome:")
_LOCAL_HOSTNAMES = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


class BrowserRouteError(ValueError):
    """Raised when a project cannot be resolved to a browser URL."""


@dataclass(frozen=True)
class BrowserProjectRoute:
    """Resolved browser route for a managed project."""

    project_id: str
    url: str
    host: str
    source: str


def is_url_like(value: str) -> bool:
    """Return true for inputs that should pass directly to the browser."""
    stripped = value.strip()
    if stripped.lower().startswith(_URL_SCHEME_PREFIXES):
        return True
    parsed = urlsplit(stripped)
    return bool(parsed.scheme and parsed.netloc)


def resolve_browser_project_route(
    project_ref: str,
    *,
    env: Mapping[str, str] | None = None,
) -> BrowserProjectRoute:
    """Resolve a project id or alias to its canonical browser frontend URL."""
    values = os.environ if env is None else env
    identity = get_project_identity(project_ref)
    if not identity:
        raise BrowserRouteError(f"Project identity not found for browser target: {project_ref}")

    canonical_id = get_project_canonical_id(project_ref, fallback=project_ref) or project_ref
    hosts = identity.get("hosts")
    if not isinstance(hosts, dict):
        raise BrowserRouteError(f"Project {canonical_id} has no hosts block in project.identity.json")

    for key in _HOST_KEYS:
        raw_host = hosts.get(key)
        if not isinstance(raw_host, str) or not raw_host.strip():
            continue
        url = _url_from_host(raw_host.strip(), values)
        return BrowserProjectRoute(project_id=canonical_id, url=url, host=_host_from_url(url), source=f"hosts.{key}")

    raise BrowserRouteError(
        f"Project {canonical_id} has no browser_frontend, lan_frontend, or production_frontend host"
    )


def resolve_browser_location(value: str, *, env: Mapping[str, str] | None = None) -> str:
    """Resolve project shorthand to URL while passing URL-like values through."""
    stripped = value.strip()
    if is_url_like(stripped):
        return stripped
    return resolve_browser_project_route(stripped, env=env).url


def _url_from_host(host: str, values: Mapping[str, str]) -> str:
    if is_url_like(host):
        return host
    configured_scheme = values.get("ST_BROWSER_PROJECT_SCHEME", "").strip()
    hostname = urlsplit(f"//{host}").hostname
    scheme = configured_scheme or ("http" if hostname in _LOCAL_HOSTNAMES else "https")
    path = values.get("ST_BROWSER_PROJECT_PATH", "/").strip() or "/"
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{scheme}://{host}{path}"


def _host_from_url(url: str) -> str:
    parsed = urlsplit(url)
    return parsed.netloc or parsed.path
