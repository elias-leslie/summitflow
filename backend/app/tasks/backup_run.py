"""The host backup job systemd runs every 4 hours (summitflow-host-backup.timer).

One run, holding the host lock for its whole length so runs never overlap:

1. btrbk takes the snapshots and sends the increment to the T7;
2. once a day, restic reads those snapshots into Google Drive (``backup_offsite``);
3. the health receipts are refreshed and any real problem is raised.

``python -m app.tasks.backup_run [--force-offsite] [--no-offsite]``. A run that finds another
one active exits quietly; a failed step is retried by the next scheduled run.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from typing import Any

from ..logging_config import get_logger
from . import (
    backup_alerts,
    backup_overview,  # noqa: F401  Loaded up front: a run that outlives a deploy must not import from a replaced release.
)
from . import backup_btrbk as host
from . import backup_offsite as offsite

logger = get_logger(__name__)

UNIT = "summitflow-host-backup.service"
FORCE_FLAG = "force-offsite"


def _snapshots_exist(points: list[dict[str, Any]]) -> bool:
    return all(host._run(["sudo", "-n", "test", "-d", str(point["snapshot"])]).returncode == 0 for point in points)


def _points(local: dict[str, Any]) -> tuple[list[dict[str, Any]], str] | None:
    """The snapshots to read off-site: this run's, or the last good run's while they are still the newest on disk."""
    if local.get("status") == "completed" and local.get("points"):
        return local["points"], str(local["run_id"])
    good = host._state_root() / "last-good.json"
    try:
        saved = json.loads(good.read_text())
    except (OSError, ValueError):
        return None
    points = saved.get("points") or []
    return (points, str(saved["run_id"])) if points and _snapshots_exist(points) else None


def request_run(*, with_offsite: bool = False) -> dict[str, Any]:
    """Start a run now under the same unit and limits as the timer; ``with_offsite`` also makes today's Google Drive copy."""
    if with_offsite:
        directory = offsite.state_dir()
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        (directory / FORCE_FLAG).touch()
    proc = subprocess.run(["systemctl", "--user", "start", "--no-block", UNIT], capture_output=True, text=True, check=False, timeout=30)
    if proc.returncode:
        return {"started": False, "error": (proc.stderr or proc.stdout).strip()[-300:]}
    return {"started": True, "unit": UNIT, "offsite": with_offsite}


def run(*, force_offsite: bool = False, no_offsite: bool = False) -> dict[str, Any]:
    started = datetime.now(UTC)
    flag = offsite.state_dir() / FORCE_FLAG
    force_offsite = force_offsite or flag.exists()
    result: dict[str, Any] = {"started_at": started.isoformat()}
    try:
        with host.host_run_lock():
            state = offsite.recover_state()
            local = host.run_native_host_backup(now=started, locked=True)
            result["local"] = {key: local.get(key) for key in ("status", "reason", "error", "run_id") if local.get(key)}
            due = None if no_offsite else offsite.offsite_due(state, datetime.now(UTC), force=force_offsite)
            if due:
                points = _points(local)
                if points is None:
                    result["offsite"] = {"status": "skipped", "reason": "no btrbk snapshots to read; the next run takes new ones"}
                else:
                    run_result = offsite.run_offsite(points[0], points[1])
                    flag.unlink(missing_ok=True)
                    result["offsite"] = {key: run_result.get(key) for key in ("status", "error", "warning", "started_at", "finished_at")}
    except host.HostBackupActive:
        result["skipped"] = "another host backup run is active"
    except Exception as exc:
        logger.exception("host_backup_run_failed")
        result["error"] = str(exc)[:300]
    finally:
        result["health"] = refresh_health()
    return result


def refresh_health() -> dict[str, Any]:
    """Rewrite the freshness receipts and raise or clear alerts from the state just written."""
    try:
        return backup_alerts.evaluate_backup_alerts({})
    except Exception as exc:
        logger.exception("backup_health_refresh_failed")
        return {"error": str(exc)[:300]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the SummitFlow host backup (btrbk, then the daily Google Drive copy when due)")
    parser.add_argument("--force-offsite", action="store_true", help="run the Google Drive copy now even if today's is done")
    parser.add_argument("--no-offsite", action="store_true", help="only the btrbk step")
    args = parser.parse_args(argv)
    result = run(force_offsite=args.force_offsite, no_offsite=args.no_offsite)
    print(json.dumps(result, indent=1, default=str))
    # A failed step is recorded in the state and retried by the next run; only a crash makes the unit itself fail.
    return 1 if result.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())
