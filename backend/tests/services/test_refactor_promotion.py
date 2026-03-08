"""Tests for shared refactor promotion policy."""

from __future__ import annotations

from app.services.refactor_promotion import assess_refactor_target


def test_promotes_structural_target_with_execution_pressure() -> None:
    assessment = assess_refactor_target(
        {
            "path": "backend/app/services/task_lane_preflight.py",
            "lines_of_code": 565,
            "complexity_score": 8.0,
            "hotspot_score": 180.0,
            "commit_count_90d": 7,
            "test_file_exists": False,
            "refactor_issues": ["large_file", "deep_nesting", "has_long_functions", "magic_strings"],
        }
    )

    assert assessment.should_create_task is True
    assert assessment.confidence in {"high", "medium"}
    assert assessment.recommended_action == "create_task"
    assert assessment.structural_signals >= 2
    assert assessment.impact_signals >= 1


def test_suppresses_small_scope_hygiene_target() -> None:
    assessment = assess_refactor_target(
        {
            "path": "backend/cli/commands/complete.py",
            "lines_of_code": 99,
            "complexity_score": 6.3,
            "hotspot_score": 25.0,
            "commit_count_90d": 1,
            "test_file_exists": True,
            "refactor_issues": ["has_long_functions"],
        }
    )

    assert assessment.should_create_task is False
    assert assessment.recommended_action == "keep_in_explorer"
    assert "Small-scope hygiene issue" in assessment.suppression_reasons[0]


def test_suppresses_size_only_target_without_real_pressure() -> None:
    assessment = assess_refactor_target(
        {
            "path": "backend/app/constants/catalog_entries.py",
            "lines_of_code": 536,
            "complexity_score": 0.0,
            "hotspot_score": 0.0,
            "commit_count_90d": 0,
            "test_file_exists": True,
            "refactor_issues": ["large_file"],
        }
    )

    assert assessment.should_create_task is False
    assert assessment.recommended_action == "keep_in_explorer"
    assert "Size-only finding" in assessment.suppression_reasons[0]
