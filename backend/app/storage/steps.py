"""Steps storage layer - CRUD operations for subtask steps.

This module provides data access for the task_subtask_steps table, which stores
normalized step data for granular completion tracking within subtasks.

Each step can have a verify_command for the tight agent feedback loop:
  code → run verify_command → fix if fail → repeat
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from psycopg.rows import TupleRow

from .connection import get_connection

logger = logging.getLogger(__name__)

# Column list for all step SELECT/RETURNING queries (12 columns)
STEP_COLUMNS = """id, subtask_id, step_number, description, spec, passes, passed_at, created_at, verify_command, expected_output, status, fix_step_number"""

# Expected column count for row validation
EXPECTED_STEP_COLUMNS = 12

# Valid step status values
STEP_STATUS_PENDING = "pending"
STEP_STATUS_PASSED = "passed"
STEP_STATUS_FAILED = "failed"
STEP_STATUS_PLAN_DEFECT = "plan_defect"
VALID_STEP_STATUSES = {
    STEP_STATUS_PENDING,
    STEP_STATUS_PASSED,
    STEP_STATUS_FAILED,
    STEP_STATUS_PLAN_DEFECT,
}

# Timeout for verify_command execution (120 seconds / 2 minutes)
# Increased from 30s to allow full test suites to complete
VERIFY_COMMAND_TIMEOUT = 120


def _row_to_dict(row: TupleRow | tuple[Any, ...] | None) -> dict[str, Any]:
    """Convert a database row to a step dict.

    Column order (12 columns):
        id, subtask_id, step_number, description, spec, passes, passed_at, created_at,
        verify_command, expected_output, status, fix_step_number
    """
    if row is None:
        raise ValueError("Row cannot be None")
    if len(row) != EXPECTED_STEP_COLUMNS:
        raise ValueError(f"Expected {EXPECTED_STEP_COLUMNS} columns, got {len(row)}")
    return {
        "id": row[0],
        "subtask_id": row[1],
        "step_number": row[2],
        "description": row[3],
        "spec": row[4],
        "passes": row[5],
        "passed_at": row[6].isoformat() if row[6] else None,
        "created_at": row[7].isoformat() if row[7] else None,
        "verify_command": row[8],
        "expected_output": row[9],
        "status": row[10] or STEP_STATUS_PENDING,
        "fix_step_number": row[11],
    }


def create_step(
    subtask_id: str,
    step_number: int,
    description: str,
    spec: dict[str, Any] | None = None,
    verify_command: str | None = None,
    expected_output: str | None = None,
) -> dict[str, Any]:
    """Create a new step for a subtask.

    Args:
        subtask_id: Parent subtask ID (e.g., "task-abc123-1.1")
        step_number: 1-indexed step number within subtask
        description: Step description text
        spec: Optional JSONB spec for implementation details
        verify_command: Bash command to verify step completion
        expected_output: Expected output pattern for verification

    Returns:
        The created step dict.

    Raises:
        Exception: If subtask_id doesn't exist (FK constraint violation)
    """

    spec_json = json.dumps(spec) if spec else None

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO task_subtask_steps (subtask_id, step_number, description, spec, verify_command, expected_output)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (subtask_id, step_number) DO UPDATE SET
                description = EXCLUDED.description,
                spec = EXCLUDED.spec,
                verify_command = EXCLUDED.verify_command,
                expected_output = EXCLUDED.expected_output
            RETURNING {STEP_COLUMNS}
            """,
            (subtask_id, step_number, description, spec_json, verify_command, expected_output),
        )
        row = cur.fetchone()
        conn.commit()

    logger.debug("Created step %d for subtask %s", step_number, subtask_id)
    return _row_to_dict(row)


def get_steps_for_subtask(subtask_id: str) -> list[dict[str, Any]]:
    """Get all steps for a subtask, ordered by step_number.

    Args:
        subtask_id: Parent subtask ID

    Returns:
        List of step dicts, ordered by step_number.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {STEP_COLUMNS}
            FROM task_subtask_steps
            WHERE subtask_id = %s
            ORDER BY step_number
            """,
            (subtask_id,),
        )
        rows = cur.fetchall()

    return [_row_to_dict(row) for row in rows]


