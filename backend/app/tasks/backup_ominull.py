"""Refresh the fixed Ominull production source through its trusted owner hook."""

from __future__ import annotations

import json
import re
import stat
from pathlib import Path
from typing import Any

from .backup_activity import run_bulk_process

SOURCE_ID = "ominull-production-state"
SOURCE_PATH = Path("/media/kasadis/Backups/ominull-production-state/current")


def prepare_ominull_backup(*, project_id: str, source_id: str, project_dir: str, backup_id: str) -> dict[str, Any] | None:
    """An unsuccessful refresh must never label stale remote state as fresh."""
    if source_id != SOURCE_ID:
        return None
    if project_id != "ominull" or Path(project_dir) != SOURCE_PATH:
        raise RuntimeError("Ominull production backup source binding differs from its fixed registration")
    from cli.config import get_project_root_path
    from cli.extensions import _environment, _resolve_executable, extension_context, load_extensions

    records = [record for record in load_extensions(set()).records
               if record.binding and record.binding.id == "ominull.backup"
               and record.manifest and "prepare_backup" in record.manifest.structured_operations]
    if len(records) != 1:
        raise RuntimeError("Ominull production backup requires its trusted owner extension")
    record = records[0]
    binding, manifest = record.binding, record.manifest
    assert binding is not None and manifest is not None
    operation = manifest.structured_operations["prepare_backup"]
    if (record.status != "unverified" or binding.owner != "ominull"
        or operation.request_contract_version != 1 or operation.response_schema_version != 1
        or "write-remote" not in manifest.effects or "write-local" not in manifest.effects
        or "desktop" in manifest.effects):
        raise RuntimeError("Ominull backup extension lacks its compatible write grant")
    executable, code, _ = _resolve_executable(record)
    if code or executable is None:
        raise RuntimeError("Ominull backup owner executable is unavailable")
    root = get_project_root_path("ominull")
    if not root or binding.execution_source != "checkout":
        raise RuntimeError("Ominull backup requires its registered owner checkout")
    request = {"contract_version": 1, "operation": "prepare_backup", "project": "ominull",
               "source_id": source_id, "backup_id": backup_id}
    context = extension_context()
    context.update(project_id="ominull", project_root=root, cwd=root,
                   output={"human": False, "compact": False, "progress_only": False})
    result = run_bulk_process(
        [str(executable), *binding.arguments, "--request", json.dumps(request)],
        env=_environment(binding, context), cwd=root, phase="capture", object_name="Ominull production container snapshot",
    )
    if result.returncode:
        # Owner diagnostics may contain credential paths or remote output.
        raise RuntimeError("Ominull production refresh failed; retained owner evidence is required before retry")
    try:
        response = json.loads(result.stdout)
        return validate_preparation(response, backup_id=backup_id)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError("Ominull owner returned invalid production backup evidence") from exc


def validate_preparation(response: Any, *, backup_id: str) -> dict[str, Any]:
    """Check the published identity and provenance before local capture starts."""
    if not isinstance(response, dict) or any(response.get(key) != value for key, value in {
        "schema_version": 1, "status": "completed", "project": "ominull",
        "source_id": SOURCE_ID, "backup_id": backup_id, "target_id": 150,
    }.items()):
        raise ValueError("Preparation identity mismatch")
    archive, manifest = SOURCE_PATH / "lxc-150.tar", SOURCE_PATH / "manifest.json"
    if response.get("archive_path") != str(archive) or response.get("manifest_path") != str(manifest):
        raise ValueError("Preparation paths mismatch")
    for path in (archive, manifest):
        if any(parent.is_symlink() for parent in (path, *path.parents)):
            raise ValueError("Preparation path contains a symlink")
        if not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError("Preparation artifact is not a regular file")
    if (type(response.get("size_bytes")) is not int or response["size_bytes"] <= 0
        or archive.stat().st_size != response["size_bytes"]
        or not isinstance(response.get("sha256"), str)
        or not re.fullmatch(r"[a-f0-9]{64}", response["sha256"])
        or not response.get("completed_at") or not response.get("proxmox_task_id")):
        raise ValueError("Preparation artifact identity missing")
    if json.loads(manifest.read_text()) != response:
        raise ValueError("Preparation manifest differs from the owner response")
    return response
