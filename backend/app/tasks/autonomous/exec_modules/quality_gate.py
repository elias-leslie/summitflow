"""Quality gate execution and auto-fix logic."""

from __future__ import annotations

from ....logging_config import get_logger
from .events import emit_log
from .git_ops import auto_commit, has_uncommitted_changes
from .quality import auto_fix_quality, run_final_quality_gate

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
        auto_fix_quality(project_path)

        if has_uncommitted_changes(project_path):
            auto_commit(project_path, f"[auto-fix] Quality gate fixes for {task_id}")

        final_gate_passed = run_final_quality_gate(task_id, project_path, project_id)

    return final_gate_passed
