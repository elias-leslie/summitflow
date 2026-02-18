"""Complex endpoint logic for git operations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import HTTPException


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
