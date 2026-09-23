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


def test_failed_subtask_keeps_attempt_evidence_without_saving_learning() -> None:
    with (
        patch("app.tasks.autonomous.exec_modules.result_processing.emit_log") as emit_log,
        patch("app.tasks.autonomous.exec_modules.result_processing.debug_error"),
        patch("app.tasks.autonomous.exec_modules.memory_writes.get_sync_client") as get_client,
    ):
        result = process_final_result(
            task_id="task-123",
            subtask_id="subtask-123",
            subtask_short_id="2.3",
            project_id="summitflow",
            all_passed=False,
            step_results=[{"passed": False, "error": "check failed"}],
            response_content="failure details",
            duration=1.0,
            self_fix_attempts=2,
            supervisor_guided_attempts=1,
            extensions_granted=0,
            issue_counts={},
        )

    assert result["status"] == "failed"
    assert result["step_results"] == [{"passed": False, "error": "check failed"}]
    assert result["self_fix_attempts"] == 2
    assert result["supervisor_guided_attempts"] == 1
    assert "after 4 attempts" in emit_log.call_args.args[2]
    get_client.assert_not_called()
