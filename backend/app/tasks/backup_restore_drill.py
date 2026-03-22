"""Infrastructure restore drill — full restore into disposable containers."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from ..logging_config import get_logger
from ..storage import backups as backup_store

logger = get_logger(__name__)

DRILL_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "infra-restore-drill.sh"
DRILL_TIMEOUT = 600  # 10 minutes


def run_infra_drill() -> dict[str, Any]:
    """Run a full infrastructure restore drill against the latest backup.

    1. Finds the latest infrastructure backup
    2. Locates the archive (local or downloads from SMB)
    3. Runs infra-restore-drill.sh
    4. Records results in backup_sources

    Returns:
        Drill result dict with ok, components, duration_ms.
    """
    logger.info("infra_drill_started")

    # Find infrastructure source
    sources = backup_store.list_sources()
    infra_source = next((s for s in sources if s.get("source_type") == "infrastructure"), None)
    if not infra_source:
        return {"ok": False, "error": "No infrastructure backup source configured"}

    source_id = infra_source["id"]

    # Find latest completed backup
    latest = backup_store.get_latest_backup(source_id=source_id)
    if not latest:
        return {"ok": False, "error": "No completed infrastructure backups found"}

    backup_id = latest["id"]
    location = str(latest.get("location") or "")
    name = str(latest.get("name") or "")

    # Locate archive
    archive_path = _locate_drill_archive(location, name, source_id)
    if not archive_path:
        error = f"Cannot locate archive for drill: location={location}, name={name}"
        _record_drill_result(source_id, backup_id, ok=False, error=error)
        return {"ok": False, "backup_id": backup_id, "error": error}

    # Run drill script
    try:
        result = subprocess.run(
            [str(DRILL_SCRIPT), archive_path],
            capture_output=True,
            text=True,
            timeout=DRILL_TIMEOUT,
        )

        # Parse JSON output (last line of stdout)
        output_lines = result.stdout.strip().splitlines()
        json_line = output_lines[-1] if output_lines else "{}"

        try:
            drill_result = json.loads(json_line)
        except json.JSONDecodeError:
            drill_result = {
                "ok": False,
                "components": [],
                "error": f"Failed to parse drill output: {result.stdout[:200]}",
            }

        drill_result["backup_id"] = backup_id

        # Record result
        _record_drill_result(
            source_id,
            backup_id,
            ok=drill_result.get("ok", False),
            result=drill_result,
        )

        logger.info(
            "infra_drill_completed",
            ok=drill_result.get("ok"),
            backup_id=backup_id,
            duration_ms=drill_result.get("duration_ms"),
        )
        return drill_result

    except subprocess.TimeoutExpired:
        error = f"Drill timed out after {DRILL_TIMEOUT}s"
        _record_drill_result(source_id, backup_id, ok=False, error=error)
        return {"ok": False, "backup_id": backup_id, "error": error}

    except Exception as e:
        error = str(e)
        _record_drill_result(source_id, backup_id, ok=False, error=error)
        logger.exception("infra_drill_exception", backup_id=backup_id)
        return {"ok": False, "backup_id": backup_id, "error": error}

    finally:
        _cleanup_temp(archive_path, location)


def _locate_drill_archive(location: str, name: str, source_id: str) -> str | None:
    """Find archive for drill — local, pending, or download from SMB."""
    # Local
    if location and not location.startswith("//") and Path(location).exists():
        return location

    # Pending
    pending = Path.home() / ".local" / "share" / "backup-pending" / name
    if name and pending.exists():
        return str(pending)

    # SMB download
    smb_path = None
    if location.startswith("//"):
        smb_path = location
    elif name:
        import os
        smb_host = os.environ.get("SMB_HOST", "")
        smb_share = os.environ.get("SMB_SHARE", "")
        if smb_host and smb_share:
            smb_path = f"//{smb_host}/{smb_share}/project-backups/{source_id}/{name}"

    if smb_path:
        return _download_from_smb(smb_path)
    return None


def _download_from_smb(smb_path: str) -> str | None:
    """Download archive from SMB to temp directory."""
    import os
    import tempfile

    creds_file = Path(os.environ.get("HOME", str(Path.home()))) / ".smbcredentials"
    parts = smb_path.split("/")
    if len(parts) < 5:
        return None

    host, share = parts[2], parts[3]
    remote_dir = "/".join(parts[4:-1])
    filename = parts[-1]

    temp_dir = tempfile.mkdtemp(prefix="sf-drill-dl-")
    temp_path = f"{temp_dir}/{filename}"

    try:
        result = subprocess.run(
            ["smbclient", f"//{host}/{share}", "-A", str(creds_file),
             "-c", f"cd {remote_dir}; get {filename} {temp_path}"],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode == 0 and Path(temp_path).exists():
            return temp_path
    except Exception:
        pass
    return None


def _cleanup_temp(archive_path: str, original_location: str) -> None:
    """Remove temp files if archive was downloaded."""
    if original_location.startswith("//") and archive_path:
        import shutil
        parent = Path(archive_path).parent
        if str(parent).startswith("/tmp/"):
            shutil.rmtree(parent, ignore_errors=True)


def _record_drill_result(
    source_id: str,
    backup_id: str,
    ok: bool,
    result: dict | None = None,
    error: str | None = None,
) -> None:
    """Record drill result in backup_sources table."""
    if result is None and error:
        result = {"ok": False, "error": error, "components": []}
    backup_store.update_source_drill_result(
        source_id=source_id,
        ok=ok,
        backup_id=backup_id,
        result=result,
    )
