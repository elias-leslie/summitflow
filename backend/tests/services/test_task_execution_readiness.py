"""Unit tests for task execution readiness helpers."""

from __future__ import annotations

from unittest.mock import patch

from app.services.task_execution_readiness import assess_task_execution_readiness
from app.services.task_second_opinion import (
    build_second_opinion_entry,
    ensure_second_opinion_tracking,
    parse_second_opinion_response,
    persist_second_opinion,
    reset_second_opinion_for_replan,
)


class TestAssessTaskExecutionReadiness:
    """Execution-readiness classification."""

    def test_nontrivial_task_requires_full_agent_plan(self) -> None:
        readiness = assess_task_execution_readiness(
            {"task_type": "refactor", "complexity": "STANDARD", "description": "Refactor module"},
            {"done_when": ["Tests pass"]},
            [],
        )

        assert not readiness.ready
        assert "subtasks" in readiness.missing_fields
        assert "context" not in readiness.missing_fields

    def test_nontrivial_task_without_scope_context_is_still_execution_ready(self) -> None:
        readiness = assess_task_execution_readiness(
            {"task_type": "feature", "complexity": "STANDARD", "description": "Add endpoint"},
            {
                "objective": "Add health endpoint",
                "done_when": ["Endpoint returns 200"],
                "spirit_anti": "Do not break existing routes",
            },
            [
                {
                    "subtask_id": "1.1",
                    "description": "Implement API",
                    "steps_from_table": [{"step_number": 1, "description": "Add route"}],
                }
            ],
        )

        assert readiness.ready
        assert "context" not in readiness.missing_fields

    def test_ready_task_is_execution_ready(self) -> None:
        readiness = assess_task_execution_readiness(
            {"task_type": "feature", "complexity": "STANDARD", "description": "Add endpoint"},
            {
                "objective": "Add health endpoint",
                "done_when": ["Endpoint returns 200", "Tests pass"],
                "spirit_anti": "Do not break existing routes",
                "context": {"files_to_modify": ["backend/app/main.py"]},
            },
            [
                {
                    "subtask_id": "1.1",
                    "description": "Implement API",
                    "steps_from_table": [{"step_number": 1, "description": "Add route"}],
                }
            ],
        )

        assert readiness.ready

    def test_frontend_task_requires_execution_contract_when_runtime_eval_route_is_selected(self) -> None:
        readiness = assess_task_execution_readiness(
            {"task_type": "feature", "complexity": "STANDARD", "description": "Refresh dashboard layout"},
            {
                "done_when": ["Dashboard loads", "Tests pass"],
                "context": {"files_to_modify": ["frontend/app/dashboard/page.tsx"]},
            },
            [
                {
                    "subtask_id": "1.1",
                    "subtask_type": "frontend",
                    "description": "Refresh dashboard layout",
                    "steps_from_table": [{"step_number": 1, "description": "Update layout"}],
                }
            ],
        )

        assert not readiness.ready
        assert "execution_contract" in readiness.missing_fields
        assert any("execution contract" in issue.lower() for issue in readiness.issues)

    def test_frontend_task_with_execution_contract_is_execution_ready(self) -> None:
        readiness = assess_task_execution_readiness(
            {"task_type": "feature", "complexity": "STANDARD", "description": "Refresh dashboard layout"},
            {
                "done_when": ["Dashboard loads", "Tests pass"],
                "context": {
                    "files_to_modify": ["frontend/app/dashboard/page.tsx"],
                    "execution_contract": {
                        "mode": "runtime_eval",
                        "target_urls": ["/app"],
                        "user_flows": [
                            {
                                "title": "Open dashboard",
                                "actions": ["Visit /app"],
                                "expected_outcomes": ["Dashboard widgets render"],
                            }
                        ],
                        "evidence_requirements": ["screenshot"],
                    },
                },
            },
            [
                {
                    "subtask_id": "1.1",
                    "subtask_type": "frontend",
                    "description": "Refresh dashboard layout",
                    "steps_from_table": [{"step_number": 1, "description": "Update layout"}],
                }
            ],
        )

        assert readiness.ready


