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


def test_build_feedback_prompt_uses_single_report_command_for_duplicate_handling() -> None:
    from app.tasks.autonomous.exec_modules.prompts import build_feedback_prompt

    prompt = build_feedback_prompt([], "sess-feedback-1")

    assert 'st feedback search "keyword"' not in prompt
    assert "--vote-if-match" in prompt
    assert "duplicate feedback receives a vote" in prompt


def test_build_feedback_prompt_uses_boundary_metadata_without_step_results() -> None:
    from app.tasks.autonomous.exec_modules.prompts import build_feedback_prompt

    result = {
        "subtask_id": "1.3",
        "status": "failed",
        "self_fix_attempts": 0,
        "supervisor_guided_attempts": 0,
        "error_boundary": "after_agent_complete",
        "last_executed_step": "quality gate",
        "last_tool_name": "bash",
        "last_command": "st check --quick --changed-only",
        "agent_session_id": "sess-123",
    }

    prompt = build_feedback_prompt([result], "sess-feedback-1")

    assert "no details available" not in prompt
    assert "boundary=after_agent_complete" in prompt
    assert "last_step=quality gate" in prompt
    assert "tool=bash" in prompt
    assert "st check --quick --changed-only" in prompt


def test_partial_completion_verification_uses_boundary_metadata_without_step_results() -> None:
    from app.tasks.autonomous.exec_modules.completion_status import (
        build_partial_completion_verification,
    )

    failed = [
        {
            "subtask_id": "1.3",
            "status": "failed",
            "error_boundary": "runtime_eval",
            "last_tool_name": "runtime_evaluator",
            "last_command": "st browser eval",
        }
    ]

    verification = build_partial_completion_verification(failed, passed=[], failed=failed)

    reason = verification["failed_details"][0]["failure_reason"]
    assert "runtime_eval" in reason
    assert "runtime_evaluator" in reason
    assert "st browser eval" in reason
