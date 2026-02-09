"""Quality gate checking and pristine codebase validation."""

from __future__ import annotations

import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

from ....constants import PRISTINE_SELF_HEAL_MAX_ATTEMPTS
from ....logging_config import get_logger
from ....services.agent_hub_client import get_sync_client
from ....storage.projects import get_project_root_path
from .events import emit_log, emit_progress_log
from .git_ops import auto_commit, has_uncommitted_changes
from .prompts import get_prompt_template

logger = get_logger(__name__)

AUTOCODE_ROLES = ["system", "autocode"]


class PristineCheckError(Exception):
    """Raised when codebase is not in pristine state."""

    pass


def find_dev_tools() -> str | None:
    """Find dt command or dev-tools.sh script.

    Returns path to dt (if in PATH) or None if not found.
    """
    dt_path = shutil.which("dt")
    if dt_path:
        return dt_path
    return None


def parse_error_count(output: str) -> int:
    """Parse error count from dt --check output.

    Looks for patterns like:
    - "Found N errors" / "N errors"
    - "N failed" / "N failures"
    - Fall back to counting "error:" lines
    """
    output_lower = output.lower()

    patterns = [
        r"found\s+(\d+)\s+error",
        r"(\d+)\s+error",
        r"(\d+)\s+fail",
        r"(\d+)\s+problem",
    ]

    for pattern in patterns:
        match = re.search(pattern, output_lower)
        if match:
            return int(match.group(1))

    error_lines = sum(1 for line in output.split("\n") if "error" in line.lower())
    return max(error_lines, 1 if "error" in output_lower else 0)


def check_pristine_codebase(project_id: str) -> None:
    """Verify codebase passes quality gates before automated execution.

    Runs lint, types, and tests to ensure no pre-existing failures that would
    cause false breaking change detection.

    Args:
        project_id: Project to check

    Raises:
        PristineCheckError: If quality gates fail
    """
    root_path = get_project_root_path(project_id)
    if not root_path:
        raise PristineCheckError(f"Project {project_id} not found or has no root_path")

    repo_path = Path(root_path)

    dt_cmd = find_dev_tools()
    if dt_cmd:
        cmd = [dt_cmd, "--check"]
    else:
        dev_tools_script = repo_path / "scripts" / "dev-tools.sh"
        if not dev_tools_script.exists():
            logger.warning(
                "pristine_check_skipped",
                project_id=project_id,
                reason="dt command and scripts/dev-tools.sh not found",
            )
            return
        cmd = [str(dev_tools_script), "--check"]

    logger.info("pristine_check_started", project_id=project_id, cmd=cmd[0])

    try:
        result = subprocess.run(
            cmd,
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=600,  # 10 minutes max
        )

        if result.returncode != 0:
            output = result.stdout + result.stderr
            logger.error(
                "pristine_check_failed",
                project_id=project_id,
                exit_code=result.returncode,
                output=output[:2000],
            )
            raise PristineCheckError(
                f"Codebase quality gates failed (exit code {result.returncode}). "
                f"Fix lint/type/test errors before running automated execution. "
                f"Run 'dt --check' to see details."
            )

        logger.info("pristine_check_passed", project_id=project_id)

    except subprocess.TimeoutExpired as e:
        raise PristineCheckError(
            "Pristine check timed out after 10 minutes. Run 'dt --check' manually to investigate."
        ) from e
    except FileNotFoundError as e:
        logger.warning(
            "pristine_check_skipped",
            project_id=project_id,
            reason=f"Command not found: {e}",
        )
        return


