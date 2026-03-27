"""Credential loading for codex-session-sync."""

from __future__ import annotations

from pathlib import Path

ENV_FILE = Path.home() / ".env.local"
ENV_KEY_CLIENT_ID = "SUMMITFLOW_CLIENT_ID"
ENV_KEY_CLIENT_SECRET = "SUMMITFLOW_CLIENT_SECRET"


def _parse_env_value(raw: str) -> str:
    """Strip quotes and inline comments from a .env file value."""
    if len(raw) >= 2 and raw[0] in ("'", '"') and raw.endswith(raw[0]):
        return raw[1:-1]
    return raw.split("#")[0].strip()


def load_env_credentials() -> tuple[str, str]:
    if not ENV_FILE.exists():
        return "", ""
    client_id = client_secret = ""
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{ENV_KEY_CLIENT_ID}="):
            client_id = _parse_env_value(line.split("=", 1)[1].rstrip())
        elif line.startswith(f"{ENV_KEY_CLIENT_SECRET}="):
            client_secret = _parse_env_value(line.split("=", 1)[1].rstrip())
    return client_id, client_secret
