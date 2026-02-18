"""Test subtask pass command helper functions.

Tests the is_step_resolved function that determines if a step should block
subtask completion.
"""

from __future__ import annotations

from cli.commands.subtask_validation import is_step_resolved


class TestIsStepResolved:
    """Tests for the is_step_resolved helper function."""

    def test_passed_step_is_resolved(self) -> None:
        """A step with passes=True is resolved."""
        step = {"step_number": 1, "passes": True, "status": "pending"}
        step_passes = {1: True}
        assert is_step_resolved(step, step_passes) is True

    def test_unpassed_step_not_resolved(self) -> None:
        """A step with passes=False and no plan_defect status is not resolved."""
        step = {"step_number": 1, "passes": False, "status": "pending"}
        step_passes = {1: False}
        assert is_step_resolved(step, step_passes) is False

    def test_plan_defect_with_passing_fix_is_resolved(self) -> None:
        """A plan_defect step with a passing fix step is resolved."""
        step = {
            "step_number": 2,
            "passes": False,
            "status": "plan_defect",
            "fix_step_number": 7,
        }
        step_passes = {2: False, 7: True}
        assert is_step_resolved(step, step_passes) is True

    def test_plan_defect_with_failing_fix_not_resolved(self) -> None:
        """A plan_defect step with a failing fix step is not resolved."""
        step = {
            "step_number": 2,
            "passes": False,
            "status": "plan_defect",
            "fix_step_number": 7,
        }
        step_passes = {2: False, 7: False}
        assert is_step_resolved(step, step_passes) is False

    def test_plan_defect_without_fix_step_not_resolved(self) -> None:
        """A plan_defect step without a fix_step_number is not resolved."""
        step = {
            "step_number": 2,
            "passes": False,
            "status": "plan_defect",
            "fix_step_number": None,
        }
        step_passes = {2: False}
        assert is_step_resolved(step, step_passes) is False

    def test_plan_defect_with_missing_fix_step_not_resolved(self) -> None:
        """A plan_defect step where fix step doesn't exist in map is not resolved."""
        step = {
            "step_number": 2,
            "passes": False,
            "status": "plan_defect",
            "fix_step_number": 99,  # Not in step_passes map
        }
        step_passes = {2: False, 7: True}
        assert is_step_resolved(step, step_passes) is False

    def test_missing_passes_field_not_resolved(self) -> None:
        """A step missing the passes field is not resolved."""
        step = {"step_number": 1, "status": "pending"}
        step_passes = {1: False}
        assert is_step_resolved(step, step_passes) is False

    def test_real_world_scenario(self) -> None:
        """Test a real-world scenario with multiple steps and plan defects."""
        # Simulate the scenario from task-1ca3cfc4 subtask 1.1:
        # Steps 1, 4, 7, 8, 9, 11, 12 passed
        # Steps 2, 3, 5, 6, 10 are plan_defect with fix steps
        steps = [
            {"step_number": 1, "passes": True, "status": "pending", "fix_step_number": None},
            {"step_number": 2, "passes": False, "status": "plan_defect", "fix_step_number": 7},
            {"step_number": 3, "passes": False, "status": "plan_defect", "fix_step_number": 8},
            {"step_number": 4, "passes": True, "status": "pending", "fix_step_number": None},
            {"step_number": 5, "passes": False, "status": "plan_defect", "fix_step_number": 12},
            {"step_number": 6, "passes": False, "status": "plan_defect", "fix_step_number": 11},
            {"step_number": 7, "passes": True, "status": "pending", "fix_step_number": None},
            {"step_number": 8, "passes": True, "status": "pending", "fix_step_number": None},
            {"step_number": 9, "passes": True, "status": "pending", "fix_step_number": None},
            {"step_number": 10, "passes": False, "status": "plan_defect", "fix_step_number": 11},
            {"step_number": 11, "passes": True, "status": "pending", "fix_step_number": None},
            {"step_number": 12, "passes": True, "status": "pending", "fix_step_number": None},
        ]
        step_passes: dict[int, bool] = {
            int(s["step_number"]): bool(s.get("passes", False)) for s in steps
        }

        # All steps should be resolved
        for step in steps:
            assert is_step_resolved(step, step_passes) is True, (
                f"Step {step['step_number']} should be resolved: "
                f"passes={step.get('passes')}, status={step.get('status')}, "
                f"fix_step={step.get('fix_step_number')}"
            )
