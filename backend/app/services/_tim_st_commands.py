"""SummitFlow CLI (st) helpers for task_issue_mapper."""

from __future__ import annotations

import json
import subprocess

from app.services._tim_constants import (
    BACKEND_ISSUE_TYPES,
    DATABASE_ISSUE_TYPES,
    DEFAULT_DOMAIN,
    DEFAULT_PRIORITY,
    FRONTEND_ISSUE_TYPES,
    SEVERITY_PRIORITY,
    ST_COMMAND_TIMEOUT,
    TASK_TITLE_MAX_LEN,
)

from ..logging_config import get_logger

logger = get_logger(__name__)


def run_st_command(args: list[str]) -> tuple[bool, str]:
    """Run an st CLI command and return (success, output)."""
    try:
        result = subprocess.run(
            ["st", *args],
            capture_output=True,
            text=True,
            timeout=ST_COMMAND_TIMEOUT,
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        logger.warning("st command failed: %s", result.stderr)
        return False, result.stderr.strip()
    except subprocess.TimeoutExpired:
        logger.error("st command timed out")
        return False, "Command timed out"
    except FileNotFoundError:
        logger.error("st CLI not found in PATH")
        return False, "st CLI not found"


def severity_to_priority(severity: str) -> int:
    """Map QA issue severity to task priority."""
    return SEVERITY_PRIORITY.get(severity, DEFAULT_PRIORITY)


def issue_type_to_domain(issue_type: str) -> str:
    """Map issue type to domain label."""
    if issue_type in BACKEND_ISSUE_TYPES:
        return "backend"
    if issue_type in FRONTEND_ISSUE_TYPES:
        return "frontend"
    if issue_type in DATABASE_ISSUE_TYPES:
        return "database"
    return DEFAULT_DOMAIN


def _parse_task_id_from_output(output: str, issue_id: int) -> str | None:
    """Parse a task ID from st command JSON or text output."""
    try:
        data = json.loads(output)
        task_id: str | None = data.get("id") or data.get("task_id")
        if task_id:
            logger.info("Created task %s for issue %d", task_id, issue_id)
            return str(task_id)
    except json.JSONDecodeError:
        pass

    # Fallback: extract from text like "Created task: task-abc123"
    if "task-" in output:
        parts = output.split("task-")
        if len(parts) > 1:
            extracted_id = "task-" + parts[1].split()[0].strip()
            logger.info("Created task %s for issue %d", extracted_id, issue_id)
            return extracted_id

    return None


def build_create_task_args(
    project_id: str,
    issue_id: int,
    title: str,
    severity: str,
    issue_type: str,
    description: str | None,
    file_path: str | None,
) -> list[str]:
    """Build the argument list for 'st create'."""
    full_title = f"Fix: {title}"
    if len(full_title) > TASK_TITLE_MAX_LEN:
        full_title = full_title[: TASK_TITLE_MAX_LEN - 3] + "..."

    desc_parts = [f"Auto-generated from QA issue #{issue_id}"]
    if description:
        desc_parts.append(description)
    if file_path:
        desc_parts.append(f"File: {file_path}")
    full_description = "\n\n".join(desc_parts)

    priority = severity_to_priority(severity)
    domain = issue_type_to_domain(issue_type)

    return [
        "-P", project_id,
        "create", full_title,
        "-t", "bug",
        "-p", str(priority),
        "-l", f"complexity:small,domains:{domain}",
        "-d", full_description,
        "--json",
    ]