def get_step(subtask_id: str, step_number: int) -> dict[str, Any] | None:
    """Get a single step by subtask_id and step_number.

    Args:
        subtask_id: Parent subtask ID
        step_number: Step number (1-indexed)

    Returns:
        Step dict or None if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {STEP_COLUMNS}
            FROM task_subtask_steps
            WHERE subtask_id = %s AND step_number = %s
            """,
            (subtask_id, step_number),
        )
        row = cur.fetchone()

    if not row:
        return None

    return _row_to_dict(row)


class StepGateError(Exception):
    """Raised when step completion gate is violated."""

    def __init__(self, message: str, missing_steps: list[int] | None = None):
        super().__init__(message)
        self.missing_steps = missing_steps or []


class StepVerificationError(Exception):
    """Raised when step completion is blocked by failed verification.

    Attributes:
        step_number: The step that failed verification
        output: The verification command output
        exit_code: The exit code from the verify_command
        verify_command: The command that was executed
        cwd: The working directory used for execution
        next_steps: Guidance for what to do next
    """

    # Standard guidance for all verification failures
    NEXT_STEPS_GUIDANCE = """
Next steps:
  1. Fix your implementation to match the expected behavior
  2. If the plan is wrong, create a fix subtask: st subtask create <parent-id> -d "Fix: ..."
  3. Log the issue: st log <task-id> "Plan defect: ..."

Do NOT modify the verify_command - verification gates are immutable."""

    def __init__(
        self,
        message: str,
        step_number: int,
        output: str,
        exit_code: int = 1,
        verify_command: str | None = None,
        cwd: str | None = None,
    ):
        # Append guidance to message
        full_message = f"{message}\n{self.NEXT_STEPS_GUIDANCE}"
        super().__init__(full_message)
        self.step_number = step_number
        self.output = output
        self.exit_code = exit_code
        self.verify_command = verify_command
        self.cwd = cwd
        self.next_steps = self.NEXT_STEPS_GUIDANCE


def _resolve_venv_paths(cmd: str, cwd: str | None) -> str:
    """Resolve .venv paths to absolute paths.

    For multi-project tasks, if the command explicitly `cd`s to a different
    project's directory, we use that project's venv instead.

    Args:
        cmd: Command that may contain .venv references
        cwd: Working directory

    Returns:
        Command with absolute venv paths
    """
    if ".venv" not in cmd:
        return cmd

    if not cwd:
        return cmd

    from .projects import get_project_root_path

    # Check if command explicitly cd's to a different project's backend
    # Pattern: cd /home/kasadis/<project>/backend or cd /home/kasadis/<project>
    cd_match = re.search(r"cd\s+(/home/kasadis/([^/\s]+)(?:/backend)?)\s*&&", cmd)
    if cd_match:
        explicit_project = cd_match.group(2)
        explicit_repo = get_project_root_path(explicit_project)
        if explicit_repo:
            explicit_venv = Path(explicit_repo) / "backend" / ".venv"
            if explicit_venv.exists():
                abs_venv = f"{explicit_venv}/bin/"
                # Handle both `backend/.venv/bin/` and `.venv/bin/` patterns
                if "backend/.venv/bin/" in cmd:
                    return cmd.replace("backend/.venv/bin/", abs_venv)
                return cmd.replace(".venv/bin/", abs_venv)

    # Check if cwd has backend/.venv
    cwd_path = Path(cwd)
    if (cwd_path / "backend" / ".venv").exists():
        abs_venv = f"{cwd_path}/backend/.venv/bin/"
        # Handle both `backend/.venv/bin/` and `.venv/bin/` patterns
        if "backend/.venv/bin/" in cmd:
            return cmd.replace("backend/.venv/bin/", abs_venv)
        return cmd.replace(".venv/bin/", abs_venv)

    # Try parent directory (for when cwd is backend/)
    if cwd_path.name == "backend" and (cwd_path / ".venv").exists():
        abs_venv = f"{cwd_path}/.venv/bin/"
        if "backend/.venv/bin/" in cmd:
            # Strip redundant backend/ since we're already in backend/
            return cmd.replace("backend/.venv/bin/", abs_venv)
        return cmd.replace(".venv/bin/", abs_venv)

    return cmd


