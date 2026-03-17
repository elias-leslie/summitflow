#!/usr/bin/env python3
"""Validate the Hatchet client token against the generated runtime config."""

from __future__ import annotations

import base64
import json
import re
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _read_env_value(env_file: Path, key: str) -> str:
    if not env_file.exists():
        return ""
    pattern = re.compile(rf"^{re.escape(key)}=(.*)$")
    for raw_line in env_file.read_text().splitlines():
        match = pattern.match(raw_line.strip())
        if not match:
            continue
        return match.group(1).strip().strip('"').strip("'")
    return ""


def _decode_jwt_payload(token: str) -> dict[str, object]:
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Hatchet token is not a valid JWT")

    payload = parts[1]
    padding = "=" * (-len(payload) % 4)
    decoded = base64.urlsafe_b64decode(payload + padding)
    parsed = json.loads(decoded)
    if not isinstance(parsed, dict):
        raise ValueError("Hatchet token payload is not a JSON object")
    return parsed


def _read_grpc_broadcast_address(server_file: Path) -> str:
    if not server_file.exists():
        return ""

    in_runtime = False
    for raw_line in server_file.read_text().splitlines():
        if raw_line.startswith("runtime:"):
            in_runtime = True
            continue
        if in_runtime and raw_line and not raw_line.startswith(" "):
            in_runtime = False
        if not in_runtime:
            continue
        stripped = raw_line.strip()
        if stripped.startswith("grpcBroadcastAddress:"):
            return stripped.split(":", 1)[1].strip()
    return ""


def main() -> int:
    repo_root = _repo_root()
    env_file = repo_root / "docker" / "compose" / ".env"
    server_file = repo_root / "docker" / "compose" / "hatchet-config" / "server.yaml"

    token = _read_env_value(env_file, "HATCHET_CLIENT_TOKEN")
    expected_address = _read_grpc_broadcast_address(server_file)

    if not token or not expected_address:
        return 0

    try:
        payload = _decode_jwt_payload(token)
    except Exception as exc:  # pragma: no cover - surfaced as CLI output
        print(f"Hatchet token validation failed: {exc}", file=sys.stderr)
        return 1

    actual_address = str(payload.get("grpc_broadcast_address", "")).strip()
    if not actual_address:
        print("Hatchet token validation failed: token payload is missing grpc_broadcast_address", file=sys.stderr)
        return 1

    if actual_address != expected_address:
        print(
            "Hatchet token validation failed: "
            f"token grpc_broadcast_address={actual_address!r} does not match runtime config {expected_address!r}",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
