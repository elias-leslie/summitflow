"""Tests for centralized task harness routing and execution-contract normalization."""

from __future__ import annotations

from app.services.task_harness import determine_task_harness, normalize_execution_contract


class TestNormalizeExecutionContract:
    def test_assigns_ids_and_normalizes_list_fields(self) -> None:
        contract = normalize_execution_contract(
            {
                "mode": "runtime_eval_plus_design",
                "target_urls": ["/app/projects/demo/design"],
                "user_flows": [
                    {
                        "title": "Open design tab",
                        "actions": "Visit the design page",
                        "expected_outcomes": "Design view renders",
                    }
                ],
                "api_checks": [
                    {
                        "method": "GET",
                        "path": "/projects/demo",
                        "status": 200,
                    }
                ],
                "negative_cases": [{"title": "Missing project", "path": "/projects/missing", "status": 404}],
                "evidence_requirements": ["screenshot"],
            }
        )

        assert contract["mode"] == "runtime_eval_plus_design"
        assert contract["user_flows"][0]["flow_id"] == "flow-1"
        assert contract["user_flows"][0]["actions"] == ["Visit the design page"]
        assert contract["user_flows"][0]["expected_outcomes"] == ["Design view renders"]
        assert contract["api_checks"][0]["criterion_id"] == "api-1"
        assert contract["negative_cases"][0]["criterion_id"] == "negative-1"


class TestDetermineTaskHarness:
    def test_simple_backend_bug_routes_to_code_only(self) -> None:
        decision = determine_task_harness(
            {
                "task_type": "bug",
                "complexity": "SIMPLE",
                "description": "Fix import path",
            },
            {
                "context": {"files_to_modify": ["backend/app/main.py"]},
            },
            [],
        )

        assert decision.mode == "code_only"
        assert not decision.requires_execution_contract

    def test_cross_surface_frontend_task_routes_to_runtime_eval(self) -> None:
        decision = determine_task_harness(
            {
                "task_type": "feature",
                "complexity": "STANDARD",
                "description": "Ship the new dashboard flow",
            },
            {
                "context": {
                    "files_to_modify": ["frontend/app/dashboard/page.tsx"],
                    "execution_contract": {
                        "target_urls": ["/app/dashboard"],
                        "user_flows": [
                            {
                                "title": "Open dashboard",
                                "actions": ["Visit /app/dashboard"],
                                "expected_outcomes": ["Dashboard renders"],
                            }
                        ],
                    },
                }
            },
            [{"subtask_type": "frontend", "description": "Build dashboard page"}],
        )

        assert decision.mode == "runtime_eval"
        assert decision.requires_execution_contract

    def test_design_metadata_without_runtime_checks_routes_to_code_only(self) -> None:
        decision = determine_task_harness(
            {
                "task_type": "feature",
                "complexity": "STANDARD",
                "description": "Redesign the project overview",
            },
            {
                "context": {
                    "files_to_modify": ["frontend/app/projects/[id]/design/page.tsx"],
                    "execution_contract": {
                        "design_criteria": {"rubric": ["originality", "craft"]},
                    },
                }
            },
            [{"subtask_type": "ui-design", "description": "Redesign the overview"}],
        )

        assert decision.mode == "code_only"
        assert not decision.run_design_critic

    def test_runtime_contract_with_design_criteria_runs_design_critic(self) -> None:
        decision = determine_task_harness(
            {
                "task_type": "feature",
                "complexity": "STANDARD",
                "description": "Redesign the project overview",
            },
            {
                "context": {
                    "files_to_modify": ["frontend/app/projects/[id]/design/page.tsx"],
                    "execution_contract": {
                        "mode": "runtime_eval_plus_design",
                        "target_urls": ["/app/projects/demo"],
                        "design_criteria": {"rubric": ["originality", "craft"]},
                    },
                }
            },
            [{"subtask_type": "ui-design", "description": "Redesign the overview"}],
        )

        assert decision.mode == "runtime_eval_plus_design"
        assert decision.run_design_critic