def _parse_expected(expected: str | None) -> tuple[str, str | None]:
    """Parse expected_output into (check_type, value).

    Returns:
        (check_type, value) where check_type is one of:
        - "exit_code": Check returncode == 0 (no output check)
        - "contains": Check value in output

    Exit code patterns (all mean "just check exit code = 0"):
        - "exit code 0", "exit code: 0"
        - "exit 0", "exit: 0", "exit:0"
        - "exit_code", "exitcode"
        - "success", "ok", "pass"
        - "lint:ok", "types:ok", "test:ok"
    """
    if not expected:
        return ("exit_code", None)

    expected_lower = expected.lower().strip()

    # Exit code patterns - just check returncode == 0
    exit_code_patterns = (
        "exit code",  # "exit code 0", "exit code: 0"
        "exit 0",
        "exit: 0",
        "exit:0",
        "exit_code",
        "exitcode",
        "success",
        "ok",
        "pass",
        "lint:ok",
        "types:ok",
        "test:ok",
    )
    if any(expected_lower.startswith(p) or expected_lower == p for p in exit_code_patterns):
        return ("exit_code", None)

    if expected_lower.startswith("contains:"):
        return ("contains", expected[9:].strip())

    return ("contains", expected)


def run_verify_command(
    verify_command: str,
    timeout: int = VERIFY_COMMAND_TIMEOUT,
    cwd: str | None = None,
) -> tuple[str, int, str]:
    """Execute a verify_command and return classification.

    Args:
        verify_command: The bash command to run
        timeout: Command timeout in seconds
        cwd: Working directory to run from. If None, uses /home/kasadis/summitflow
             as fallback for backwards compatibility.

    Returns:
        Tuple of (status, exit_code, output) where status is one of:
        - 'passed': Exit code 0
        - 'failed': Exit code != 0
        - 'crashed': Exit code 126-127 or exception
    """
    # Default to summitflow for backwards compatibility
    working_dir = cwd or "/home/kasadis/summitflow"

    # Resolve .venv paths to absolute paths
    resolved_command = _resolve_venv_paths(verify_command, working_dir)

    try:
        # Use bash explicitly since commands may use bash-specific features like 'source'
        result = subprocess.run(
            ["bash", "-c", resolved_command],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=working_dir,
        )

        exit_code = result.returncode
        output = result.stdout + result.stderr

        # Classify based on exit code
        if exit_code == 0:
            return ("passed", 0, output)
        elif 1 <= exit_code <= 125:
            return ("failed", exit_code, output)
        else:  # 126-127 = command not found or not executable
            return ("crashed", exit_code, output)

    except subprocess.TimeoutExpired:
        return ("crashed", -1, f"Command timed out after {timeout}s")
    except Exception as e:
        return ("crashed", -1, str(e))


