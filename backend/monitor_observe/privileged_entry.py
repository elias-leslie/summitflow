"""Fixed, one-request diagnostic entry point for the host collector.

The managed release installs this code in a root-owned zipapp. It reads one
bounded JSON request from stdin and emits only an observation envelope.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, cast

from monitor_extended.disk import query_disk_space

from .common import ObserveQueryError
from .connections import query_connections
from .logs import query_logs

MAX_REQUEST_BYTES = 8192
MAX_OUTPUT_BYTES = 65536
_FIELDS = {"schema", "command", "source", "params", "limit", "max_bytes"}
_PARAMS = {
    "logs": {"scope", "service", "since", "until", "cursor", "priority"},
    "connections": {"include_addresses", "include_process", "cursor"},
    "disk_space": {"path", "max_entries", "max_depth", "timeout_seconds"},
}


def observe(request: object, *, identity_path: Path | None = None) -> dict[str, Any]:
    if not isinstance(request, dict):
        raise ObserveQueryError("invalid request")
    payload = cast(dict[str, Any], request)
    if set(payload) != _FIELDS or payload.get("schema") != 1 or payload.get("command") != "observe":
        raise ObserveQueryError("invalid request")
    source = payload.get("source")
    params = payload.get("params")
    if not isinstance(source, str) or source not in _PARAMS or not isinstance(params, dict) or set(params) - _PARAMS[source]:
        raise ObserveQueryError("unsupported source or parameters")
    limit, max_bytes = payload.get("limit"), payload.get("max_bytes")
    if type(limit) is not int or not 1 <= limit <= 100 or type(max_bytes) is not int or not 512 <= max_bytes <= MAX_OUTPUT_BYTES:
        raise ObserveQueryError("invalid response bounds")
    if source == "logs":
        result = query_logs(**params, limit=limit, max_bytes=max_bytes, identity_path=identity_path)
    elif source == "connections":
        result = query_connections(**params, limit=limit, max_bytes=max_bytes)
    else:
        result = query_disk_space(**params, limit=limit, max_bytes=max_bytes)
    if len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode()) > max_bytes:
        raise ObserveQueryError("observation exceeded response bound")
    return result


def main() -> int:
    raw = sys.stdin.buffer.readline(MAX_REQUEST_BYTES + 1)
    if len(raw) > MAX_REQUEST_BYTES or not raw.endswith(b"\n"):
        return 2
    try:
        request = json.loads(raw)
        identity = Path(sys.argv[0]).resolve().parent / "project.identity.json"
        result = observe(request, identity_path=identity if identity.is_file() else None)
    except (ValueError, TypeError, OSError):
        return 2
    sys.stdout.write(json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