def pristine_self_heal(task_id: str, project_id: str) -> bool:
    """Auto-fix quality gate failures before task execution.

    Simple loop that:
    1. Runs dt --check
    2. If fails, passes error output to agent
    3. Reverts with git checkout . if error count increases
    4. Auto-commits successful fixes with [pristine] prefix

    Args:
        task_id: Task ID for logging
        project_id: Project to fix

    Returns:
        True if codebase is pristine (passed or fixed)
        False if exhausted attempts (escalate/block)
    """
    root_path = get_project_root_path(project_id)
    if not root_path:
        logger.error("pristine_self_heal_no_path", project_id=project_id)
        emit_log(
            task_id,
            "error",
            "Pristine self-heal failed: no project path",
            source="pristine",
            project_id=project_id,
        )
        return False

    repo_path = Path(root_path)
    dt_cmd = find_dev_tools()
    if not dt_cmd:
        logger.warning("pristine_self_heal_skipped", reason="dt not found")
        return True

    cmd = [dt_cmd, "--check"]
    previous_error_count: int | None = None
    pristine_session_id: str | None = None

    emit_log(
        task_id,
        "info",
        "Starting pristine self-heal: checking quality gates",
        source="pristine",
        project_id=project_id,
    )

    for attempt in range(PRISTINE_SELF_HEAL_MAX_ATTEMPTS):
        try:
            result = subprocess.run(
                cmd,
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                timeout=600,
            )

            if result.returncode == 0:
                if attempt > 0:
                    if has_uncommitted_changes(str(repo_path)):
                        auto_commit(
                            str(repo_path),
                            f"[pristine] Auto-fix quality issues before {task_id}",
                        )
                    logger.info(
                        "pristine_self_heal_success",
                        project_id=project_id,
                        attempts=attempt + 1,
                    )
                    emit_log(
                        task_id,
                        "info",
                        f"Pristine self-heal succeeded after {attempt + 1} attempt(s)",
                        source="pristine",
                        project_id=project_id,
                    )
                return True

            output = result.stdout + result.stderr
            error_count = parse_error_count(output)

            if previous_error_count is not None and error_count > previous_error_count:
                logger.warning(
                    "pristine_self_heal_regression",
                    project_id=project_id,
                    previous=previous_error_count,
                    current=error_count,
                )
                emit_log(
                    task_id,
                    "warning",
                    f"Pristine self-heal regression detected ({previous_error_count}→{error_count} errors), reverting",
                    source="pristine",
                    project_id=project_id,
                )
                subprocess.run(
                    ["git", "checkout", "."],
                    cwd=str(repo_path),
                    capture_output=True,
                    timeout=30,
                )
                return False

            previous_error_count = error_count

            if attempt >= PRISTINE_SELF_HEAL_MAX_ATTEMPTS - 1:
                break

            logger.info(
                "pristine_self_heal_attempt",
                project_id=project_id,
                attempt=attempt + 1,
                error_count=error_count,
            )
            emit_log(
                task_id,
                "info",
                f"Pristine self-heal attempt {attempt + 1}/{PRISTINE_SELF_HEAL_MAX_ATTEMPTS}: {error_count} errors, invoking coder agent",
                source="pristine",
                project_id=project_id,
            )

            client = get_sync_client()
            pristine_template = get_prompt_template("autocode-pristine-fix")
            fix_prompt = pristine_template.format_map({"errors_output": output[:8000]})

            # Pre-create session ID on first attempt for realtime observability
            if not pristine_session_id:
                from ....storage.tasks.core import add_agent_hub_session

                pristine_session_id = str(uuid.uuid4())
                add_agent_hub_session(task_id, pristine_session_id)
                emit_log(
                    task_id,
                    "info",
                    f"Pristine agent session started: {pristine_session_id}",
                    source="pristine",
                    project_id=project_id,
                )

            pristine_kwargs: dict[str, Any] = {
                "messages": [{"role": "user", "content": fix_prompt}],
                "agent_slug": "coder",
                "working_dir": str(repo_path),
                "max_turns": 10,
                "execute_tools": True,
                "project_id": project_id,
                "use_memory": False,
                "include_roles": AUTOCODE_ROLES,
                "session_id": pristine_session_id,
            }

            response = client.complete(**pristine_kwargs)

            if response.session_id and response.session_id != pristine_session_id:
                from ....storage.tasks.core import add_agent_hub_session

                add_agent_hub_session(task_id, response.session_id)
                pristine_session_id = response.session_id

            logger.info(
                "pristine_self_heal_agent_completed",
                project_id=project_id,
                attempt=attempt + 1,
                response_length=len(response.content) if response.content else 0,
            )
            emit_log(
                task_id,
                "info",
                f"Pristine self-heal: coder agent completed attempt {attempt + 1}",
                source="pristine",
                project_id=project_id,
            )

            # Surface agent tool calls to execution timeline for observability
            if response.progress_log:
                emit_progress_log(
                    task_id, f"pristine-{attempt + 1}", response.progress_log, project_id=project_id
                )

        except subprocess.TimeoutExpired:
            logger.error("pristine_self_heal_timeout", project_id=project_id)
            emit_log(
                task_id,
                "error",
                "Pristine self-heal timed out",
                source="pristine",
                project_id=project_id,
            )
            return False
        except Exception as e:
            logger.error("pristine_self_heal_error", project_id=project_id, error=str(e))
            emit_log(
                task_id,
                "error",
                f"Pristine self-heal error: {e}",
                source="pristine",
                project_id=project_id,
            )
            return False

    logger.warning(
        "pristine_self_heal_exhausted",
        project_id=project_id,
        max_attempts=PRISTINE_SELF_HEAL_MAX_ATTEMPTS,
    )
    emit_log(
        task_id,
        "warning",
        f"Pristine self-heal exhausted {PRISTINE_SELF_HEAL_MAX_ATTEMPTS} attempts",
        source="pristine",
        project_id=project_id,
    )
    return False


def run_final_quality_gate(
    task_id: str, project_path: str, project_id: str
) -> bool:
    """Run dt --check as final quality gate before AI review.

    Args:
        task_id: Task ID for logging
        project_path: Path to the project/worktree
        project_id: Project ID for logging

    Returns:
        True if quality gate passes, False otherwise
    """
    dt_cmd = find_dev_tools()
    if not dt_cmd:
        return True

    emit_log(
        task_id,
        "info",
        "Running final quality gate (dt --check)...",
        source="quality",
        project_id=project_id,
    )

    try:
        result = subprocess.run(
            [dt_cmd, "--check"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=600,
        )
        passed = result.returncode == 0
        if passed:
            emit_log(
                task_id,
                "info",
                "Final quality gate passed",
                source="quality",
                project_id=project_id,
            )
        else:
            output = (result.stdout + result.stderr)[:500]
            emit_log(
                task_id,
                "warn",
                f"Final quality gate failed: {output}",
                source="quality",
                project_id=project_id,
            )
        return passed
    except subprocess.TimeoutExpired:
        emit_log(
            task_id,
            "warn",
            "Final quality gate timed out",
            source="quality",
            project_id=project_id,
        )
        return False
    except Exception as e:
        emit_log(
            task_id,
            "warn",
            f"Final quality gate error: {e}",
            source="quality",
            project_id=project_id,
        )
        return False


def auto_fix_quality(project_path: str) -> bool:
    """Run dt --fix to attempt auto-fixing quality issues.

    Returns:
        True if dt --fix ran successfully
    """
    dt_cmd = find_dev_tools()
    if not dt_cmd:
        return False

    try:
        result = subprocess.run(
            [dt_cmd, "--fix"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=300,
        )
        return result.returncode == 0
    except Exception:
        return False