def update_step_passes(
    subtask_id: str,
    step_number: int,
    passes: bool,
    project_root: str | None = None,
) -> dict[str, Any] | None:
    """Update step passes status with mandatory verification.

    When passes is set to True:
    1. Fetches the step's verify_command (required)
    2. Runs the verify_command
    3. Only marks step passes=true if verification passes (exit code 0)
    4. Raises StepVerificationError on failure or missing verify_command

    When passes is set to False, clears passed_at without verification.

    Args:
        subtask_id: Parent subtask ID
        step_number: Step number to update
        passes: Whether the step passes
        project_root: Working directory for verify_command execution.
                      If None, defaults to /home/kasadis/summitflow.

    Returns:
        Updated step dict or None if not found.

    Raises:
        StepVerificationError: If verification fails or verify_command is missing
    """
    # If marking as failed/incomplete, no verification needed
    if not passes:
        passed_at = None
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE task_subtask_steps
                SET passes = %s, passed_at = %s
                WHERE subtask_id = %s AND step_number = %s
                RETURNING {STEP_COLUMNS}
                """,
                (passes, passed_at, subtask_id, step_number),
            )
            row = cur.fetchone()
            conn.commit()

        if not row:
            logger.warning("Step %d not found for subtask %s", step_number, subtask_id)
            return None

        logger.debug("Updated step %d passes=False for subtask %s", step_number, subtask_id)
        return _row_to_dict(row)

    # passes=True: Get the step to check for verify_command
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {STEP_COLUMNS}
            FROM task_subtask_steps
            WHERE subtask_id = %s AND step_number = %s
            """,
            (subtask_id, step_number),
        )
        row = cur.fetchone()

    if not row:
        logger.warning("Step %d not found for subtask %s", step_number, subtask_id)
        return None

    step = _row_to_dict(row)
    verify_command = step.get("verify_command")
    expected_output = step.get("expected_output")

    # verify_command is required - fail if missing
    if not verify_command:
        raise StepVerificationError(
            message=f"Step {step_number} has no verify_command. Every step must have verification.",
            step_number=step_number,
            output="",
            exit_code=-1,
            verify_command=None,
            cwd=project_root,
        )

    # expected_output is required - fail if missing
    if not expected_output:
        raise StepVerificationError(
            message=f"Step {step_number} has no expected_output. Every step must define what success looks like.",
            step_number=step_number,
            output="",
            exit_code=-1,
            verify_command=verify_command,
            cwd=project_root,
        )

    # Parse expected output to determine check type
    check_type, check_value = _parse_expected(expected_output)

    # Run verification from project root
    status, exit_code, output = run_verify_command(verify_command, cwd=project_root)

    if status != "passed":
        message = (
            f"Step {step_number} verification failed (exit code {exit_code}).\n"
            f"Command: {verify_command}\n"
            f"Expected: {expected_output}\n"
            f"Output: {output[:500]}"
        )

        raise StepVerificationError(
            message=message,
            step_number=step_number,
            output=output,
            exit_code=exit_code,
            verify_command=verify_command,
            cwd=project_root,
        )

    # For "exit_code" check type, exit code 0 is sufficient (already passed above)
    # For "contains" check type, verify the expected value appears in output
    if check_type == "contains" and check_value and check_value not in output:
        message = (
            f"Step {step_number} verification failed: expected output not found.\n"
            f"Command: {verify_command}\n"
            f"Expected: {expected_output}\n"
            f"Actual output: {output[:500]}"
        )

        raise StepVerificationError(
            message=message,
            step_number=step_number,
            output=output,
            exit_code=0,
            verify_command=verify_command,
            cwd=project_root,
        )

    logger.info("Step %d verify_command passed for subtask %s", step_number, subtask_id)

    # Verification passed - mark step as passed
    passed_at = datetime.now(UTC)

    with get_connection() as conn, conn.cursor() as cur:
        # Log incomplete previous steps for context (informational only)
        if step_number > 1:
            cur.execute(
                """
                SELECT step_number FROM task_subtask_steps
                WHERE subtask_id = %s AND step_number < %s AND passes = FALSE
                ORDER BY step_number
                """,
                (subtask_id, step_number),
            )
            incomplete = [row[0] for row in cur.fetchall()]
            if incomplete:
                logger.info(
                    f"Marking step {step_number} as passed with incomplete previous steps: {incomplete}"
                )

        cur.execute(
            f"""
            UPDATE task_subtask_steps
            SET passes = %s, passed_at = %s
            WHERE subtask_id = %s AND step_number = %s
            RETURNING {STEP_COLUMNS}
            """,
            (passes, passed_at, subtask_id, step_number),
        )
        row = cur.fetchone()
        conn.commit()

    if not row:
        logger.warning("Step %d not found for subtask %s", step_number, subtask_id)
        return None

    logger.info("Step %d passed for subtask %s (verified)", step_number, subtask_id)
    return _row_to_dict(row)


