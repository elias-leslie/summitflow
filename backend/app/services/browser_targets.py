"""Browser target selection and safety checks."""

from __future__ import annotations

import os
import socket
from collections.abc import Mapping
from dataclasses import dataclass

from ..utils import safe_subprocess

_LOCAL_HOSTS = {"", "localhost", "127.0.0.1", "::1", "0.0.0.0"}
_DEFAULT_BROWSER_PORT = 9222
_DEFAULT_LIGHTPANDA_PORT = 9223


class BrowserTargetError(ValueError):
    """Raised when browser endpoint selection is unsafe or incomplete."""


@dataclass(frozen=True)
class BrowserEndpoint:
    """Resolved browser endpoint."""

    host: str
    port: int
    source: str
    debug_local: bool = False


def resolve_browser_endpoint(
    *,
    env: Mapping[str, str] | None = None,
    live: bool = False,
    engine: str | None = None,
) -> BrowserEndpoint:
    """Resolve configured browser endpoint and reject accidental server-local CDP."""
    values = env or os.environ
    host, source = _configured_host(values, live=live)
    allow_local = _allow_local(values, live=live)
    if not host:
        raise BrowserTargetError(
            "Browser host is not configured; set ST_BROWSER_HOST to the isolated VM or connector endpoint"
        )
    if _is_server_local_host(host) and not allow_local:
        raise BrowserTargetError(
            f"Refusing server-local browser endpoint {host}; set ST_BROWSER_HOST to an isolated VM/connector "
            "or set ST_BROWSER_ALLOW_LOCAL=1 for an explicit debug-only override"
        )
    port = _configured_port(values, live=live, engine=engine)
    return BrowserEndpoint(host=host, port=port, source=source, debug_local=allow_local and _is_server_local_host(host))


def _configured_host(values: Mapping[str, str], *, live: bool) -> tuple[str, str]:
    candidates = []
    if live:
        candidates.append(("SUMMITFLOW_LIVE_BROWSER_HOST", values.get("SUMMITFLOW_LIVE_BROWSER_HOST", "")))
    candidates.append(("ST_BROWSER_HOST", values.get("ST_BROWSER_HOST", "")))
    candidates.append(("ST_BROWSER_DEFAULT_HOST", values.get("ST_BROWSER_DEFAULT_HOST", "")))
    for name, raw in candidates:
        host = raw.strip()
        if host:
            return host, name
    return "", "unset"


def _configured_port(values: Mapping[str, str], *, live: bool, engine: str | None) -> int:
    if live:
        raw = values.get("SUMMITFLOW_LIVE_BROWSER_PORT", "").strip()
        if raw:
            return _parse_port(raw, _DEFAULT_BROWSER_PORT)
    raw = values.get("ST_BROWSER_PORT", "").strip()
    if raw:
        return _parse_port(raw, _DEFAULT_BROWSER_PORT)
    if engine == "lightpanda":
        return _DEFAULT_LIGHTPANDA_PORT
    return _DEFAULT_BROWSER_PORT


def _parse_port(raw: str, default: int) -> int:
    try:
        port = int(raw)
    except ValueError:
        return default
    return port if 1 <= port <= 65535 else default


def _allow_local(values: Mapping[str, str], *, live: bool) -> bool:
    if live and values.get("SUMMITFLOW_LIVE_BROWSER_ALLOW_LOCAL", "").strip() == "1":
        return True
    return values.get("ST_BROWSER_ALLOW_LOCAL", "").strip() == "1"


def _is_server_local_host(host: str) -> bool:
    normalized = host.strip().lower().strip("[]")
    if normalized in _LOCAL_HOSTS:
        return True
    return normalized in _server_ip_addresses()


def _server_ip_addresses() -> set[str]:
    addresses = {"127.0.0.1", "::1"}
    try:
        for item in socket.gethostbyname_ex(socket.gethostname())[2]:
            addresses.add(item)
    except OSError:
        pass
    try:
        hostname_ips = socket.getaddrinfo(socket.gethostname(), None)
    except OSError:
        hostname_ips = []
    for entry in hostname_ips:
        address = entry[4][0]
        if isinstance(address, str) and address:
            addresses.add(address)
    detected = safe_subprocess.run(["hostname", "-I"], text=True, capture_output=True, check=False)
    if detected.returncode == 0:
        addresses.update(item for item in detected.stdout.split() if item)
    return addresses
