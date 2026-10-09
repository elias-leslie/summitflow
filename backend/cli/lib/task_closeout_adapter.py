"""Local Git/checkpoint infrastructure for the backend task completion module."""
from __future__ import annotations

import subprocess
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any


class LocalCloseoutOperations:
    """Use public local primitives; command handlers contain no task policy."""

    def caller_identity(self) -> str:
        from .task_claims import current_worker_id

        return current_worker_id()

    def source_lock(self, root: Path) -> AbstractContextManager[None]:
        from .acceptance import repo_lock

        return repo_lock(root, purpose="local closeout cleanup")

    def validate_source(self, root: Path, acceptance: dict[str, Any], source_sha: str) -> dict[str, Any]:
        from .acceptance_coordinator import validate_source_receipt

        return validate_source_receipt(root, acceptance, sha=source_sha).reference.to_dict()

    def require_owned_source(self, root: Path, source_sha: str, paths: tuple[str, ...], task: dict[str, Any]) -> None:
        from .acceptance_coordinator import (
            require_scope_matches_revision,
            require_task_created_paths,
        )

        require_scope_matches_revision(root, source_sha, paths)
        require_task_created_paths(root, source_sha, task)
        dirty = subprocess.run(
            ["git", "--no-optional-locks", "status", "--porcelain=v1", "-z", "--untracked-files=all",
             *(["--", *(f":(literal){path}" for path in paths)] if paths else [])],
            cwd=root, capture_output=True, text=True, check=False,
        )
        if dirty.returncode:
            raise ValueError("Cannot inspect selected task paths")
        if dirty.stdout:
            raise ValueError("Selected task paths changed after accepted completion request")

    def cleanup(self, task_id: str, project_id: str, root: Path) -> None:
        from .autosnapshot import capture_lifecycle_baseline
        from .checkpoint import remove_snapshot

        capture_lifecycle_baseline(project_id=project_id, cwd=root)
        remove_snapshot(task_id, project_id=project_id)
        # Lease release remains supplementary; durable checkpoint removal is
        # the recoverable cleanup effect guarded by the task row lock.
        try:
            from .leases import release_task

            release_task(project_id, task_id)
        except Exception:
            pass
