"""Task-Issue Mapper Service for Self-Healing.

Maps QA issues to SummitFlow tasks and handles auto-close
when issues are resolved.
"""

import logging
import subprocess
from dataclasses import dataclass

from psycopg import Connection

from app.storage.connection import get_connection

logger = logging.getLogger(__name__)


@dataclass
class QAIssue:
    """Minimal issue data needed for task mapping."""

    id: int
    project_id: str
    issue_type: str
    severity: str
    title: str
    description: str | None
    file_path: str | None
    st_task_id: str | None


def _run_st_command(args: list[str]) -> tuple[bool, str]:
    """Run an st CLI command and return (success, output)."""
    try:
        result = subprocess.run(
            ["st", *args],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        else:
            logger.warning(f"st command failed: {result.stderr}")
            return False, result.stderr.strip()
    except subprocess.TimeoutExpired:
        logger.error("st command timed out")
        return False, "Command timed out"
    except FileNotFoundError:
        logger.error("st CLI not found in PATH")
        return False, "st CLI not found"


def _severity_to_priority(severity: str) -> int:
    """Map QA issue severity to task priority."""
    mapping = {
        "critical": 0,
        "high": 1,
        "medium": 2,
        "low": 3,
    }
    return mapping.get(severity, 2)


def _issue_type_to_domain(issue_type: str) -> str:
    """Map issue type to domain label."""
    backend_types = {"complexity", "dead_code", "missing_test"}
    frontend_types = {"stale_page", "missing_component"}
    database_types = {"stale_table", "orphan_column"}

    if issue_type in backend_types:
        return "backend"
    elif issue_type in frontend_types:
        return "frontend"
    elif issue_type in database_types:
        return "database"
    return "backend"  # Default to backend


def create_task_for_issue(issue: QAIssue) -> str | None:
    """Create a SummitFlow task for a QA issue.

    Args:
        issue: The QA issue to create a task for

    Returns:
        The task ID if created, None if failed
    """
    priority = _severity_to_priority(issue.severity)
    domain = _issue_type_to_domain(issue.issue_type)

    # Build task title
    title = f"Fix: {issue.title}"
    if len(title) > 100:
        title = title[:97] + "..."

    # Build description
    description_parts = [f"Auto-generated from QA issue #{issue.id}"]
    if issue.description:
        description_parts.append(issue.description)
    if issue.file_path:
        description_parts.append(f"File: {issue.file_path}")
    description = "\n\n".join(description_parts)

    # Build st create command
    args = [
        "create",
        title,
        "-t",
        "bug",
        "-p",
        str(priority),
        "-l",
        f"complexity:small,domains:{domain}",
        "-d",
        description,
        "--json",  # Get JSON output for parsing task ID
    ]

    success, output = _run_st_command(args)
    if not success:
        logger.error(f"Failed to create task for issue {issue.id}: {output}")
        return None

    # Parse task ID from JSON output
    try:
        import json

        data = json.loads(output)
        task_id: str | None = data.get("id") or data.get("task_id")
        if task_id:
            logger.info(f"Created task {task_id} for issue {issue.id}")
            return str(task_id)
    except json.JSONDecodeError:
        # Fallback: try to extract ID from text output
        # Output might be like "Created task: task-abc123"
        if "task-" in output:
            parts = output.split("task-")
            if len(parts) > 1:
                extracted_id = "task-" + parts[1].split()[0].strip()
                logger.info(f"Created task {extracted_id} for issue {issue.id}")
                return extracted_id

    logger.error(f"Could not parse task ID from output: {output}")
    return None


def link_issue_to_task(
    issue_id: int,
    task_id: str,
    conn: Connection | None = None,
) -> bool:
    """Link a QA issue to a SummitFlow task.

    Args:
        issue_id: The QA issue ID
        task_id: The SummitFlow task ID
        conn: Optional database connection

    Returns:
        True if linked successfully
    """

    def _do_link(c: Connection) -> bool:
        with c.cursor() as cur:
            cur.execute(
                """
                UPDATE qa_issues
                SET st_task_id = %s, updated_at = NOW()
                WHERE id = %s
                """,
                (task_id, issue_id),
            )
            if cur.rowcount > 0:
                logger.info(f"Linked issue {issue_id} to task {task_id}")
                return True
            logger.warning(f"Issue {issue_id} not found for linking")
            return False

    if conn:
        return _do_link(conn)
    else:
        with get_connection() as c:
            result = _do_link(c)
            c.commit()
            return result


def close_task_for_issue(issue: QAIssue) -> bool:
    """Close the SummitFlow task linked to a QA issue.

    Uses 'cancel' for pending tasks (not yet started) and 'close' for
    tasks that are running or paused.

    Args:
        issue: The QA issue with st_task_id set

    Returns:
        True if task was closed successfully
    """
    if not issue.st_task_id:
        logger.debug(f"Issue {issue.id} has no linked task to close")
        return False

    # First check task status to determine the right command
    status_success, status_output = _run_st_command(["show", issue.st_task_id, "--json"])

    command = "close"  # Default
    if status_success:
        try:
            import json

            task_data = json.loads(status_output)
            task_status = task_data.get("status", "")
            # Use cancel for pending tasks (issue resolved before work started)
            if task_status == "pending":
                command = "cancel"
        except json.JSONDecodeError:
            pass  # Fall back to close

    reason = f"Auto-closed: QA issue #{issue.id} resolved"
    args = [
        command,
        issue.st_task_id,
        "--reason",
        reason,
    ]
    if command == "close":
        args.append("--force")  # Skip validation prompts for close

    success, output = _run_st_command(args)
    if success:
        logger.info(f"Auto-{command}d task {issue.st_task_id} for resolved issue {issue.id}")
        return True
    else:
        logger.warning(f"Failed to {command} task {issue.st_task_id}: {output}")
        return False


def get_linked_task(
    issue_id: int,
    conn: Connection | None = None,
) -> str | None:
    """Get the SummitFlow task ID linked to a QA issue.

    Args:
        issue_id: The QA issue ID
        conn: Optional database connection

    Returns:
        The task ID if linked, None otherwise
    """

    def _do_get(c: Connection) -> str | None:
        with c.cursor() as cur:
            cur.execute(
                "SELECT st_task_id FROM qa_issues WHERE id = %s",
                (issue_id,),
            )
            row = cur.fetchone()
            return row[0] if row else None

    if conn:
        return _do_get(conn)
    else:
        with get_connection() as c:
            return _do_get(c)


def get_issue_by_id(
    issue_id: int,
    conn: Connection | None = None,
) -> QAIssue | None:
    """Get a QA issue by ID.

    Args:
        issue_id: The QA issue ID
        conn: Optional database connection

    Returns:
        The QAIssue if found, None otherwise
    """

    def _do_get(c: Connection) -> QAIssue | None:
        with c.cursor() as cur:
            cur.execute(
                """
                SELECT id, project_id, issue_type, severity, title,
                       description, file_path, st_task_id
                FROM qa_issues
                WHERE id = %s
                """,
                (issue_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return QAIssue(
                id=row[0],
                project_id=row[1],
                issue_type=row[2],
                severity=row[3],
                title=row[4],
                description=row[5],
                file_path=row[6],
                st_task_id=row[7],
            )

    if conn:
        return _do_get(conn)
    else:
        with get_connection() as c:
            return _do_get(c)


def create_and_link_task_for_issue(issue_id: int) -> str | None:
    """Create a task for an issue and link them.

    Convenience function that combines create_task_for_issue and link_issue_to_task.

    Args:
        issue_id: The QA issue ID

    Returns:
        The task ID if created and linked, None otherwise
    """
    issue = get_issue_by_id(issue_id)
    if not issue:
        logger.error(f"Issue {issue_id} not found")
        return None

    if issue.st_task_id:
        logger.debug(f"Issue {issue_id} already linked to task {issue.st_task_id}")
        return issue.st_task_id

    task_id = create_task_for_issue(issue)
    if not task_id:
        return None

    if link_issue_to_task(issue_id, task_id):
        return task_id

    return None
