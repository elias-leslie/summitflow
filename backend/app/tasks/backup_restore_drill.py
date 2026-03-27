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

# Source types
SOURCE_TYPE_INFRASTRUCTURE = "infrastructure"

# Error messages
ERR_NO_INFRA_SOURCE = "No infrastructure backup source configured"
ERR_NO_COMPLETED_BACKUPS = "No completed infrastructure backups found"
ERR_ARCHIVE_NOT_FOUND_TEMPLATE = "Cannot locate archive for drill: location={location}, name={name}"
ERR_NO_JSON_IN_OUTPUT_TEMPLATE = "No JSON found in drill output (last 300 chars): {tail}"
ERR_DRILL_TIMEOUT_TEMPLATE = "Drill timed out after {timeout}s"

# Path fragments
PENDING_DIR_PARTS = (".local", "share", "backup-pending")
SMB_TEMP_PREFIX = "sf-drill-dl-"
SMB_BACKUPS_SUBDIR = "project-backups"
SMB_CREDS_FILENAME = ".smbcredentials"

# Environment variable names
ENV_SMB_HOST = "SMB_HOST"
ENV_SMB_SHARE = "SMB_SHARE"

# SMB timeout
SMB_DOWNLOAD_TIMEOUT = 300


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

    infra_source = _find_infra_source()
    if infra_source is None:
        return {"ok": False, "error": ERR_NO_INFRA_SOURCE}

    source_id = infra_source["id"]

    latest = backup_store.get_latest_backup(source_id=source_id)
    if not latest:
        return {"ok": False, "error": ERR_NO_COMPLETED_BACKUPS}

    backup_id = latest["id"]
    location = str(latest.get("location") or "")
    name = str(latest.get("name") or "")

    archive_path = _locate_drill_archive(location, name, source_id)
    if not archive_path:
        error = ERR_ARCHIVE_NOT_FOUND_TEMPLATE.format(location=location, name=name)
        _record_drill_result(source_id, backup_id, ok=False, error=error)
        return {"ok": False, "backup_id": backup_id, "error": error}

    try:
        drill_result = _run_drill_script(archive_path, backup_id)
        _record_drill_result(
            source_id,
            backup_id,
            ok=bool(drill_result.get("ok")),
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
        error = ERR_DRILL_TIMEOUT_TEMPLATE.format(timeout=DRILL_TIMEOUT)
        _record_drill_result(source_id, backup_id, ok=False, error=error)
        return {"ok": False, "backup_id": backup_id, "error": error}

    except Exception as e:
        error = str(e)
        _record_drill_result(source_id, backup_id, ok=False, error=error)
        logger.exception("infra_drill_exception", backup_id=backup_id)
        return {"ok": False, "backup_id": backup_id, "error": error}

    finally:
        _cleanup_temp(archive_path, location)


def _find_infra_source() -> dict[str, Any] | None:
    """Return the infrastructure backup source, or None if not found."""
    sources = backup_store.list_sources()
    return next((s for s in sources if s.get("source_type") == SOURCE_TYPE_INFRASTRUCTURE), None)


def _run_drill_script(archive_path: str, backup_id: str) -> dict[str, Any]:
    """Execute the drill script and return the parsed result dict."""
    result = subprocess.run(
        [str(DRILL_SCRIPT), archive_path],
        capture_output=True,
        text=True,
        timeout=DRILL_TIMEOUT,
    )
    drill_result = _parse_drill_output(result.stdout)
    drill_result["backup_id"] = backup_id
    return drill_result


def _parse_drill_output(stdout: str) -> dict[str, Any]:
    """Find and parse the last JSON object line in drill stdout."""
    output_lines = stdout.strip().splitlines()
    for line in reversed(output_lines):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            parsed = _try_parse_json(line)
            if parsed is not None:
                return parsed
    return {
        "ok": False,
        "components": [],
        "error": ERR_NO_JSON_IN_OUTPUT_TEMPLATE.format(tail=stdout[-300:]),
    }


def _try_parse_json(line: str) -> dict[str, Any] | None:
    """Return parsed JSON dict from line, or None on parse failure."""
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


def _locate_drill_archive(location: str, name: str, source_id: str) -> str | None:
    """Find archive for drill — local, pending, or download from SMB."""
    # Local
    if location and not location.startswith("//") and Path(location).exists():
        return location

    # Pending
    pending = Path.home().joinpath(*PENDING_DIR_PARTS) / name
    if name and pending.exists():
        return str(pending)

    # SMB download
    smb_path = _resolve_smb_path(location, name, source_id)
    if smb_path:
        return _download_from_smb(smb_path)
    return None


def _resolve_smb_path(location: str, name: str, source_id: str) -> str | None:
    """Determine the SMB path for the archive, or None if not applicable."""
    if location.startswith("//"):
        return location
    if name:
        import os
        smb_host = os.environ.get(ENV_SMB_HOST, "")
        smb_share = os.environ.get(ENV_SMB_SHARE, "")
        if smb_host and smb_share:
            return f"//{smb_host}/{smb_share}/{SMB_BACKUPS_SUBDIR}/{source_id}/{name}"
    return None


def _download_from_smb(smb_path: str) -> str | None:
    """Download archive from SMB to temp directory."""
    import os
    import tempfile

    creds_file = Path(os.environ.get("HOME", str(Path.home()))) / SMB_CREDS_FILENAME
    parts = smb_path.split("/")
    if len(parts) < 5:
        return None

    host, share = parts[2], parts[3]
    remote_dir = "/".join(parts[4:-1])
    filename = parts[-1]

    temp_dir = tempfile.mkdtemp(prefix=SMB_TEMP_PREFIX)
    temp_path = f"{temp_dir}/{filename}"

    try:
        result = subprocess.run(
            ["smbclient", f"//{host}/{share}", "-A", str(creds_file),
             "-c", f"cd {remote_dir}; get {filename} {temp_path}"],
            capture_output=True, text=True, timeout=SMB_DOWNLOAD_TIMEOUT,
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
    result: dict[str, Any] | None = None,
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
