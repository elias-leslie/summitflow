"""Tests for pipeline statistics helper functions."""

from __future__ import annotations

from app.api.pipeline_stats import (
    _compute_partial_merge,
    _compute_self_healing,
    _compute_verification,
)


def test_compute_self_healing_ignores_invalid_numeric_fields() -> None:
    result = _compute_self_healing(
        [
            {
                "execution_clean": True,
                "total_self_fix_attempts": object(),
                "self_fix_attempts": "2",
                "total_supervisor_attempts": object(),
                "supervisor_guided_attempts": "1",
                "tier_upgraded": True,
            },
            {
                "execution_clean": False,
                "self_fix_attempts": 1,
            },
        ]
    )

    assert result.first_attempt_pass_rate == 0.5
    assert result.avg_self_fix_attempts == 1.5
    assert result.supervisor_escalation_rate == 0.5
    assert result.model_escalation_count == 1


def test_compute_verification_skips_invalid_step_shapes_and_coerces_counts() -> None:
    result = _compute_verification(
        [
            {
                "step_results": [
                    {"passed": True, "retry_count": "2", "attempts": 3},
                    {"passed": False, "retry_count": object(), "attempts": "4"},
                    "ignore-me",
                    {"passed": True},
                ]
            }
        ]
    )

    assert result.step_pass_rate == 0.67
    assert result.avg_retries_per_step == 1.67


def test_compute_partial_merge_ignores_invalid_count_fields() -> None:
    result = _compute_partial_merge(
        [
            {"execution_clean": True, "partial_merge": False, "passed_count": "1", "subtask_count": "1"},
            {"partial_merge": True, "passed_count": 1, "subtask_count": 2},
            {"partial_merge": False, "passed_count": object(), "subtask_count": "2"},
        ]
    )

    assert result.full_completion_rate == 0.33
    assert result.partial_completion_rate == 0.33
    assert result.total_failure_rate == 0.33
