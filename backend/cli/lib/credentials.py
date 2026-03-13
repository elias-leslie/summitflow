"""Shared credential loading for CLI commands that call Agent Hub.

Single source of truth for reading ~/.env.local and returning
(client_id, request_source) pairs. All CLI modules that need Agent Hub
credentials should import from here instead of duplicating the parsing logic.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import typer

from ..output import output_error

_ENV_FILE = ".env.local"
_KEY_CLIENT_ID = "SUMMITFLOW_CLIENT_ID"
_KEY_CLIENT_ID_LEGACY = "CONSULT_CLIENT_ID"
_KEY_REQUEST_SOURCE = "SUMMITFLOW_REQUEST_SOURCE"


@lru_cache
def _read_env_local() -> dict[str, str]:
    """Read and cache ~/.env.local key-value pairs."""
    env_file = Path.home() / _ENV_FILE
    if not env_file.exists():
        return {}
    creds: dict[str, str] = {}
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[7:]
        if "=" in line and not line.startswith("#"):
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip("'\"")
            if key and val:
                creds[key] = val
    return creds


def load_credentials(default_source: str = "st-cli") -> tuple[str, str]:
    """Load Agent Hub credentials from ~/.env.local.

    Args:
        default_source: Default request source if SUMMITFLOW_REQUEST_SOURCE is not set.

    Returns:
        Tuple of (client_id, request_source).

    Raises:
        typer.Exit: If ~/.env.local is missing or SUMMITFLOW_CLIENT_ID is not found.
    """
    creds = _read_env_local()
    if not creds:
        output_error(f"~/{_ENV_FILE} not found - required for Agent Hub authentication")
        raise typer.Exit(1)

    client_id = creds.get(_KEY_CLIENT_ID) or creds.get(_KEY_CLIENT_ID_LEGACY)
    if not client_id:
        output_error(f"Missing {_KEY_CLIENT_ID} in ~/{_ENV_FILE}")
        raise typer.Exit(1)

    request_source = creds.get(_KEY_REQUEST_SOURCE, default_source)
    return client_id, request_source
