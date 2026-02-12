"""Git rollback operations for recovery.

Handles reverting project state to a known good commit.
"""

from __future__ import annotations

import asyncio
from typing import Any

from ...logging_config import get_logger
from ...storage.connection import get_connection

logger = get_logger(__name__)


async def rollback_to_commit(
    project_id: str,
    commit_sha: str,
) -> dict[str, Any]:
    """Rollback project to a specific commit.

    Args:
        project_id: Project ID
        commit_sha: Git commit SHA to rollback to

    Returns:
        Dict with 'success', 'message', and optional 'error'.
    """
    project_root = _get_project_root(project_id)
    if not project_root["success"]:
        return project_root

    root_path = project_root["root_path"]

    commit_valid = await _verify_commit_exists(root_path, commit_sha)
    if not commit_valid["success"]:
        return commit_valid

    await _stash_if_dirty(root_path, project_id, commit_sha)

    return await _perform_rollback(root_path, project_id, commit_sha)


def _get_project_root(project_id: str) -> dict[str, Any]:
    """Get project root path from database.

    Args:
        project_id: Project ID

    Returns:
        Dict with success, root_path, or error.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT root_path FROM projects WHERE id = %s", (project_id,))
        row = cur.fetchone()
        project = {"root_path": row[0]} if row else None

    if not project:
        return {
            "success": False,
            "message": "Project not found",
            "error": f"No project with ID: {project_id}",
        }

    project_root = project.get("root_path")
    if not project_root:
        return {
            "success": False,
            "message": "Project root not configured",
            "error": "Project has no root_path set",
        }

    return {"success": True, "root_path": project_root}


async def _verify_commit_exists(
    project_root: str,
    commit_sha: str,
) -> dict[str, Any]:
    """Verify that a commit exists in the git repository.

    Args:
        project_root: Path to project root
        commit_sha: Commit SHA to verify

    Returns:
        Dict with success status and optional error.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            project_root,
            "cat-file",
            "-t",
            commit_sha,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, _stderr = await proc.communicate()

        if proc.returncode != 0:
            return {
                "success": False,
                "message": "Commit not found",
                "error": f"Commit {commit_sha} does not exist",
            }

        return {"success": True}

    except Exception as e:
        return {
            "success": False,
            "message": "Git error",
            "error": str(e),
        }


async def _stash_if_dirty(
    project_root: str,
    project_id: str,
    commit_sha: str,
) -> None:
    """Stash uncommitted changes if repository is dirty.

    Args:
        project_root: Path to project root
        project_id: Project ID (for logging)
        commit_sha: Target commit SHA (for stash message)
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            project_root,
            "status",
            "--porcelain",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _stderr = await proc.communicate()

        if not stdout.strip():
            return

        logger.warning("stashing_before_rollback", project_id=project_id)
        stash_proc = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            project_root,
            "stash",
            "push",
            "-m",
            f"Auto-stash before rollback to {commit_sha[:8]}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await stash_proc.communicate()

    except Exception as e:
        logger.warning("stash_check_failed", error=str(e))


async def _perform_rollback(
    project_root: str,
    project_id: str,
    commit_sha: str,
) -> dict[str, Any]:
    """Execute git reset to rollback to specified commit.

    Args:
        project_root: Path to project root
        project_id: Project ID (for logging)
        commit_sha: Commit SHA to rollback to

    Returns:
        Dict with success status, message, and optional error.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            project_root,
            "reset",
            "--hard",
            commit_sha,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            return {
                "success": False,
                "message": "Rollback failed",
                "error": stderr.decode() if stderr else "Unknown error",
            }

        logger.info("rollback_success", project_id=project_id, commit_sha=commit_sha[:8])

        return {
            "success": True,
            "message": f"Rolled back to {commit_sha[:8]}",
            "commit_sha": commit_sha,
        }

    except Exception as e:
        return {
            "success": False,
            "message": "Rollback error",
            "error": str(e),
        }