def update_step_fields(
    subtask_id: str,
    step_number: int,
    description: str | None = None,
) -> dict[str, Any] | None:
    """Update step description.

    NOTE: verify_command and expected_output are immutable after creation.
    Only the description field can be updated.

    Args:
        subtask_id: Parent subtask ID
        step_number: Step number to update
        description: Step description

    Returns:
        Updated step dict or None if not found.
    """
    # Build dynamic UPDATE based on provided fields
    updates: list[str] = []
    values: list[Any] = []

    if description is not None:
        updates.append("description = %s")
        values.append(description)

    if not updates:
        # Nothing to update - just return existing step
        return get_step(subtask_id, step_number)

    values.extend([subtask_id, step_number])

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE task_subtask_steps
            SET {", ".join(updates)}
            WHERE subtask_id = %s AND step_number = %s
            RETURNING {STEP_COLUMNS}
            """,
            tuple(values),
        )
        row = cur.fetchone()
        conn.commit()

    if not row:
        logger.warning("Step %d not found for subtask %s", step_number, subtask_id)
        return None

    logger.info("Updated step %d fields for subtask %s", step_number, subtask_id)
    return _row_to_dict(row)


def bulk_create_steps(
    subtask_id: str,
    steps: Sequence[str | dict[str, Any]],
) -> list[dict[str, Any]]:
    """Create multiple steps for a subtask in a single transaction.

    Steps are automatically numbered starting from 1.

    Args:
        subtask_id: Parent subtask ID
        steps: List of step items - either strings (description only)
               or dicts with {description, spec, verify_command, expected_output}

    Returns:
        List of created step dicts.

    Raises:
        Exception: If subtask_id doesn't exist or on DB error.
    """
    if not steps:
        return []

    created = []
    with get_connection() as conn, conn.cursor() as cur:
        for idx, step in enumerate(steps, start=1):
            if isinstance(step, str):
                description = step
                spec = None
                verify_command = None
                expected_output = None
            else:
                description = step.get("description", "")
                spec = step.get("spec")
                verify_command = step.get("verify_command")
                expected_output = step.get("expected_output")

            spec_json = json.dumps(spec) if spec else None
            cur.execute(
                f"""
                INSERT INTO task_subtask_steps (subtask_id, step_number, description, spec, verify_command, expected_output)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (subtask_id, step_number) DO UPDATE SET
                    description = EXCLUDED.description,
                    spec = EXCLUDED.spec,
                    verify_command = EXCLUDED.verify_command,
                    expected_output = EXCLUDED.expected_output
                RETURNING {STEP_COLUMNS}
                """,
                (subtask_id, idx, description, spec_json, verify_command, expected_output),
            )
            row = cur.fetchone()
            created.append(_row_to_dict(row))

        conn.commit()

    logger.info("Created %d steps for subtask %s", len(created), subtask_id)
    return created


def append_steps(
    subtask_id: str,
    steps: Sequence[str | dict[str, Any]],
) -> list[dict[str, Any]]:
    """Append steps to a subtask, continuing from the highest existing step number.

    Unlike bulk_create_steps which starts at 1, this finds the max step_number
    and continues from there.

    Args:
        subtask_id: Parent subtask ID
        steps: List of step items - either strings (description only)
               or dicts with {description, spec, verify_command, expected_output}

    Returns:
        List of created step dicts.

    Raises:
        Exception: If subtask_id doesn't exist or on DB error.
    """
    if not steps:
        return []

    with get_connection() as conn, conn.cursor() as cur:
        # Find the current max step number
        cur.execute(
            "SELECT COALESCE(MAX(step_number), 0) FROM task_subtask_steps WHERE subtask_id = %s",
            (subtask_id,),
        )
        row = cur.fetchone()
        max_step: int = row[0] if row else 0

        created = []
        for idx, step in enumerate(steps, start=max_step + 1):
            if isinstance(step, str):
                description = step
                spec = None
                verify_command = None
                expected_output = None
            else:
                description = step.get("description", "")
                spec = step.get("spec")
                verify_command = step.get("verify_command")
                expected_output = step.get("expected_output")

            spec_json = json.dumps(spec) if spec else None
            cur.execute(
                f"""
                INSERT INTO task_subtask_steps (subtask_id, step_number, description, spec, verify_command, expected_output)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (subtask_id, step_number) DO UPDATE SET
                    description = EXCLUDED.description,
                    spec = EXCLUDED.spec,
                    verify_command = EXCLUDED.verify_command,
                    expected_output = EXCLUDED.expected_output
                RETURNING {STEP_COLUMNS}
                """,
                (subtask_id, idx, description, spec_json, verify_command, expected_output),
            )
            row = cur.fetchone()
            created.append(_row_to_dict(row))

        conn.commit()

    logger.info(
        "Appended %d steps to subtask %s (starting at step %d)",
        len(created),
        subtask_id,
        max_step + 1,
    )
    return created


def delete_steps_for_subtask(subtask_id: str) -> int:
    """Delete all steps for a subtask.

    Args:
        subtask_id: Parent subtask ID

    Returns:
        Number of steps deleted.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM task_subtask_steps WHERE subtask_id = %s",
            (subtask_id,),
        )
        count: int = cur.rowcount
        conn.commit()

    logger.debug("Deleted %d steps for subtask %s", count, subtask_id)
    return count


