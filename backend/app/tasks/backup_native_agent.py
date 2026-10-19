"""Capture agent-owned Git sources, handing only archive data to the owner."""

from __future__ import annotations

import io
import json
import logging
import os
import shutil
import stat
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any, cast
from uuid import UUID, uuid4

from ..services import tether
from ..utils.agent_execution import source_requires_agent
from ..utils.transient_scratch import disposable_scratch, ensure_scratch_capacity
from .backup_activity import check_backup_cancelled

logger = logging.getLogger(__name__)
ARCHIVE_NAME = "snapshot.tar.gz"
ARCHIVE_ROOT = "snapshot"


def requires_agent_snapshot(project: Path) -> bool:
    """Data-only sources stay local; a checkout's Git must run as its owner."""
    marker = project / ".git"
    return bool(
        (marker.exists() or marker.is_symlink())
        and source_requires_agent(project)
        and os.getuid() != tether._agent_uid()
    )


def _handoff_directory(project: Path, capture_id: str) -> Path:
    # The caller chooses the UUID before execution. No returned path can make
    # the owner open a different file, and cleanup names only this attempt.
    if str(UUID(capture_id)) != capture_id:
        raise ValueError("Invalid backup capture identifier")
    marker = project / ".git"
    if marker.is_dir():
        git_dir = marker.resolve()
    else:
        descriptor = os.open(marker, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise RuntimeError("Backup Git metadata must be a directory or regular gitfile")
            value = source.read(4097)
        if len(value) > 4096 or not value.startswith(b"gitdir: "):
            raise RuntimeError("Unable to locate backup capture handoff")
        git_dir = (project / os.fsdecode(value[8:].strip())).resolve()
    return git_dir / "st" / "backup-capture" / capture_id


def capture_snapshot_as_agent(
    project: Path, staging: Path, excludes: tuple[str, ...],
    sensitive_paths: tuple[Path, ...], *, source_roots: dict[str, Path] | None,
    capture_git: bool, git_history_mode: str,
) -> tuple[Path, dict[str, Any]]:
    """Import a checked data payload before owner-only database/encryption work."""
    from ..services.backup_keys import backup_key_directory
    from ..utils.agent_jobs import run_installed_agent_job

    capture_id = str(uuid4())
    handoff = _handoff_directory(project, capture_id)
    request = {
        "operation": "capture", "project": str(project.absolute()),
        "capture_id": capture_id, "excludes": list(excludes),
        "sensitive_paths": [str(path.expanduser().absolute()) for path in (*sensitive_paths, backup_key_directory())],
        "source_roots": {key: str(path.expanduser().absolute()) for key, path in (source_roots or {}).items()},
        "capture_git": capture_git, "git_history_mode": git_history_mode,
    }
    module = __name__
    try:
        result = run_installed_agent_job(module, request, project=project, cancel_check=check_backup_cancelled)
        if result != {"capture_id": capture_id, "ready": True}:
            raise RuntimeError("Agent backup capture returned an invalid result")
        check_backup_cancelled()
        snapshot = staging / "project-snapshot"
        recovery = _import_snapshot(handoff / ARCHIVE_NAME, snapshot, capture_git=capture_git)
        return snapshot, recovery
    finally:
        try:
            run_installed_agent_job(module, {
                "operation": "cleanup", "project": str(project.absolute()), "capture_id": capture_id,
            }, project=project, timeout=120)
        except Exception:
            logger.warning("Unable to remove temporary agent backup handoff", exc_info=True)


def _import_snapshot(archive_path: Path, destination: Path, *, capture_git: bool = True) -> dict[str, Any]:
    from .backup_native_archive import _CheckedReader, _ScratchWriter
    from .backup_native_recovery import (
        GIT_BUNDLE_NAME,
        GIT_HISTORY_BUNDLE_NAME,
        GIT_INDEX_NAME,
        GIT_SHARED_INDEX_NAME,
        RECOVERY_DIR_NAME,
        RECOVERY_MANIFEST_NAME,
        _open_metadata_directory,
        _sha256,
        _validate_st_metadata_restore,
    )
    from .backup_native_restore import _safe_extract_member, _validate_archive_layout

    # Refuse links in every export parent as well as at the archive itself.
    parent = _open_metadata_directory(archive_path.parent)
    assert parent is not None
    try:
        descriptor = os.open(archive_path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    finally:
        os.close(parent)
    with os.fdopen(descriptor, "rb") as raw:
        metadata = os.fstat(raw.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != tether._agent_uid():
            raise RuntimeError("Agent backup handoff must be an agent-owned regular archive")
        with _CheckedReader(raw) as checked, tarfile.open(fileobj=checked, mode="r:gz") as archive:
            members = archive.getmembers()
            root, _ = _validate_archive_layout(members)
            if root != ARCHIVE_ROOT:
                raise RuntimeError("Unexpected agent backup archive root")
            if any(len(parts := PurePosixPath(member.name).parts) > 1 and parts[1] == ".git" for member in members):
                raise RuntimeError("Agent backup archive must not contain raw Git metadata")
            destination.mkdir(mode=0o700)
            try:
                for member in members:
                    check_backup_cancelled()
                    ensure_scratch_capacity(destination, member.size if member.isreg() else 0)
                    if not member.isreg():
                        _safe_extract_member(archive, member, destination, ARCHIVE_ROOT)
                        continue
                    target = destination / Path(*PurePosixPath(member.name).parts[1:])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    source = archive.extractfile(member)
                    if source is None:
                        raise RuntimeError("Agent backup archive member has no data")
                    with source, _CheckedReader(cast(io.BufferedReader, source)) as reader, target.open("xb", buffering=0) as raw_output, _ScratchWriter(raw_output, target) as output:
                        shutil.copyfileobj(reader, output, length=1024 * 1024)
                    target.chmod(member.mode & 0o777)
                recovery_dir = destination / RECOVERY_DIR_NAME
                manifest = recovery_dir / RECOVERY_MANIFEST_NAME
                if not stat.S_ISREG(manifest.lstat().st_mode):
                    raise RuntimeError("Agent backup recovery manifest must be a regular file")
                recovery = json.loads(manifest.read_text())
                if (not isinstance(recovery, dict) or recovery.get("consistent") is not True
                        or type(recovery.get("version")) is not int or recovery["version"] != 1
                        or recovery.get("source_kind") != "directory"
                        or "git" not in recovery or (capture_git and not isinstance(recovery["git"], dict))):
                    raise RuntimeError("Invalid agent backup recovery manifest")
                git = recovery["git"]
                if isinstance(git, dict):
                    if "st_metadata" not in recovery:
                        raise RuntimeError("Agent backup requires ST recovery metadata")
                    _validate_st_metadata_restore(destination, recovery_dir, recovery)
                    required = [(GIT_BUNDLE_NAME, git.get("bundle_checksum"))]
                    if git.get("index_checksum") is not None:
                        required.append((GIT_INDEX_NAME, git["index_checksum"]))
                    if git.get("shared_index_checksum") is not None:
                        required.append((GIT_SHARED_INDEX_NAME, git["shared_index_checksum"]))
                    if git.get("history_bundle") is not None:
                        history = git["history_bundle"]
                        if not isinstance(history, dict) or history.get("name") != GIT_HISTORY_BUNDLE_NAME:
                            raise RuntimeError("Invalid agent backup Git history manifest")
                        required.append((GIT_HISTORY_BUNDLE_NAME, history.get("checksum")))
                    for name, checksum in required:
                        payload_path = recovery_dir / name
                        if not stat.S_ISREG(payload_path.lstat().st_mode) or _sha256(payload_path) != checksum:
                            raise RuntimeError("Agent backup Git recovery payload checksum mismatch")
                return recovery
            except BaseException:
                shutil.rmtree(destination)
                raise


def run_job(payload: dict[str, Any]) -> dict[str, Any]:
    """Installed job entrypoint: no database, encryption or owner environment."""
    from .backup_native_archive import _add_checked_file, _should_exclude, capacity_checked_archive
    from .backup_native_recovery import build_consistent_snapshot

    if os.getuid() != tether._agent_uid():
        raise RuntimeError("Backup source capture requires the agent identity")
    project = Path(payload["project"])
    capture_id = payload["capture_id"]
    handoff = _handoff_directory(project, capture_id)
    operation = payload["operation"]
    if operation == "cleanup":
        if handoff.exists():
            shutil.rmtree(handoff)
        return {"capture_id": capture_id, "cleaned": True}
    if operation != "capture":
        raise ValueError("Unsupported backup capture operation")
    # Inherit the checkout's existing named owner ACL. Only the new transient
    # directories and archive receive modes; private agent scratch stays 0700.
    handoff.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    handoff.mkdir(mode=0o750)
    try:
        with disposable_scratch("backup-agent-capture-") as temporary:
            snapshot, _ = build_consistent_snapshot(
                project, temporary, tuple(payload["excludes"]), _should_exclude,
                tuple(Path(path) for path in payload["sensitive_paths"]),
                source_roots={name: Path(path) for name, path in payload["source_roots"].items()},
                capture_git=payload["capture_git"], git_history_mode=payload["git_history_mode"],
            )
            archive_path = handoff / ARCHIVE_NAME
            with capacity_checked_archive(archive_path) as archive:
                for root, dirs, files in os.walk(snapshot, followlinks=False):
                    for name in sorted([*dirs, *files]):
                        path = Path(root) / name
                        if path.is_symlink() or path.is_file():
                            _add_checked_file(archive, path, f"{ARCHIVE_ROOT}/{path.relative_to(snapshot).as_posix()}")
            archive_path.chmod(0o640)
        return {"capture_id": capture_id, "ready": True}
    except BaseException:
        shutil.rmtree(handoff)
        raise