class TestSecondOpinionParsing:
    """Parsing helpers for live critique responses."""

    def test_parse_second_opinion_response_normalizes_object_findings(self) -> None:
        result = parse_second_opinion_response(
            """
            {
              "verdict": "needs_clarification",
              "summary": "Package is underspecified.",
              "missing_requirements": ["Need an exact schema"],
              "edge_cases": [],
              "test_gaps": [],
              "rollout_gaps": [],
              "findings": [
                {
                  "severity": "high",
                  "issue": "Output schema is vague.",
                  "why_it_matters": "Validation becomes inconsistent."
                }
              ],
              "simpler_alternative": "",
              "confidence": "high"
            }
            """,
            stage="task_shape",
            agent_slug="specifier",
        )

        assert result["status"] == "needs_revision"
        assert result["findings"] == [
            "Output schema is vague. — Validation becomes inconsistent."
        ]

    def test_build_second_opinion_entry_marks_required_task_pending(self) -> None:
        entry = build_second_opinion_entry(
            {
                "task_type": "feature",
                "complexity": "COMPLEX",
                "priority": 1,
                "labels": ["auth"],
            },
            {"objective": "Ship auth migration safely"},
            source="plan-import",
        )

        assert entry is not None
        assert entry["required"]
        assert entry["stage"] == "task_shape"
        assert entry["status"] == "pending"
        assert "complexity=COMPLEX" in entry["reasons"]
        assert entry["requested_by"] == "plan-import"

    def test_build_second_opinion_entry_preserves_completed_review(self) -> None:
        entry = build_second_opinion_entry(
            {
                "task_type": "feature",
                "complexity": "COMPLEX",
                "priority": 1,
                "labels": ["auth"],
            },
            {
                "context": {
                    "second_opinion": {
                        "required": True,
                        "stage": "task_shape",
                        "status": "completed",
                        "summary": "Already reviewed.",
                        "reviewed_by_agent": "specifier",
                    }
                }
            },
            source="task-update",
        )

        assert entry is not None
        assert entry["status"] == "completed"
        assert entry["summary"] == "Already reviewed."
        assert entry["reviewed_by_agent"] == "specifier"

    def test_complex_task_without_second_opinion_is_still_execution_ready(self) -> None:
        readiness = assess_task_execution_readiness(
            {
                "task_type": "feature",
                "complexity": "COMPLEX",
                "description": "Migrate critical auth flow",
                "priority": 1,
                "labels": ["auth", "backend"],
            },
            {
                "objective": "Ship auth migration safely",
                "done_when": ["Migration works", "Tests pass"],
                "spirit_anti": "Do not break login",
                "decisions": [{"id": "d1", "title": "Keep API stable", "outcome": "compat shim"}],
                "context": {"files_to_modify": ["backend/app/auth.py"]},
            },
            [
                {
                    "subtask_id": "1.1",
                    "description": "Implement migration",
                    "steps_from_table": [{"step_number": 1, "description": "Update flow"}],
                }
            ],
        )

        assert readiness.ready
        assert "second_opinion" not in readiness.missing_fields
        assert sum("second opinion" in issue.lower() for issue in readiness.issues) == 0

    def test_pre_close_review_alone_does_not_block_task_shape_readiness(self) -> None:
        readiness = assess_task_execution_readiness(
            {
                "task_type": "feature",
                "complexity": "COMPLEX",
                "description": "Close auth migration",
                "priority": 1,
                "labels": ["auth", "backend"],
            },
            {
                "objective": "Ship auth migration safely",
                "done_when": ["Migration works", "Tests pass"],
                "spirit_anti": "Do not break login",
                "context": {
                    "files_to_modify": ["backend/app/auth.py"],
                    "second_opinion": {
                        "required": True,
                        "stage": "pre_close",
                        "status": "completed",
                        "summary": "Ready to close.",
                    },
                },
            },
            [
                {
                    "subtask_id": "1.1",
                    "description": "Implement migration",
                    "steps_from_table": [{"step_number": 1, "description": "Update flow"}],
                }
            ],
        )

        assert readiness.ready
        assert "second_opinion" not in readiness.missing_fields

    def test_task_shape_review_in_history_still_satisfies_readiness(self) -> None:
        readiness = assess_task_execution_readiness(
            {
                "task_type": "feature",
                "complexity": "COMPLEX",
                "description": "Close auth migration",
                "priority": 1,
                "labels": ["auth", "backend"],
            },
            {
                "objective": "Ship auth migration safely",
                "done_when": ["Migration works", "Tests pass"],
                "spirit_anti": "Do not break login",
                "context": {
                    "files_to_modify": ["backend/app/auth.py"],
                    "second_opinion": {
                        "required": True,
                        "stage": "pre_close",
                        "status": "needs_revision",
                        "summary": "Need one more verify pass.",
                        "reviews": {
                            "task_shape": {
                                "required": True,
                                "stage": "task_shape",
                                "status": "completed",
                                "summary": "Shape reviewed.",
                            },
                            "pre_close": {
                                "required": True,
                                "stage": "pre_close",
                                "status": "needs_revision",
                                "summary": "Need one more verify pass.",
                            },
                        },
                    },
                },
            },
            [
                {
                    "subtask_id": "1.1",
                    "description": "Implement migration",
                    "steps_from_table": [{"step_number": 1, "description": "Update flow"}],
                }
            ],
        )

        assert readiness.ready

    def test_persist_second_opinion_preserves_task_shape_review_when_recording_pre_close(self) -> None:
        existing_spirit = {
            "context": {
                "second_opinion": {
                    "required": True,
                    "stage": "task_shape",
                    "status": "completed",
                    "summary": "Shape reviewed.",
                    "reasons": ["complexity=COMPLEX", "priority=P1"],
                    "requested_by": "plan-import",
                }
            }
        }
        critique = {
            "required": True,
            "stage": "pre_close",
            "status": "needs_revision",
            "summary": "Need final verification.",
            "verdict": "NEEDS_REVISION",
        }

        with (
            patch("app.services.task_second_opinion.get_task_spirit", return_value=existing_spirit),
            patch("app.services.task_second_opinion.update_task_spirit", return_value={}) as mock_update,
        ):
            persist_second_opinion("task-mock-1", critique)

        update_call = mock_update.call_args
        stored = update_call.kwargs["context"]["second_opinion"]
        assert stored["stage"] == "task_shape"
        assert stored["summary"] == "Shape reviewed."
        assert stored["reasons"] == ["complexity=COMPLEX", "priority=P1"]
        assert stored["reviews"]["task_shape"]["summary"] == "Shape reviewed."
        assert stored["reviews"]["pre_close"]["summary"] == "Need final verification."

    def test_reset_second_opinion_for_replan_marks_task_shape_pending_again(self) -> None:
        existing_spirit = {
            "context": {
                "second_opinion": {
                    "required": True,
                    "stage": "task_shape",
                    "status": "needs_revision",
                    "summary": "Package still has gaps.",
                    "verdict": "NEEDS_REVISION",
                    "reasons": ["complexity=COMPLEX", "priority=P1"],
                    "reviews": {
                        "task_shape": {
                            "required": True,
                            "stage": "task_shape",
                            "status": "needs_revision",
                            "summary": "Package still has gaps.",
                        }
                    },
                }
            }
        }

        with (
            patch("app.services.task_second_opinion.get_task_spirit", return_value=existing_spirit),
            patch("app.services.task_second_opinion.update_task_spirit", return_value={}) as mock_update,
        ):
            reset_second_opinion_for_replan("task-mock-1", source="planning")

        stored = mock_update.call_args.kwargs["context"]["second_opinion"]
        assert stored["status"] == "pending"
        assert stored["stage"] == "task_shape"
        assert stored["requested_by"] == "planning"
        assert "summary" not in stored
        assert stored["reviews"]["task_shape"]["status"] == "pending"

    def test_pending_second_opinion_is_advisory_only(self) -> None:
        readiness = assess_task_execution_readiness(
            {
                "task_type": "feature",
                "complexity": "COMPLEX",
                "description": "Migrate critical auth flow",
                "priority": 1,
                "labels": ["auth", "backend"],
            },
            {
                "objective": "Ship auth migration safely",
                "done_when": ["Migration works", "Tests pass"],
                "spirit_anti": "Do not break login",
                "decisions": [{"id": "d1", "title": "Keep API stable", "outcome": "compat shim"}],
                "context": {
                    "files_to_modify": ["backend/app/auth.py"],
                    "second_opinion": {
                        "required": True,
                        "stage": "task_shape",
                        "status": "pending",
                    },
                },
            },
            [
                {
                    "subtask_id": "1.1",
                    "description": "Implement migration",
                    "steps_from_table": [{"step_number": 1, "description": "Update flow"}],
                }
            ],
        )

        assert readiness.ready
        assert "second_opinion" not in readiness.missing_fields
        assert sum("second opinion" in issue.lower() for issue in readiness.issues) == 0

    def test_completed_second_opinion_satisfies_complex_task_gate(self) -> None:
        readiness = assess_task_execution_readiness(
            {
                "task_type": "feature",
                "complexity": "COMPLEX",
                "description": "Migrate critical auth flow",
                "priority": 1,
                "labels": ["auth", "backend"],
            },
            {
                "objective": "Ship auth migration safely",
                "done_when": ["Migration works", "Tests pass"],
                "spirit_anti": "Do not break login",
                "decisions": [{"id": "d1", "title": "Keep API stable", "outcome": "compat shim"}],
                "context": {
                    "files_to_modify": ["backend/app/auth.py"],
                    "second_opinion": {
                        "required": True,
                        "stage": "task_shape",
                        "status": "completed",
                        "summary": "Plan covers migration and rollback risks.",
                    },
                },
            },
            [
                {
                    "subtask_id": "1.1",
                    "description": "Implement migration",
                    "steps_from_table": [{"step_number": 1, "description": "Update flow"}],
                }
            ],
        )

        assert readiness.ready

    def test_nonfrontend_execution_contract_noise_does_not_force_runtime_eval_gate(self) -> None:
        readiness = assess_task_execution_readiness(
            {"task_type": "bug", "complexity": "SIMPLE", "description": "Diagnose worker memory pressure"},
            {
                "done_when": ["Root cause identified", "Mitigation written up"],
                "context": {
                    "execution_contract": {
                        "mode": "runtime_eval",
                        "user_flows": [
                            {
                                "title": "Collect diagnostics",
                                "actions": ["Run journalctl and systemctl"],
                                "expected_outcomes": ["Memory timeline captured"],
                            }
                        ],
                        "negative_cases": [{"title": "No data", "status": 1}],
                    }
                },
            },
            [
                {
                    "subtask_id": "1.1",
                    "description": "Collect diagnostics",
                    "steps_from_table": [{"step_number": 1, "description": "Inspect logs"}],
                }
            ],
        )

        assert readiness.ready

    def test_ensure_second_opinion_tracking_does_not_auto_create_new_entry(self) -> None:
        with (
            patch("app.services.task_second_opinion.get_task_spirit", return_value={}),
            patch("app.services.task_second_opinion.update_task_spirit") as mock_update,
            patch("app.services.task_second_opinion.upsert_task_spirit") as mock_upsert,
        ):
            result = ensure_second_opinion_tracking(
                "task-mock-1",
                {
                    "task_type": "feature",
                    "complexity": "COMPLEX",
                    "priority": 1,
                    "labels": ["auth"],
                },
                source="planning",
            )

        assert result is None
        mock_update.assert_not_called()
        mock_upsert.assert_not_called()
