from __future__ import annotations

from unittest.mock import patch

from app.tasks.autonomous.exec_modules.result_processing import process_final_result


def test_process_final_result_skips_subtask_storage_for_synthetic_task_unit() -> None:
    with (
        patch("app.tasks.autonomous.exec_modules.result_processing.get_subtask", return_value=None),
        patch("app.tasks.autonomous.exec_modules.result_processing.update_subtask_passes") as update_passes,
        patch("app.tasks.autonomous.exec_modules.result_processing.extract_handoff_summary") as extract_summary,
        patch("app.tasks.autonomous.exec_modules.result_processing.emit_log"),
        patch("app.tasks.autonomous.exec_modules.result_processing.debug_success"),
        patch("app.tasks.autonomous.exec_modules.result_processing.save_subtask_learning"),
    ):
        result = process_final_result(
            task_id="task-123",
            subtask_id="task-123",
            subtask_short_id="task",
            project_id="summitflow",
            all_passed=True,
            step_results=[],
            response_content="done",
            duration=1.0,
            self_fix_attempts=0,
            supervisor_guided_attempts=0,
            extensions_granted=0,
            issue_counts={},
        )

    assert result["status"] == "passed"
    update_passes.assert_not_called()
    extract_summary.assert_not_called()