class StepDeletionResult:
    """Result of step deletion with audit info."""

    def __init__(
        self,
        deleted: bool,
        was_passed: bool = False,
        subtask_invalidated: bool = False,
        step_details: dict[str, Any] | None = None,
    ):
        self.deleted = deleted
        self.was_passed = was_passed
        self.subtask_invalidated = subtask_invalidated
        self.step_details = step_details


def delete_step(
    subtask_id: str,
    step_number: int,
    *,
    force: bool = False,
    emit_event: bool = True,
) -> StepDeletionResult:
    """Delete a single step from a subtask with audit logging.

    IMPORTANT: Deleting passed steps invalidates the parent subtask's passes status.
    This is a safeguard against gaming the verification system by deleting steps
    that have already been verified.

    Args:
        subtask_id: Parent subtask ID (e.g., "task-abc123-1.1")
        step_number: Step number to delete
        force: If True, allow deletion of passed steps (required for passed steps)
        emit_event: If True, emit audit event for the deletion

    Returns:
        StepDeletionResult with deletion status and audit info.

    Raises:
        StepGateError: If trying to delete a passed step without force=True
    """
    # First, fetch the step to capture state before deletion
    step = get_step(subtask_id, step_number)
    if not step:
        logger.warning("Step %d not found in subtask %s", step_number, subtask_id)
        return StepDeletionResult(deleted=False)

    was_passed = step.get("passes", False)

    # Gate: Require force=True to delete passed steps
    if was_passed and not force:
        raise StepGateError(
            f"Step {step_number} has already passed verification. "
            "Deleting passed steps requires --force flag. "
            "This is a safeguard against gaming the verification system.",
            missing_steps=[step_number],
        )

    # Delete the step
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM task_subtask_steps WHERE subtask_id = %s AND step_number = %s",
            (subtask_id, step_number),
        )
        deleted: bool = cur.rowcount > 0
        conn.commit()

    if not deleted:
        logger.warning("Step %d not found in subtask %s (race condition?)", step_number, subtask_id)
        return StepDeletionResult(deleted=False)

    # If the deleted step was passed, invalidate the parent subtask's passes status
    subtask_invalidated = False
    if was_passed:
        subtask_invalidated = _invalidate_subtask_passes(subtask_id)

    # Emit audit event
    if emit_event:
        _emit_step_deletion_event(subtask_id, step_number, step, subtask_invalidated)

    logger.info(
        "Deleted step %d from subtask %s (was_passed=%s, subtask_invalidated=%s)",
        step_number,
        subtask_id,
        was_passed,
        subtask_invalidated,
    )

    return StepDeletionResult(
        deleted=True,
        was_passed=was_passed,
        subtask_invalidated=subtask_invalidated,
        step_details=step,
    )


