"""Owner-triggered accepted-source publication, independent of backup capture."""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cli.lib.acceptance import AcceptanceError, repo_lock

from ..services.publication_health import record_publication_observation
from ..storage import backups as backup_store
from ..storage.projects import get_project_root_path
from .backup_publish import _public_evidence, _value, publish_source_before_backup

_OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")


def publication_receipt_directory(project: Path) -> Path:
    return Path(_value(project, "rev-parse", "--path-format=absolute", "--git-common-dir")) / "st" / "publication"


def read_publication_receipt(project: Path, source_commit: str) -> dict[str, Any] | None:
    """Read retained same-source evidence without observing the remote."""
    if not _OID.fullmatch(source_commit):
        raise ValueError("Publication requires a full immutable source commit")
    return _read_publication_receipt_path(publication_receipt_directory(project) / (source_commit + ".json"), source_commit)


def _read_publication_receipt_path(path: Path, source_commit: str) -> dict[str, Any] | None:
    if not path.is_file() or path.is_symlink():
        return None
    value = json.loads(path.read_text())
    if (not isinstance(value, dict) or value.get("kind") != "manual_publication.v1"
            or value.get("schema_version") != 1 or value.get("source_commit") != source_commit
            or value.get("requested_source_commit") != source_commit):
        raise ValueError("Publication evidence identity mismatch")
    body = {key: item for key, item in value.items() if key != "receipt_id"}
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if value.get("receipt_id") != digest:
        raise ValueError("Publication evidence integrity mismatch")
    return value


def latest_publication_receipt(project: Path, project_id: str, *, directory: Path | None = None) -> tuple[Path, dict[str, Any]] | None:
    """Select valid manual evidence pointers; immutable historical files are not new observations."""
    records = []
    for path in (directory if directory is not None else publication_receipt_directory(project)).glob("*.json"):
        if not _OID.fullmatch(path.stem):
            continue
        value = _read_publication_receipt_path(path, path.stem)
        if value and value.get("project_id") == project_id:
            records.append((path, value))
    return max(records, key=lambda row: str(row[1].get("observed_at") or "")) if records else None


def _retain_publication(project: Path, project_id: str, source_commit: str, observation: dict[str, Any]) -> Path:
    if observation.get("head") not in {None, source_commit} or (
            observation.get("publication_complete") is True and observation.get("head") != source_commit):
        raise ValueError("Publication observation belongs to a different source")
    directory = publication_receipt_directory(project)
    directory.mkdir(parents=True, exist_ok=True)
    previous = read_publication_receipt(project, source_commit)
    value = {"kind": "manual_publication.v1", "schema_version": 1, "source_commit": source_commit,
             "requested_source_commit": source_commit, "project_id": project_id,
             "observed_at": datetime.now(UTC).isoformat(), "observation": _public_evidence(observation),
             "previous_receipt_id": (previous or {}).get("receipt_id")}
    digest = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    value["receipt_id"] = digest
    encoded = json.dumps(value, indent=2, sort_keys=True) + "\n"
    immutable = directory / (source_commit + "-" + digest + ".json")
    immutable.write_text(encoded)
    temporary = directory / ("." + str(uuid.uuid4()) + ".tmp")
    try:
        temporary.write_text(encoded)
        os.replace(temporary, directory / (source_commit + ".json"))
    finally:
        temporary.unlink(missing_ok=True)
    return immutable


def publish_project_now(source_id: str, source_commit: str, *, authorized_workflows: tuple[str, ...] = (),
                        publication_mode: str = "manual") -> dict[str, Any]:
    """Publish only the supplied accepted OID; no checkpoint, capture or deployment."""
    if not _OID.fullmatch(source_commit):
        raise ValueError("Publication requires an exact lowercase 40- or 64-character commit OID")
    result: dict[str, Any] = {"source_id": source_id, "publication_mode": publication_mode,
        "requested_source_commit": source_commit, "observed_at": datetime.now(UTC).isoformat(),
        "publication_complete": False, "evidence_recorded": False}
    # Registered project ownership authorizes source lookup. Backup scheduling,
    # capture records and Redis are independent of this manually selected source.
    root = get_project_root_path(source_id)
    registered = backup_store.get_source(source_id) if not root else None
    project_id = source_id if root else str((registered or {}).get("project_id") or "")
    if not root and registered and registered.get("source_type") == "project":
        root = get_project_root_path(project_id)
        if root and Path(root).resolve() != Path(str(registered.get("path"))).resolve():
            return {**result, "status": "failed", "reason": "repository_root_mismatch"}
    if not root or not project_id:
        return {**result, "status": "failed", "reason": "registered_project_required"}
    project = Path(root).resolve()
    source = {"id": source_id, "project_id": project_id, "path": str(project), "enabled": True, "source_type": "project"}
    try:
        with repo_lock(project, purpose="manual publication"):
            previous = read_publication_receipt(project, source_commit)
            retained = (previous or {}).get("observation")
            options: dict[str, Any] = {"authorized_workflows": authorized_workflows} if authorized_workflows else {}
            if publication_mode != "manual":
                options["publication_mode"] = publication_mode
            publication = publish_source_before_backup(source, retained=retained,
                manual_source_commit=source_commit, activity_allowed=lambda: True, **options)
            result.update(publication)
            try:
                artifact = _retain_publication(project, project_id, source_commit, publication)
            except (OSError, ValueError):
                return {**result, "status": "pending", "reason": "publication_receipt_unavailable", "publication_complete": False}
            result.update(evidence_recorded=True, evidence=str(artifact))
            record_publication_observation(project_id, publication)
    except AcceptanceError:
        return {**result, "status": "pending", "reason": "repository_busy", "publication_complete": False}
    return result
