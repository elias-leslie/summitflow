"""Git-aware baseline capture and reset helpers for reusable testbed projects."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from app.storage import backups as backup_store
from app.storage.projects import get_project_root_path
from app.tasks.backup import create_backup
from app.tasks.backup_restore import restore_backup

from .quick_snapshots import (
    SnapshotError,
    capture_snapshot,
    restore_project_snapshot,
)


class TestbedBackupError(Exception):
    """Raised when a testbed baseline or reset cannot complete safely."""


def _testbed_archive_root() -> Path:
    root = os.environ.get("ST_TESTBED_BACKUP_ROOT")
    if root:
        return Path(root).expanduser()
    return Path.home() / ".local" / "share" / "testbed-backups"


def _project_root(project_id: str) -> Path:
    root_path = get_project_root_path(project_id)
    if not root_path:
        raise TestbedBackupError(f"Project '{project_id}' has no root_path configured")
    root = Path(root_path).resolve()
    if not root.exists():
        raise TestbedBackupError(f"Project root does not exist: {root}")
    return root


def _git(repo_root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=check,
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() or str(exc)
        raise TestbedBackupError(f"Git command failed: git {' '.join(args)}\n{stderr}") from exc
    except OSError as exc:
        raise TestbedBackupError(f"Failed to run git {' '.join(args)}: {exc}") from exc


def _git_branch(repo_root: Path) -> str | None:
    result = _git(repo_root, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    if result.returncode == 0:
        return result.stdout.strip() or None
    return None


def _git_head(repo_root: Path) -> str | None:
    result = _git(repo_root, "rev-parse", "--verify", "HEAD", check=False)
    if result.returncode == 0:
        return result.stdout.strip() or None
    return None


def _git_status_lines(repo_root: Path) -> list[str]:
    result = _git(
        repo_root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        check=False,
    )
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def _has_database(backup: dict[str, Any]) -> bool:
    verification = backup.get("verification_json")
    if isinstance(verification, dict) and isinstance(verification.get("has_db"), bool):
        return bool(verification["has_db"])
    return bool((backup.get("db_size_bytes") or 0) > 0)


def _require_baseline_backup(project_id: str, backup_id: str | None = None) -> dict[str, Any]:
    backup = (
        backup_store.get_backup(backup_id)
        if backup_id
        else backup_store.get_latest_backup(
            project_id=project_id,
            verification_key="testbed_baseline",
        )
    )
    if not backup:
        label = backup_id or "latest"
        raise TestbedBackupError(f"Testbed baseline backup '{label}' was not found")
    if backup.get("project_id") != project_id:
        raise TestbedBackupError(
            f"Backup '{backup['id']}' belongs to project '{backup.get('project_id')}', not '{project_id}'"
        )

    verification = backup.get("verification_json")
    if not isinstance(verification, dict) or not isinstance(verification.get("testbed_baseline"), dict):
        raise TestbedBackupError(f"Backup '{backup['id']}' is not marked as a testbed baseline")
    return backup


def _ensure_reset_runs_outside_target(project_root: Path) -> None:
    try:
        current = Path.cwd().resolve()
    except OSError:
        current = Path.cwd()
    if current == project_root or project_root in current.parents:
        raise TestbedBackupError(
            "Run testbed reset from outside the target project root. "
            f"The restore replaces '{project_root}' in place and will strand a shell that is currently inside it."
        )


def _relocate_repo_local_archive(
    project_id: str,
    project_root: Path,
    backup_id: str,
    archive_location: str | None,
) -> str | None:
    if not archive_location:
        return None

    archive_path = Path(archive_location).expanduser()
    try:
        resolved_archive = archive_path.resolve()
        resolved_root = project_root.resolve()
    except OSError as exc:
        raise TestbedBackupError(f"Failed to resolve local archive path '{archive_location}': {exc}") from exc

    if resolved_archive != resolved_root and resolved_root not in resolved_archive.parents:
        return str(resolved_archive)
    if not resolved_archive.exists():
        raise TestbedBackupError(
            f"Local testbed archive was not found at '{resolved_archive}'. "
            "Expected local-only baseline capture to produce a restoreable archive."
        )

    destination = _testbed_archive_root() / project_id / resolved_archive.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(resolved_archive), destination)
    updated = backup_store.update_backup_status(
        backup_id,
        "completed",
        location=str(destination),
    )
    if not updated:
        raise TestbedBackupError(f"Failed to update archive location for baseline backup '{backup_id}'")
    return str(destination)


def preview_testbed_reset(project_id: str, backup_id: str | None = None) -> dict[str, Any]:
    """Return the baseline metadata used for reset preview/confirmation."""
    backup = _require_baseline_backup(project_id, backup_id)
    metadata = dict(backup["verification_json"]["testbed_baseline"])
    git_meta = metadata.get("git") if isinstance(metadata.get("git"), dict) else {}
    project_root = Path(str(metadata.get("project_root") or _project_root(project_id))).resolve()
    _ensure_reset_runs_outside_target(project_root)

    return {
        "project_id": project_id,
        "backup_id": backup["id"],
        "backup_name": backup.get("name"),
        "backup_note": backup.get("note"),
        "project_root": str(project_root),
        "snapshot_id": metadata.get("snapshot_id"),
        "snapshot_name": metadata.get("snapshot_name"),
        "git_branch": git_meta.get("branch"),
        "git_head": git_meta.get("head_oid"),
        "git_dirty": bool(git_meta.get("dirty")),
        "has_database": _has_database(backup),
    }


def capture_testbed_baseline(
    project_id: str,
    *,
    note: str | None = None,
    snapshot_name: str | None = None,
    allow_dirty: bool = False,
    keep_local: bool = False,
    local_only: bool = True,
) -> dict[str, Any]:
    """Capture a git-aware project baseline backed by Btrfs and a backup archive."""
    project_root = _project_root(project_id)
    git_status_lines = _git_status_lines(project_root)
    git_dirty = bool(git_status_lines)
    if git_dirty and not allow_dirty:
        raise TestbedBackupError(
            "Refusing to capture a dirty baseline. Commit or stash changes, or re-run with --allow-dirty."
        )

    try:
        snapshot = capture_snapshot(
            snapshot_name,
            project_id=project_id,
            cwd=project_root,
            source="testbed-baseline",
        )
    except SnapshotError as exc:
        raise TestbedBackupError(str(exc)) from exc

    result = create_backup(
        project_id=project_id,
        note=note or "Testbed baseline",
        keep_local=keep_local if not local_only else False,
        local_only=local_only,
    )
    if result.get("status") not in {"completed", "completed_pending_upload"}:
        raise TestbedBackupError(str(result.get("error") or "Backup creation failed"))

    backup_id = str(result["backup_id"])
    archive_location = _relocate_repo_local_archive(
        project_id,
        project_root,
        backup_id,
        str(result.get("location") or "") or None,
    )
    updated = backup_store.merge_backup_verification_json(
        backup_id,
        {
            "testbed_baseline": {
                "version": 1,
                "project_root": str(project_root),
                "snapshot_id": snapshot.id,
                "snapshot_name": snapshot.name,
                "snapshot_path": snapshot.snapshot_path,
                "snapshot_created_at": snapshot.created_at,
                "git": {
                    "branch": _git_branch(project_root),
                    "head_oid": _git_head(project_root),
                    "head_ref": snapshot.head_ref,
                    "dirty": git_dirty,
                    "status_lines": git_status_lines,
                },
            }
        },
    )
    if not updated:
        raise TestbedBackupError(f"Failed to annotate baseline backup '{backup_id}'")

    return {
        "project_id": project_id,
        "backup_id": backup_id,
        "backup_name": updated.get("name"),
        "backup_status": updated.get("status"),
        "archive_location": archive_location or updated.get("location"),
        "snapshot_id": snapshot.id,
        "snapshot_name": snapshot.name,
        "git_branch": _git_branch(project_root),
        "git_head": _git_head(project_root),
        "git_dirty": git_dirty,
    }


def _run_project_rebuild(
    project_id: str,
    project_root: Path | None,
) -> dict[str, Any]:
    def _run(cmd: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            raise TestbedBackupError(f"Failed to run {' '.join(cmd)}: {exc}") from exc

    result = _run(["rebuild.sh", project_id])
    if result.returncode == 0:
        return {
            "ran": True,
            "method": "global-rebuild",
            "stdout_tail": (result.stdout or "").strip()[-2000:],
            "stderr_tail": (result.stderr or "").strip()[-2000:],
        }

    combined = "\n".join(part for part in ((result.stdout or "").strip(), (result.stderr or "").strip()) if part)
    if "Unknown project:" in combined and project_root is not None:
        for script_name in ("rebuild.sh", "restart.sh"):
            script_path = project_root / "scripts" / script_name
            if not script_path.exists():
                continue

            local_result = _run(["bash", str(script_path)], cwd=project_root)
            if local_result.returncode == 0:
                return {
                    "ran": True,
                    "method": f"local-{script_name}",
                    "stdout_tail": (local_result.stdout or "").strip()[-2000:],
                    "stderr_tail": (local_result.stderr or "").strip()[-2000:],
                }

            local_stdout = (local_result.stdout or "").strip()[-2000:]
            local_stderr = (local_result.stderr or "").strip()[-2000:]
            local_details = "\n".join(part for part in (local_stdout, local_stderr) if part)
            raise TestbedBackupError(
                f"{script_name} failed for project '{project_id}'\n{local_details}".strip()
            )

        return {
            "ran": False,
            "method": "skipped",
            "reason": f"Unknown project '{project_id}' for rebuild.sh and no local scripts/rebuild.sh or scripts/restart.sh exist",
            "stdout_tail": (result.stdout or "").strip()[-2000:],
            "stderr_tail": (result.stderr or "").strip()[-2000:],
        }

    stdout = (result.stdout or "").strip()[-2000:]
    stderr = (result.stderr or "").strip()[-2000:]
    details = "\n".join(part for part in (stdout, stderr) if part)
    raise TestbedBackupError(f"rebuild.sh {project_id} failed\n{details}".strip())


def reset_testbed_to_baseline(
    project_id: str,
    backup_id: str | None = None,
    *,
    rebuild: bool = True,
) -> dict[str, Any]:
    """Reset a project to a recorded testbed baseline."""
    backup = _require_baseline_backup(project_id, backup_id)
    metadata = backup["verification_json"]["testbed_baseline"]
    snapshot_id = metadata.get("snapshot_id")
    if not snapshot_id:
        raise TestbedBackupError(f"Backup '{backup['id']}' is missing testbed snapshot metadata")

    project_root = _project_root(project_id)
    _ensure_reset_runs_outside_target(project_root)
    try:
        restored_snapshot = restore_project_snapshot(
            str(snapshot_id),
            project_id=project_id,
            cwd=project_root,
        )
    except SnapshotError as exc:
        raise TestbedBackupError(str(exc)) from exc

    db_restored = False
    if _has_database(backup):
        restore_result = restore_backup(
            project_id=project_id,
            backup_id=backup["id"],
            db_only=True,
        )
        if restore_result.get("status") != "completed":
            raise TestbedBackupError(str(restore_result.get("error") or "Database restore failed"))
        db_restored = True

    rebuild_output: dict[str, Any] | None = (
        _run_project_rebuild(project_id, project_root) if rebuild else None
    )
    return {
        "project_id": project_id,
        "backup_id": backup["id"],
        "backup_name": backup.get("name"),
        "snapshot_id": restored_snapshot.id,
        "snapshot_name": restored_snapshot.name,
        "db_restored": db_restored,
        "files_restored": True,
        "rebuild_ran": bool(rebuild_output.get("ran")) if rebuild_output else False,
        "rebuild_method": rebuild_output.get("method") if rebuild_output else None,
        "rebuild_reason": rebuild_output.get("reason") if rebuild_output else None,
        "rebuild_output": rebuild_output,
    }
