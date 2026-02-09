"""Complex endpoint logic for git operations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from ...storage import tasks as task_store


async def execute_smart_sync(project_root: Path) -> dict[str, Any]:
    """Execute smart sync operation using commit.sh script.

    Args:
        project_root: Path to the project repository

    Returns:
        Dict with sync operation results including status, gates, errors, etc.

    Raises:
        HTTPException: If execution fails
    """
    import asyncio
    from asyncio import subprocess

    script_path = Path.home() / "summitflow" / "scripts" / "commit.sh"

    try:
        proc = await asyncio.create_subprocess_exec(
            str(script_path),
            "--json",
            "--push",
            "--task",
            "smart-sync",
            cwd=project_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        output = stdout.decode()
        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            return {
                "success": False,
                "status": "UNKNOWN",
                "gates": "",
                "errors": [stderr.decode()[:200]],
                "message": "",
                "reason": "json_parse_failed",
                "pushed": False,
                "raw_output": output + stderr.decode(),
            }

        repo_data = data.get("repos", [{}])[0] if data.get("repos") else {}

        return {
            "success": proc.returncode == 0,
            "status": repo_data.get("status", data.get("status", "UNKNOWN")),
            "gates": repo_data.get("gates", ""),
            "errors": [repo_data["reason"]] if repo_data.get("reason") else [],
            "message": repo_data.get("message", ""),
            "reason": repo_data.get("reason", ""),
            "pushed": repo_data.get("pushed", False),
            "raw_output": output,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


def create_pull_request_for_task(
    task_id: str,
    title: str | None,
    body: str | None,
) -> dict[str, str]:
    """Create a pull request for a task.

    Args:
        task_id: The task ID to create PR for
        title: PR title (optional)
        body: PR body/description (optional)

    Returns:
        Dict with pr_url, branch_name, and task_id

    Raises:
        HTTPException: If task not found, has no project, or PR creation fails
    """
    from ...services.git_service import auto_create_pr
    from ...storage.connection import get_connection

    task = task_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    # Get project root
    project_id = task.get("project_id")
    if not project_id:
        raise HTTPException(status_code=400, detail="Task has no project_id")

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT root_path FROM projects WHERE id = %s", (project_id,))
        row = cur.fetchone()
        if not row or not row[0]:
            raise HTTPException(status_code=400, detail="Project has no root_path configured")
        project_root = row[0]

    # Create PR
    try:
        result = auto_create_pr(
            task_id=task_id,
            project_path=project_root,
            title=title,
            body=body,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return {
        "pr_url": result["pr_url"],
        "branch_name": result["branch_name"],
        "task_id": task_id,
    }


def get_task_pr_status(task_id: str) -> dict[str, Any]:
    """Get the pull request status for a task.

    Args:
        task_id: The task ID to check

    Returns:
        Dict with task_id, has_pr, pr_url, branch_name, and optional status

    Raises:
        HTTPException: If task not found
    """
    task = task_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    pr_url = task.get("pull_request_url")
    if not pr_url:
        return {
            "task_id": task_id,
            "has_pr": False,
            "pr_url": None,
            "branch_name": task.get("branch_name"),
        }

    return {
        "task_id": task_id,
        "has_pr": True,
        "pr_url": pr_url,
        "branch_name": task.get("branch_name"),
        "status": task.get("status"),
    }
