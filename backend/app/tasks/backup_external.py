"""Freshness of backups other projects run (external_backup_sources): read-only probes, no backup is started here.

- ``systemd_unit``: the unit's last run (system manager first, then the owner's user manager); success when systemd
  recorded Result=success with exit status 0. systemd forgets a run on reboot, so a unit with no run since boot is
  judged by its last finished start job in the journal.
- ``guest_unit``: the same reading inside the Proxmox guest that the owner project's catalog placement names
  (project.identity.json runtime.deployment), through the QEMU guest agent or ``pct exec``.
- ``artifact_glob``: the newest matching file's modification time; a file counts once it is non-empty.
"""

from __future__ import annotations

import glob
import json
import os
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from .. import runtime_deployment
from ..project_identity import get_project_identity
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


def _systemd_props(unit: str, run: Runner) -> tuple[dict[str, str], list[str]] | None:
    props = "LoadState,Result,ExecMainStatus,ExecMainExitTimestamp,ActiveState"
    for scope in ([], ["--user"]):
        rc, out = run(["systemctl", *scope, "show", unit, f"--property={props}"])
        if rc != 0:
            continue
        values = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
        if values.get("LoadState") == "loaded":
            return values, scope
    return None


def _journal_last_job(unit: str, scope: list[str], run: Runner) -> tuple[datetime, bool] | None:
    """When the unit's newest finished start job ended, and whether it succeeded."""
    rc, out = run(["journalctl", *scope, "-u", unit, "JOB_TYPE=start", "JOB_RESULT=done", "JOB_RESULT=failed",
                   "-n", "1", "-o", "json", "--no-pager"])
    lines = out.strip().splitlines() if rc == 0 else []
    if not lines:
        return None
    try:
        entry = json.loads(lines[-1])
        finished = datetime.fromtimestamp(int(entry["__REALTIME_TIMESTAMP"]) / 1_000_000, UTC)
    except (ValueError, KeyError, TypeError):
        return None
    return finished, entry.get("JOB_RESULT") == "done"


def _parse_systemd_time(value: str) -> datetime | None:
    value = value.strip()
    if not value or value == "n/a":
        return None
    if value.endswith((" UTC", " GMT")):  # strptime's %Z leaves these naive, which would read as local time
        try:
            return datetime.strptime(value[:-4], "%a %Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        except ValueError:
            return None
    for fmt in ("%a %Y-%m-%d %H:%M:%S %Z", "%a %Y-%m-%d %H:%M:%S %z"):
        try:
            parsed = datetime.strptime(value, fmt)
        except ValueError:
            continue
        return parsed if parsed.tzinfo else parsed.astimezone()
    return None


def _probe_unit(unit: str, run: Runner) -> dict[str, Any]:
    loaded = _systemd_props(unit, run)
    if loaded is None:
        return {"last_success_at": None, "last_status": "unknown", "last_error": f"{unit} is not installed"}
    props, scope = loaded
    finished = _parse_systemd_time(props.get("ExecMainExitTimestamp", ""))
    if props.get("ActiveState") in {"activating", "active"} and props.get("Result") == "success" and not finished:
        return {"last_success_at": None, "last_status": "running", "last_error": None}
    ok = props.get("Result") == "success" and props.get("ExecMainStatus", "0") == "0"
    if finished is None:
        last = _journal_last_job(unit, scope, run)
        if last is None:
            return {"last_success_at": None, "last_status": "never", "last_error": None}
        finished, ok = last
        if not ok:
            return {"last_success_at": None, "last_status": "failed", "last_error": "last run before this boot failed"}
    if ok:
        return {"last_success_at": finished.astimezone(UTC).isoformat(), "last_status": "completed", "last_error": None}
    return {"last_success_at": None, "last_status": "failed",
            "last_error": f"last run ended {props.get('Result')} (exit {props.get('ExecMainStatus')})"}


def _guest_placement(project_id: Any) -> runtime_deployment.ProxmoxDeployment | None:
    identity = get_project_identity(str(project_id)) if project_id else None
    return runtime_deployment.parse_deployment(((identity or {}).get("runtime") or {}).get("deployment"))


def _guest_runner(target: runtime_deployment.ProxmoxDeployment) -> Runner:
    def run(argv: list[str]) -> tuple[int, str]:
        try:
            return 0, runtime_deployment._guest_command(target, argv)
        except runtime_deployment.DeploymentError as exc:
            return 1, str(exc)
    return run


def _probe_guest_unit(source: dict[str, Any], unit: str, placement: Callable[[Any], Any]) -> dict[str, Any]:
    try:
        target = placement(source.get("owner_project"))
        if target is None:
            return {"last_success_at": None, "last_status": "unknown",
                    "last_error": f"{source.get('owner_project')} has no Proxmox placement in its project identity"}
        if runtime_deployment._guest_status(target) != "running":
            return {"last_success_at": None, "last_status": "unknown", "last_error": f"{target.label} is stopped"}
    except runtime_deployment.DeploymentError as exc:
        return {"last_success_at": None, "last_status": "unknown", "last_error": str(exc)}
    seen = _probe_unit(unit, _guest_runner(target))
    if seen["last_error"]:
        seen["last_error"] = f"{seen['last_error']} on {target.label}"
    return seen


def probe(source: dict[str, Any], *, run: Runner = _run,
          placement: Callable[[Any], Any] = _guest_placement) -> dict[str, Any]:
    """{last_success_at, last_status, last_error} for one external source."""
    target = str(source.get("target") or "")
    if source.get("kind") == "systemd_unit":
        return _probe_unit(target, run)
    if source.get("kind") == "guest_unit":
        return _probe_guest_unit(source, target, placement)
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
