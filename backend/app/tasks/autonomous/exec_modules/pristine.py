"""Pristine codebase checking and self-healing."""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path
from typing import Any

from ....constants import PRISTINE_SELF_HEAL_MAX_ATTEMPTS
from ....logging_config import get_logger
from ....services.agent_hub_client import get_sync_client
from ....storage.agent_configs_quality import build_dt_command
from ....storage.projects import get_project_root_path
from .events import emit_log, emit_progress_log
from .git_ops import auto_commit, has_uncommitted_changes
from .prompts import get_prompt_template
from .quality_utils import find_dev_tools, parse_error_count

logger = get_logger(__name__)
AUTOCODE_ROLES = ["system", "autocode"]


class PristineCheckError(Exception):
    """Raised when codebase is not in pristine state."""


def _emit(task_id: str, level: str, msg: str, project_id: str) -> None:
    emit_log(task_id, level, msg, source="pristine", project_id=project_id)


def _run_quality_check(repo_path: Path, cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(repo_path), capture_output=True, text=True, timeout=600)


def _revert_changes(repo_path: Path) -> None:
    subprocess.run(["git", "checkout", "."], cwd=str(repo_path), capture_output=True, timeout=30)


def _build_check_command(project_id: str, repo_path: Path) -> list[str] | None:
    """Return the quality-check command, or None if nothing is available."""
    dt_cmd = find_dev_tools()
    if dt_cmd:
        return build_dt_command(dt_cmd, project_id)
    script = repo_path / "scripts" / "dev-tools.sh"
    return [str(script), "--quick"] if script.exists() else None


def _register_session(task_id: str, project_id: str, session_id: str) -> None:
    from ....storage.tasks.core import add_agent_hub_session

    add_agent_hub_session(task_id, session_id)
    _emit(task_id, "info", f"Pristine agent session started: {session_id}", project_id)


def _invoke_pristine_agent(
    task_id: str,
    project_id: str,
    repo_path: Path,
    output: str,
    attempt: int,
    session_id: str | None,
) -> tuple[str, Any]:
    """Invoke coder agent to fix quality issues; return (session_id, response)."""
    client = get_sync_client()
    fix_prompt = get_prompt_template("autocode-pristine-fix").format_map({"errors_output": output[:8000]})

    if not session_id:
        session_id = str(uuid.uuid4())
        _register_session(task_id, project_id, session_id)

    response = client.complete(
        messages=[{"role": "user", "content": fix_prompt}],
        agent_slug="coder",
        working_dir=str(repo_path),
        max_turns=10,
        execute_tools=True,
        project_id=project_id,
        use_memory=False,
        include_roles=AUTOCODE_ROLES,
        session_id=session_id,
    )

    if response.session_id and response.session_id != session_id:
        from ....storage.tasks.core import add_agent_hub_session

        add_agent_hub_session(task_id, response.session_id)
        session_id = response.session_id

    logger.info("pristine_self_heal_agent_completed", project_id=project_id, attempt=attempt + 1, response_length=len(response.content) if response.content else 0)
    _emit(task_id, "info", f"Pristine self-heal: coder agent completed attempt {attempt + 1}", project_id)
    return session_id, response


def check_pristine_codebase(project_id: str) -> None:
    """Verify codebase passes quality gates before automated execution.

    Raises:
        PristineCheckError: If quality gates fail
    """
    root_path = get_project_root_path(project_id)
    if not root_path:
        raise PristineCheckError(f"Project {project_id} not found or has no root_path")

    repo_path = Path(root_path)
    cmd = _build_check_command(project_id, repo_path)
    if not cmd:
        logger.warning("pristine_check_skipped", project_id=project_id, reason="dt command and scripts/dev-tools.sh not found")
        return

    logger.info("pristine_check_started", project_id=project_id, cmd=cmd[0])
    try:
        result = _run_quality_check(repo_path, cmd)
    except subprocess.TimeoutExpired as e:
        raise PristineCheckError("Pristine check timed out after 10 minutes. Run 'dt --check' manually to investigate.") from e
    except FileNotFoundError as e:
        logger.warning("pristine_check_skipped", project_id=project_id, reason=f"Command not found: {e}")
        return

    if result.returncode != 0:
        out = result.stdout + result.stderr
        logger.error("pristine_check_failed", project_id=project_id, exit_code=result.returncode, output=out[:2000])
        raise PristineCheckError(
            f"Codebase quality gates failed (exit code {result.returncode}). "
            "Fix lint/type/test errors before running automated execution. "
            "Run 'dt --quick' to see details."
        )
    logger.info("pristine_check_passed", project_id=project_id)


