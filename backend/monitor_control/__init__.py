"""Small, owner-local control protocol for the independent host collector."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from typing import Any

from monitor_reader import MonitorQueryError, encode_budgeted_json


class MonitorControlError(RuntimeError):
    """Control socket is unavailable or returned an invalid response."""


def monitor_state_dir() -> Path:
    override = os.environ.get("SUMMITFLOW_MONITOR_STATE_DIR")
    return Path(override) if override else Path.home() / ".local/state/summitflow/monitor"


def control_request(command: str, *, lease_id: str | None = None,
                    ttl_seconds: int | None = None, state_dir: Path | None = None) -> dict[str, Any]:
    if command not in {"status", "lease_start", "lease_renew", "lease_end"}:
        raise MonitorControlError("unsupported monitor control command")
    payload: dict[str, Any] = {"command": command}
    if command in {"lease_renew", "lease_end"}:
        if lease_id is None or len(lease_id) != 32 or any(c not in "0123456789abcdef" for c in lease_id):
            raise MonitorControlError("invalid lease id")
        payload["lease_id"] = lease_id
    if ttl_seconds is not None:
        if command not in {"lease_start", "lease_renew"} or not 1 <= ttl_seconds <= 300:
            raise MonitorControlError("ttl_seconds must be 1..300 for a lease")
        payload["ttl_seconds"] = ttl_seconds
    wire = (json.dumps(payload, separators=(",", ":")) + "\n").encode()
    path = (state_dir or monitor_state_dir()) / "control.sock"
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(1.0)
            connection.connect(str(path))
            connection.sendall(wire)
            with connection.makefile("rb") as stream:
                raw = stream.readline(8193)
    except (OSError, TimeoutError) as exc:
        raise MonitorControlError(f"collector control unavailable: {exc.strerror or type(exc).__name__}") from exc
    if not raw or len(raw) > 8192 or not raw.endswith(b"\n"):
        raise MonitorControlError("invalid collector control response")
    try:
        response = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MonitorControlError("invalid collector control JSON") from exc
    if not isinstance(response, dict) or not isinstance(response.get("ok"), bool):
        raise MonitorControlError("invalid collector control response")
    return response


def enrich_status(payload: dict[str, Any], max_bytes: int) -> dict[str, Any]:
    """Add live writer state without making committed history depend on the daemon."""
    result = {**payload, "coverage": dict(payload.get("coverage") or {}),
              "errors": list(payload.get("errors") or [])}
    try:
        live = control_request("status")
        collector = {
            "availability": "ok" if live.get("ok") else "error",
            "detail_active": live.get("detail_active"),
            "active_leases": live.get("active_leases"),
            "storage_bytes": live.get("storage_bytes"),
            "version": live.get("collector_version"),
        }
        if live.get("writer_failure"):
            collector["availability"] = "error"
            result["errors"].append({"source": "collector_writer", "code": "error",
                                     "message": str(live["writer_failure"])[:160]})
        if live.get("policy_error"):
            result["errors"].append({"source": "pressure_policy", "code": "error",
                                     "message": str(live["policy_error"])[:160]})
    except MonitorControlError:
        collector = {"availability": "collector_stopped"}
        result["errors"].append({"source": "collector", "code": "collector_stopped"})
    result["coverage"]["collector"] = collector
    try:
        encode_budgeted_json(result, max_bytes)
    except MonitorQueryError:
        essential: dict[str, Any] = {"availability": collector["availability"]}
        if live_failure := any(error.get("source") == "collector_writer" for error in result["errors"]):
            essential["writer_failure"] = live_failure
        if policy_failure := any(error.get("source") == "pressure_policy" for error in result["errors"]):
            essential["policy_error"] = policy_failure
        compact = {**result, "items": [], "coverage": {"collector": essential},
                   "errors": [{"code": "output_budget", "source": "collector"}],
                   "next_cursor": None, "truncated": True}
        try:
            encode_budgeted_json(compact, max_bytes)
            return compact
        except MonitorQueryError:
            return {"schema": payload["schema"], "generated_at": payload["generated_at"],
                    "requested": {}, "coverage": {"collector": essential}, "items": [],
                    "next_cursor": None, "truncated": True, "errors": []}
    return result
