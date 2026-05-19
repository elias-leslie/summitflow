"""Publish helpers for completed `st done` work."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def warn_on_publish_failure(result: Any, output_warning: Any) -> None:
    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    try:
        payload = json.loads(stdout) if stdout else {}
    except json.JSONDecodeError:
        detail = stderr or stdout[:200] or "unknown st commit output"
        output_warning(f"Task completed but publish status was unreadable: {detail}")
        return
    repo_result = payload.get("repos", [{}])[0] if payload.get("repos") else {}
    status = str(repo_result.get("status", payload.get("status", "UNKNOWN")))
    reason = str(repo_result.get("reason", "") or "")
    detail_text = str(repo_result.get("detail", "") or "")
    if result.returncode == 0 and status in {"SUCCESS", "SKIP"}:
        return
    detail = detail_text or reason or stderr or stdout[:200] or "unknown publish failure"
    output_warning(f"Task completed but publish did not complete cleanly: {status} ({detail})")


def cleanup_completed_bookmark(
    st_path: str,
    project_root: str,
    task_id: str,
    *,
    subprocess_module: Any,
    output_warning: Any,
) -> None:
    if not (Path(project_root) / ".jj").is_dir():
        return
    command = [
        st_path,
        "jj",
        "push",
        "--delete-bookmark",
        "--task",
        task_id,
        "--repo",
        project_root,
    ]
    try:
        result = subprocess_module.run(
            command, cwd=project_root, capture_output=True, text=True, check=False, timeout=300
        )
    except (subprocess_module.SubprocessError, OSError) as exc:
        output_warning(f"Task completed but bookmark cleanup failed to start: {exc}")
        return
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown bookmark cleanup failure"
        output_warning(f"Task completed but bookmark cleanup failed: {detail[:200]}")


def publish_completed_work(
    task_id: str,
    project_id: str | None,
    *,
    deps: dict[str, Any],
) -> None:
    """Publish direct-main work so completed tasks do not leave repos ahead/dirty."""
    if not project_id:
        return
    try:
        from app.storage.projects import get_project_root_path
    except Exception:
        return
    project_root = get_project_root_path(project_id)
    if not project_root:
        deps["output_warning"](f"Task completed but publish skipped: unknown project root for {project_id}")
        return
    st_path = deps["shutil"].which("st") or str(
        deps["get_repo_root"]() / "backend" / ".venv" / "bin" / "st"
    )
    command = [
        st_path,
        "--no-compact",
        "commit",
        "--push",
        "--task",
        task_id,
        "--message",
        f"complete {task_id}",
    ]
    try:
        result = deps["subprocess"].run(
            command, cwd=project_root, capture_output=True, text=True, check=False, timeout=600
        )
    except (deps["subprocess"].SubprocessError, OSError) as exc:
        deps["output_warning"](f"Task completed but publish failed to start: {exc}")
        return
    deps["warn_on_publish_failure"](result)
    if result.returncode == 0:
        deps["cleanup_completed_bookmark"](st_path, project_root, task_id)