def pristine_self_heal(task_id: str, project_id: str) -> bool:
    """Auto-fix quality gate failures before task execution.

    Returns True if codebase is pristine, False if attempts exhausted.
    """
    root_path = get_project_root_path(project_id)
    if not root_path:
        logger.error("pristine_self_heal_no_path", project_id=project_id)
        _emit(task_id, "error", "Pristine self-heal failed: no project path", project_id)
        return False

    repo_path = Path(root_path)
    dt_cmd = find_dev_tools()
    if not dt_cmd:
        logger.warning("pristine_self_heal_skipped", reason="dt not found")
        return True

    cmd = build_dt_command(dt_cmd, project_id)
    previous_error_count: int | None = None
    session_id: str | None = None
    _emit(task_id, "info", "Starting pristine self-heal: checking quality gates", project_id)

    for attempt in range(PRISTINE_SELF_HEAL_MAX_ATTEMPTS):
        try:
            result = _run_quality_check(repo_path, cmd)
        except subprocess.TimeoutExpired:
            logger.error("pristine_self_heal_timeout", project_id=project_id)
            _emit(task_id, "error", "Pristine self-heal timed out", project_id)
            return False
        except Exception as e:
            logger.error("pristine_self_heal_error", project_id=project_id, error=str(e))
            _emit(task_id, "error", f"Pristine self-heal error: {e}", project_id)
            return False

        if result.returncode == 0:
            if attempt > 0:
                if has_uncommitted_changes(str(repo_path)):
                    auto_commit(str(repo_path), f"[pristine] Auto-fix quality issues before {task_id}")
                logger.info("pristine_self_heal_success", project_id=project_id, attempts=attempt + 1)
                _emit(task_id, "info", f"Pristine self-heal succeeded after {attempt + 1} attempt(s)", project_id)
            return True

        output = result.stdout + result.stderr
        error_count = parse_error_count(output)

        if previous_error_count is not None and error_count > previous_error_count:
            logger.warning("pristine_self_heal_regression", project_id=project_id, previous=previous_error_count, current=error_count)
            _emit(task_id, "warning", f"Pristine self-heal regression detected ({previous_error_count}→{error_count} errors), reverting", project_id)
            _revert_changes(repo_path)
            return False

        previous_error_count = error_count

        if attempt >= PRISTINE_SELF_HEAL_MAX_ATTEMPTS - 1:
            break

        logger.info("pristine_self_heal_attempt", project_id=project_id, attempt=attempt + 1, error_count=error_count)
        _emit(task_id, "info", f"Pristine self-heal attempt {attempt + 1}/{PRISTINE_SELF_HEAL_MAX_ATTEMPTS}: {error_count} errors, invoking coder agent", project_id)
        session_id, response = _invoke_pristine_agent(task_id, project_id, repo_path, output, attempt, session_id)
        if response.progress_log:
            emit_progress_log(task_id, f"pristine-{attempt + 1}", response.progress_log, project_id=project_id)

    logger.warning("pristine_self_heal_exhausted", project_id=project_id, max_attempts=PRISTINE_SELF_HEAL_MAX_ATTEMPTS)
    _emit(task_id, "warning", f"Pristine self-heal exhausted {PRISTINE_SELF_HEAL_MAX_ATTEMPTS} attempts", project_id)
    return False
