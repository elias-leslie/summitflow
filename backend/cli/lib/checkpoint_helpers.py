"""Private helpers for checkpoint.py — not part of the public API."""

from __future__ import annotations

import subprocess
import sys


def create_worktree_resources(
    task_id: str, base_branch: str, project_id: str
) -> tuple[str, int, int]:
    """Create worktree and allocate ports; returns (worktree_path, backend_port, frontend_port)."""
    from .port_manager import allocate_ports
    from .worktree import WorktreeError, create_worktree

    try:
        worktree_info = create_worktree(task_id, base_branch, project_id)
        worktree_path = str(worktree_info.path)
        print(f"Created worktree: {worktree_path}")
    except WorktreeError as e:
        print(f"Error: Failed to create worktree: {e}", file=sys.stderr)
        sys.exit(1)

    ports = allocate_ports(task_id, project_id=project_id)
    print(f"Allocated ports: backend={ports.backend_port}, frontend={ports.frontend_port}")
    return worktree_path, ports.backend_port, ports.frontend_port


def create_legacy_branch(task_id: str) -> None:
    """Create a legacy in-repo branch for task_id."""
    try:
        subprocess.run(
            ["git", "checkout", "-b", f"{task_id}/main"],
            check=True, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"Error: Failed to create git branch: {e.stderr}", file=sys.stderr)
        sys.exit(1)
