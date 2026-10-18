"""Freshness of backups other projects run (external_backup_sources): read-only probes, no backup is started here.

- ``systemd_unit``: the unit's last run (system manager first, then the owner's user manager); success when systemd
  recorded Result=success with exit status 0.
- ``artifact_glob``: the newest matching file's modification time; a file counts once it is non-empty.
"""

from __future__ import annotations

import glob
import os
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from ..storage.connection import get_cursor

Runner = Callable[[list[str]], tuple[int, str]]
_FIELDS = "id, name, owner_project, kind, target, frequency, enabled, created_at"


def list_external_sources() -> list[dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute(f"SELECT {_FIELDS} FROM external_backup_sources ORDER BY id")
        rows = cur.fetchall()
    keys = [k.strip() for k in _FIELDS.split(",")]
    return [dict(zip(keys, row, strict=True)) for row in rows]


def _run(argv: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 124, type(exc).__name__
    return proc.returncode, proc.stdout


def _systemd_props(unit: str, run: Runner) -> dict[str, str] | None:
    props = "LoadState,Result,ExecMainStatus,ExecMainExitTimestamp,ActiveState"
    for scope in ([], ["--user"]):
        rc, out = run(["systemctl", *scope, "show", unit, f"--property={props}"])
        if rc != 0:
            continue
        values = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
        if values.get("LoadState") == "loaded":
            return values
    return None


def _parse_systemd_time(value: str) -> datetime | None:
    value = value.strip()
    if not value or value == "n/a":
        return None
    for fmt in ("%a %Y-%m-%d %H:%M:%S %Z", "%a %Y-%m-%d %H:%M:%S %z"):
        try:
            parsed = datetime.strptime(value, fmt)
        except ValueError:
            continue
        return parsed if parsed.tzinfo else parsed.astimezone()
    return None


def probe(source: dict[str, Any], *, run: Runner = _run) -> dict[str, Any]:
    """{last_success_at, last_status, last_error} for one external source."""
    target = str(source.get("target") or "")
    if source.get("kind") == "systemd_unit":
        props = _systemd_props(target, run)
        if props is None:
            return {"last_success_at": None, "last_status": "unknown", "last_error": f"{target} is not installed"}
        finished = _parse_systemd_time(props.get("ExecMainExitTimestamp", ""))
        if props.get("ActiveState") in {"activating", "active"} and props.get("Result") == "success" and not finished:
            return {"last_success_at": None, "last_status": "running", "last_error": None}
        ok = props.get("Result") == "success" and props.get("ExecMainStatus", "0") == "0"
        if finished is None:
            return {"last_success_at": None, "last_status": "never", "last_error": None}
        if ok:
            return {"last_success_at": finished.astimezone(UTC).isoformat(), "last_status": "completed", "last_error": None}
        return {"last_success_at": None, "last_status": "failed",
                "last_error": f"last run ended {props.get('Result')} (exit {props.get('ExecMainStatus')})"}
    if source.get("kind") == "artifact_glob":
        newest: float | None = None
        for path in glob.glob(target):
            try:
                info = os.stat(path)
            except OSError:
                continue
            if info.st_size > 0 and (newest is None or info.st_mtime > newest):
                newest = info.st_mtime
        if newest is None:
            return {"last_success_at": None, "last_status": "never", "last_error": "no backup file found"}
        return {"last_success_at": datetime.fromtimestamp(newest, UTC).isoformat(), "last_status": "completed",
                "last_error": None}
    return {"last_success_at": None, "last_status": "unknown", "last_error": f"unknown kind {source.get('kind')}"}
