"""Make a source's payload fresh through its owner extension before the Drive job reads it.

``ominull-production-state`` is a folder another project fills: its ``prepare_backup``
operation takes a new vzdump of the container and publishes it into the folder. Without
this step restic would upload whatever was there last, and report it as a new backup.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any

from .backup_proc import run_process

# source id -> the owner extension that prepares it, and how a stopped guest is named in the status.
SOURCES: dict[str, dict[str, str]] = {
    "ominull-production-state": {"extension": "ominull.backup", "project": "ominull", "guest": "CT 150 ominull"},
}
OPERATION = "prepare_backup"
TIMEOUT_SECONDS = 3 * 3600  # the owner bounds its own Proxmox task and download at an hour each
_DIGEST = re.compile(r"[a-f0-9]{64}")


class PrepareError(RuntimeError):
    """The owner could not make a fresh payload; the folder must not be uploaded as if it were."""


def _qualified_previous(source_id: str, folder: Path) -> dict[str, str] | None:
    """The folder's current generation, once a Drive snapshot taken after it was made holds it.

    The owner retires its previous generation only against this proof; without it the
    next run is offered the same payload again.
    """
    from .backup_offsite import _parse, read_state

    state = read_state()
    job = (state.get("jobs") or {}).get(source_id) or {}
    try:
        prior = json.loads((folder / "manifest.json").read_text())
        made, uploaded = _parse(prior.get("completed_at")), _parse(job.get("time"))
    except (OSError, ValueError, AttributeError):
        return None
    snapshot, repository = job.get("snapshot_id"), state.get("repository")
    if (not isinstance(prior, dict) or prior.get("source_id") != source_id or made is None or uploaded is None or uploaded < made
            or not isinstance(prior.get("backup_id"), str) or not _DIGEST.fullmatch(str(prior.get("sha256")))
            or not isinstance(snapshot, str) or not _DIGEST.fullmatch(snapshot) or not isinstance(repository, str)):
        return None
    return {"backup_id": prior["backup_id"], "sha256": prior["sha256"], "snapshot_id": snapshot,
            "repository_id": hashlib.sha256(repository.encode()).hexdigest()}


def _owner_code(stdout: str) -> str | None:
    """The owner's fixed failure identifier; its other output may carry credential paths."""
    try:
        response = json.loads(stdout)
    except (TypeError, ValueError):
        return None
    code = response.get("error") if isinstance(response, dict) and response.get("status") == "failed" else None
    return code if isinstance(code, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code) else None


def prepare_source(source_id: str, path: str) -> dict[str, Any] | None:
    """Run the owner's prepare operation once. Returns its response, or None when the guest is stopped (nothing new to copy)."""
    from cli.config import get_project_root_path
    from cli.extensions import _environment, _resolve_executable, extension_context, load_extensions

    spec, folder = SOURCES[source_id], Path(path)
    records = [record for record in load_extensions(set()).records
               if record.binding and record.binding.id == spec["extension"]
               and record.manifest and OPERATION in record.manifest.structured_operations]
    if len(records) != 1:
        raise PrepareError(f"the {spec['extension']} extension is not installed")
    record = records[0]
    binding, manifest = record.binding, record.manifest
    assert binding is not None and manifest is not None
    operation = manifest.structured_operations[OPERATION]
    if (record.status != "unverified" or binding.owner != spec["project"]
            or operation.request_contract_version != 1 or operation.response_schema_version != 1
            or not {"write-remote", "write-local"} <= set(manifest.effects) or "desktop" in manifest.effects):
        raise PrepareError(f"the {spec['extension']} extension does not have the grants this step needs")
    executable, code, _ = _resolve_executable(record)
    root = get_project_root_path(spec["project"])
    if code or executable is None or not root or binding.execution_source != "checkout":
        raise PrepareError(f"the {spec['project']} checkout or its backup executable is unavailable")
    backup_id = "bkp-" + uuid.uuid4().hex[:16]
    request = {"contract_version": 1, "operation": OPERATION, "project": spec["project"], "source_id": source_id,
               "backup_id": backup_id, "qualified_previous": _qualified_previous(source_id, folder)}
    context = extension_context()
    context.update(project_id=spec["project"], project_root=root, cwd=root, output={"human": False, "compact": False, "progress_only": False})
    result = run_process([str(executable), *binding.arguments, "--request", json.dumps(request)],
                         env=_environment(binding, context), timeout=TIMEOUT_SECONDS, capture=True, cwd=root)
    if result.returncode:
        owner = _owner_code(result.stdout)
        raise PrepareError(f"{spec['project']} could not refresh {source_id}" + (f" ({owner})" if owner else f" (exit {result.returncode})"))
    try:
        response = json.loads(result.stdout)
        if (response.get("status") == "skipped" and response.get("reason") == "guest_stopped"
                and response.get("source_id") == source_id and response.get("backup_id") == backup_id):
            return None
        archive = Path(response["archive_path"])
        if (response["status"] != "completed" or response["source_id"] != source_id or response["backup_id"] != backup_id
                or archive.parent != folder or not archive.is_file() or archive.stat().st_size != response["size_bytes"] or response["size_bytes"] <= 0):
            raise ValueError("the response does not match the published files")
        return response
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise PrepareError(f"{spec['project']} returned an invalid refresh result for {source_id}") from exc
