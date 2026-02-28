"""Quality gate execution and auto-fix logic."""

from __future__ import annotations

import subprocess

from ....logging_config import get_logger
from .events import emit_log
from .git_ops import auto_commit, has_uncommitted_changes
from .quality import auto_fix_quality, run_final_quality_gate
from .quality_utils import find_dev_tools

logger = get_logger(__name__)


def run_quality_gate_with_autofix(
    task_id: str,
    project_path: str,
    project_id: str,
) -> bool:
    """Run quality gate with auto-fix retry if it fails.

    Args:
        task_id: The task ID
        project_path: Path to project directory
        project_id: The project ID

    Returns:
        True if quality gate passed (either initially or after auto-fix), False otherwise
    """
    final_gate_passed = run_final_quality_gate(task_id, project_path, project_id)

    if not final_gate_passed:
        emit_log(
            task_id,
            "warn",
            "Final quality gate failed, attempting auto-fix",
            source="quality",
            project_id=project_id,
        )
        auto_fix_quality(project_path, project_id)

        if has_uncommitted_changes(project_path):
            auto_commit(project_path, f"[auto-fix] Quality gate fixes for {task_id}")

        final_gate_passed = run_final_quality_gate(task_id, project_path, project_id)

    if final_gate_passed:
        _run_coderabbit_advisory(task_id, project_path, project_id)

    return final_gate_passed


def _run_coderabbit_advisory(
    task_id: str,
    project_path: str,
    project_id: str,
) -> None:
    """Run CodeRabbit review as advisory (non-blocking) after quality gate passes.

    Logs findings as events for the review agent to consume.
    Skips gracefully on rate limit errors or if coderabbit is not installed.
    """
    dt_cmd = find_dev_tools()
    if not dt_cmd:
        return

    cmd = [dt_cmd, "coderabbit"]

    try:
        result = subprocess.run(
            cmd,
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = (result.stdout + result.stderr).strip()

        if "rate limit" in output.lower() or "429" in output:
            emit_log(
                task_id,
                "info",
                "CodeRabbit advisory skipped: rate limited",
                source="coderabbit",
                project_id=project_id,
            )
            return

        if result.returncode != 0 and "not found" in output.lower():
            emit_log(
                task_id,
                "info",
                "CodeRabbit advisory skipped: coderabbit not installed",
                source="coderabbit",
                project_id=project_id,
            )
            return

        findings = output[:2000] if output else "No findings"
        emit_log(
            task_id,
            "info",
            f"CodeRabbit advisory review:\n{findings}",
            source="coderabbit",
            project_id=project_id,
        )
    except subprocess.TimeoutExpired:
        emit_log(
            task_id,
            "info",
            "CodeRabbit advisory skipped: timed out",
            source="coderabbit",
            project_id=project_id,
        )
    except Exception as e:
        logger.debug("CodeRabbit advisory failed: %s", e)
