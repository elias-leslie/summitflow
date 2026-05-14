"""Tests for failure summary formatting in autonomous execution flows."""

from __future__ import annotations


def _failed_subtask_result(reason: str, output: str) -> dict[str, object]:
    return {
        "subtask_id": "1.2",
        "status": "failed",
        "self_fix_attempts": 0,
        "supervisor_guided_attempts": 0,
        "step_results": [
            {
                "step_number": 0,
                "passed": False,
                "reason": reason,
                "output": output,
                "returncode": 1,
            }
        ],
    }


def test_summarize_subtask_failure_surfaces_commit_failure_detail() -> None:
    from app.tasks.autonomous.exec_modules.failure_summaries import summarize_subtask_failure

    failed = [
        _failed_subtask_result(
            "commit_failed",
            "commit helper failed: st commit --message 'autocode(task-1): complete subtask 1.2' --task task-1 --push; stderr: changed_only_types failed for backend/app/foo.py",
        )
    ]

    reason = summarize_subtask_failure(failed[0])

    assert "commit_failed" in reason
    assert "st commit" in reason
    assert "changed_only_types failed for backend/app/foo.py" in reason


def test_summarize_subtask_failure_uses_boundary_metadata_without_step_results() -> None:
    from app.tasks.autonomous.exec_modules.failure_summaries import summarize_subtask_failure

    failed = {
        "subtask_id": "1.3",
        "status": "failed",
        "error_boundary": "runtime_eval",
        "last_tool_name": "runtime_evaluator",
        "last_command": "st browser eval",
    }

    reason = summarize_subtask_failure(failed)
    assert "runtime_eval" in reason
    assert "runtime_evaluator" in reason
    assert "st browser eval" in reason