def _invalidate_subtask_passes(subtask_id: str) -> bool:
    """Invalidate subtask.passes when a passed step is deleted.

    Args:
        subtask_id: Full subtask table ID (e.g., "task-abc123-1.1")

    Returns:
        True if subtask was invalidated, False if it wasn't passed or not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        # Only update if currently passed
        cur.execute(
            """
            UPDATE task_subtasks
            SET passes = FALSE, passed_at = NULL
            WHERE id = %s AND passes = TRUE
            RETURNING id
            """,
            (subtask_id,),
        )
        invalidated = cur.fetchone() is not None
        conn.commit()

    if invalidated:
        logger.warning(
            "Subtask %s passes status invalidated due to step deletion",
            subtask_id,
        )

    return invalidated


def _emit_step_deletion_event(
    subtask_id: str,
    step_number: int,
    step_details: dict[str, Any],
    subtask_invalidated: bool,
) -> None:
    """Emit audit event for step deletion.

    Args:
        subtask_id: Full subtask table ID
        step_number: Deleted step number
        step_details: Step state before deletion
        subtask_invalidated: Whether parent subtask was invalidated
    """
    from .events import EventLevel, log_task_event

    # Extract task_id from subtask_id (format: "task-abc123-1.1")
    # The task_id is everything before the last dash-separated segment
    parts = subtask_id.rsplit("-", 1)
    if len(parts) != 2:
        logger.warning("Cannot emit event: invalid subtask_id format %s", subtask_id)
        return

    task_id = parts[0]

    was_passed = step_details.get("passes", False)
    level: EventLevel = "warning" if was_passed else "info"

    message = f"Step {step_number} deleted from subtask {subtask_id}"
    if was_passed:
        message += " (WAS PASSED - verification bypassed)"
    if subtask_invalidated:
        message += " - subtask passes status invalidated"

    log_task_event(
        task_id=task_id,
        message=message,
        source="system",
        level=level,
        event_type="step_deletion",
        visibility="user",
        attributes={
            "subtask_id": subtask_id,
            "step_number": step_number,
            "was_passed": was_passed,
            "subtask_invalidated": subtask_invalidated,
            "verify_command": step_details.get("verify_command"),
            "expected_output": step_details.get("expected_output"),
            "description": step_details.get("description"),
        },
    )


def insert_step(
    subtask_id: str,
    position: int,
    description: str,
    spec: dict[str, Any] | None = None,
    verify_command: str | None = None,
    expected_output: str | None = None,
) -> dict[str, Any]:
    """Insert a step at a specific position, shifting existing steps down.

    This allows inserting a step before an existing step. All steps at or after
    the insertion position are renumbered (incremented by 1).

    Args:
        subtask_id: Parent subtask ID (e.g., "task-abc123-1.1")
        position: Position to insert at (1-indexed). Existing steps at this
                  position and after are shifted down.
        description: Step description text
        spec: Optional JSONB spec for implementation details
        verify_command: Bash command to verify step completion
        expected_output: Expected output pattern for verification

    Returns:
        The created step dict.

    Raises:
        ValueError: If position < 1
        Exception: If subtask_id doesn't exist (FK constraint violation)
    """
    if position < 1:
        raise ValueError("Position must be >= 1")

    spec_json = json.dumps(spec) if spec else None

    with get_connection() as conn, conn.cursor() as cur:
        # Get steps to shift (in reverse order to avoid unique constraint violations)
        cur.execute(
            """
            SELECT step_number FROM task_subtask_steps
            WHERE subtask_id = %s AND step_number >= %s
            ORDER BY step_number DESC
            """,
            (subtask_id, position),
        )
        steps_to_shift = [row[0] for row in cur.fetchall()]

        # Shift each step individually in reverse order
        for step_num in steps_to_shift:
            cur.execute(
                """
                UPDATE task_subtask_steps
                SET step_number = %s
                WHERE subtask_id = %s AND step_number = %s
                """,
                (step_num + 1, subtask_id, step_num),
            )
        shifted = len(steps_to_shift)

        # Insert the new step at the position
        cur.execute(
            f"""
            INSERT INTO task_subtask_steps (subtask_id, step_number, description, spec, verify_command, expected_output)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING {STEP_COLUMNS}
            """,
            (subtask_id, position, description, spec_json, verify_command, expected_output),
        )
        row = cur.fetchone()
        conn.commit()

    logger.info(
        "Inserted step at position %d for subtask %s (shifted %d existing steps)",
        position,
        subtask_id,
        shifted,
    )
    return _row_to_dict(row)


def get_step_summary(subtask_id: str) -> dict[str, Any]:
    """Get summary of step completion for a subtask.

    Returns:
        Dict with keys:
            - total: Total number of steps
            - completed: Number of resolved steps (passed OR plan_defect with passing fix)
            - progress_percent: Completion percentage (0-100)
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE
                    s.passes = TRUE
                    OR (s.status = 'plan_defect' AND fix.passes = TRUE)
                ) as completed
            FROM task_subtask_steps s
            LEFT JOIN task_subtask_steps fix
                ON fix.subtask_id = s.subtask_id
                AND fix.step_number = s.fix_step_number
            WHERE s.subtask_id = %s
            """,
            (subtask_id,),
        )
        row = cur.fetchone()

    total = row[0] if row else 0
    completed = row[1] if row else 0
    progress_percent = round((completed / total * 100) if total > 0 else 0, 1)

    return {
        "total": total,
        "completed": completed,
        "progress_percent": progress_percent,
    }


class PlanDefectError(Exception):
    """Raised when a plan_defect operation is invalid."""

    pass


def update_step_status(
    subtask_id: str,
    step_number: int,
    status: str,
    fix_step_number: int | None = None,
) -> dict[str, Any] | None:
    """Update step status.

    Valid status values:
    - 'pending': Step not yet attempted
    - 'passed': Step completed successfully
    - 'failed': Step failed verification
    - 'plan_defect': Step's verification was wrong (plan issue, not implementation)

    For 'plan_defect' status, a fix_step_number is REQUIRED. The fix step must:
    1. Be a different step within the same subtask
    2. Have passes=True (correct verification that proves implementation works)

    Workflow for plan defects:
    1. Original step has wrong verify_command/expected_output
    2. Add new step with correct verification: st step add <subtask> "Fix: correct verification"
    3. Pass the fix step: st step pass <subtask> <fix_step_number>
    4. Mark original as plan_defect: st step defect <subtask> <step> --fix <fix_step_number>

    Args:
        subtask_id: Parent subtask ID
        step_number: Step number to update
        status: New status value
        fix_step_number: For plan_defect only: step number with correct verification

    Returns:
        Updated step dict or None if not found.

    Raises:
        ValueError: If status is not a valid value
        PlanDefectError: If plan_defect without valid completed fix step
    """
    if status not in VALID_STEP_STATUSES:
        raise ValueError(
            f"Invalid status '{status}'. Valid values: {', '.join(sorted(VALID_STEP_STATUSES))}"
        )

    # For plan_defect status, require and validate fix_step_number
    if status == STEP_STATUS_PLAN_DEFECT:
        if fix_step_number is None:
            raise PlanDefectError(
                "plan_defect status requires a fix_step_number. "
                "Add a new step with correct verification, pass it, "
                "then mark this step as plan_defect."
            )

        if fix_step_number == step_number:
            raise PlanDefectError(
                f"Fix step cannot be the same as the defective step ({step_number}). "
                "Add a new step with correct verification."
            )

        # Validate the fix step exists and is passed within the same subtask
        fix_step = get_step(subtask_id, fix_step_number)
        if not fix_step:
            raise PlanDefectError(
                f"Fix step {fix_step_number} not found in subtask. "
                "Add the fix step first: st step add <subtask> 'Fix: correct verification'"
            )

        if not fix_step.get("passes"):
            raise PlanDefectError(
                f"Fix step {fix_step_number} has not passed verification. "
                "Pass the fix step first: st step pass <subtask> {fix_step_number}"
            )

        logger.info(
            "Step %d marked as plan_defect with fix step %d",
            step_number,
            fix_step_number,
        )

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE task_subtask_steps
            SET status = %s, fix_step_number = %s
            WHERE subtask_id = %s AND step_number = %s
            RETURNING {STEP_COLUMNS}
            """,
            (status, fix_step_number, subtask_id, step_number),
        )
        row = cur.fetchone()
        conn.commit()

    if not row:
        logger.warning("Step %d not found for subtask %s", step_number, subtask_id)
        return None

    logger.info("Updated step %d status to '%s' for subtask %s", step_number, status, subtask_id)
    return _row_to_dict(row)
