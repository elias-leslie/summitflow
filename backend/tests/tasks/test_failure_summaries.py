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


def test_build_partial_completion_verification_surfaces_commit_failure_detail() -> None:
    from app.tasks.autonomous.exec_modules.completion_status import (
        build_partial_completion_verification,
    )

    failed = [
        _failed_subtask_result(
            "commit_failed",
            "commit helper failed: st commit --message 'autocode(task-1): complete subtask 1.2' --task task-1 --push; stderr: changed_only_types failed for backend/app/foo.py",
        )
    ]

    verification = build_partial_completion_verification(failed, passed=[], failed=failed)

    reason = verification["failed_details"][0]["failure_reason"]
    assert "commit_failed" in reason
    assert "st commit" in reason
    assert "changed_only_types failed for backend/app/foo.py" in reason


def test_build_feedback_prompt_surfaces_timeout_output_detail() -> None:
    from app.tasks.autonomous.exec_modules.prompts import build_feedback_prompt

    result = _failed_subtask_result(
        "timed_out",
        "Last command `st check --check` timed out after 600s while backend/tests/api/test_tasks.py was still running.",
    )

    prompt = build_feedback_prompt([result], "sess-feedback-1")

    assert "Failure:" in prompt
    assert "st check --check" in prompt
    assert "600s" in prompt
    assert "Affected steps: 0" in prompt
