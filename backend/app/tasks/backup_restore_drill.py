"""Infrastructure restore drill — full restore into disposable containers."""

from __future__ import annotations

import json
import os
import subprocess
import tarfile
from pathlib import Path
from typing import Any

from ..logging_config import get_logger
from ..storage import backups as backup_store
from ..utils import nightshift_stack
from ..utils.transient_scratch import ensure_scratch_capacity, restore_scratch
from .backup_activity import BackupCancelled, run_bulk_process
from .backup_native_restore import _validate_archive_layout

logger = get_logger(__name__)

DRILL_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "infra-restore-drill.sh"
DRILL_TIMEOUT = 600  # 10 minutes
# The drill script drives the docker CLI. Once the Nightshift stack unit is installed SummitFlow
# loses docker access; rootless podman holds no images, so the drill is then unsupported.
DRILL_UNSUPPORTED = "Restore drill unsupported: no container runtime (docker access removed, podman has no images)"


def drill_runtime_available() -> bool:
    return not nightshift_stack.stack_installed()

# Source types
SOURCE_TYPE_INFRASTRUCTURE = "infrastructure"

# Error messages
ERR_NO_INFRA_SOURCE = "No infrastructure backup source configured"
ERR_NO_COMPLETED_BACKUPS = "No completed infrastructure backups found"
ERR_NOT_REPOSITORY_BACKUP = "Latest infrastructure backup {backup_id} is not a restic repository point"
ERR_NO_JSON_IN_OUTPUT_TEMPLATE = "No JSON found in drill output (last 300 chars): {tail}"
ERR_DRILL_TIMEOUT_TEMPLATE = "Drill timed out after {timeout}s"


def run_infra_drill() -> dict[str, Any]:
    """Run a full infrastructure restore drill against the latest backup.

    1. Finds the latest infrastructure backup (a restic repository point)
    2. Materializes its archive from the repository
    3. Runs infra-restore-drill.sh
    4. Records results in backup_sources

    Returns:
        Drill result dict with ok, components, duration_ms.
    """
    if not drill_runtime_available():
        return {"ok": False, "unsupported": True, "error": DRILL_UNSUPPORTED}
    logger.info("infra_drill_started")

    infra_source = _find_infra_source()
    if infra_source is None:
        return {"ok": False, "error": ERR_NO_INFRA_SOURCE}

    source_id = infra_source["id"]

    latest = backup_store.get_latest_backup(source_id=source_id)
    if not latest:
        return {"ok": False, "error": ERR_NO_COMPLETED_BACKUPS}

    backup_id = latest["id"]
    from .backup_repository_runtime import is_repository_backup, materialize_repository_archive

    if not is_repository_backup(latest):
        error = ERR_NOT_REPOSITORY_BACKUP.format(backup_id=backup_id)
        _record_drill_result(source_id, backup_id, ok=False, error=error)
        return {"ok": False, "backup_id": backup_id, "error": error}
    try:
        with materialize_repository_archive(latest) as archive:
            drill_result = _run_drill_script(str(archive), backup_id)
        _record_drill_result(source_id, backup_id, ok=bool(drill_result.get("ok")), result=drill_result)
        logger.info("infra_drill_completed", ok=drill_result.get("ok"), backup_id=backup_id,
                    duration_ms=drill_result.get("duration_ms"))
        return drill_result
    except subprocess.TimeoutExpired:
        error = ERR_DRILL_TIMEOUT_TEMPLATE.format(timeout=DRILL_TIMEOUT)
        _record_drill_result(source_id, backup_id, ok=False, error=error)
        return {"ok": False, "backup_id": backup_id, "error": error}
    except BackupCancelled:
        raise
    except Exception as exc:
        _record_drill_result(source_id, backup_id, ok=False, error=str(exc))
        logger.exception("infra_drill_exception", backup_id=backup_id)
        return {"ok": False, "backup_id": backup_id, "error": str(exc)}


def _find_infra_source() -> dict[str, Any] | None:
    """Return the infrastructure backup source, or None if not found."""
    sources = backup_store.list_sources()
    return next((s for s in sources if s.get("source_type") == SOURCE_TYPE_INFRASTRUCTURE), None)


def _run_drill_script(archive_path: str, backup_id: str) -> dict[str, Any]:
    """Execute the drill script and return the parsed result dict."""
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        _validate_archive_layout(members)
        # Extraction plus the Redis writable-data copy coexist with the
        # caller's already materialized archive. Database expansion is unknown.
        required = sum(member.size for member in members if member.isreg())
        required += sum(member.size for member in members
                        if member.isreg() and Path(member.name).name == "redis-dump.rdb")
    with restore_scratch("infra-drill-", required_bytes=required) as scratch:
        identifier = scratch.name
        names = [f"sf-drill-pg-{identifier}", f"sf-drill-redis-{identifier}"]
        environment = {
            **os.environ, "TMPDIR": str(scratch),
            "ST_RESTORE_DRILL_ROOT": str(scratch), "ST_RESTORE_DRILL_ID": identifier,
        }
        failure: BaseException | None = None
        try:
            result = run_bulk_process(
                [str(DRILL_SCRIPT), archive_path],
                env=environment, phase="restore", object_name=backup_id,
                attention_after=DRILL_TIMEOUT, timeout=DRILL_TIMEOUT,
                capacity_check=lambda: ensure_scratch_capacity(scratch, 0),
            )
            drill_result = _parse_drill_output(result.stdout)
            if result.returncode:
                drill_result.update(ok=False, error=f"Restore drill script exited {result.returncode}")
            ensure_scratch_capacity(scratch, 0)
            drill_result["backup_id"] = backup_id
            return drill_result
        except BaseException as exc:
            failure = exc
            raise
        finally:
            # Docker containers outlive a killed script/process group. Remove
            # only the exact names belonging to this attempt before deleting
            # their private bind-mounted data, even on cancellation/timeout.
            try:
                _remove_drill_containers(names)
            except Exception as exc:
                if failure is None:
                    raise
                failure.add_note(f"Disposable restore container cleanup also failed: {exc}")
                logger.warning("infra_drill_cleanup_failed", backup_id=backup_id)


def _remove_drill_containers(names: list[str]) -> None:
    removed = subprocess.run(
        ["docker", "rm", "-fv", *names], capture_output=True, text=True,
        timeout=DRILL_TIMEOUT, check=False,
    )
    if removed.returncode:
        # The script's normal EXIT cleanup may have removed them already.
        remaining = subprocess.run(
            ["docker", "ps", "-a", "--filter", f"name=^/({'|'.join(names)})$", "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=DRILL_TIMEOUT, check=False,
        )
        if remaining.returncode:
            raise RuntimeError("Disposable restore container cleanup could not be verified")
        if remaining.stdout.strip():
            raise RuntimeError("Disposable restore containers remain after cleanup")


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
