"""Quality gate execution."""

from __future__ import annotations

from .ah_events import emit_quality_gate_result
from .quality import run_final_quality_gate


def run_quality_gate(
    task_id: str,
    project_path: str,
    project_id: str,
) -> bool:
    """Run the final task-scoped quality gate.

    Args:
        task_id: The task ID
        project_path: Path to project directory
        project_id: The project ID

    Returns:
        True if quality gate passed, False otherwise
    """
    final_gate_passed = run_final_quality_gate(task_id, project_path, project_id)
    detail = "passed" if final_gate_passed else "failed"
    emit_quality_gate_result(task_id, final_gate_passed, detail)
    return final_gate_passed
