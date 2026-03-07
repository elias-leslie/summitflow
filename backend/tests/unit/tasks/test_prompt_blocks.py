"""Tests for autonomous prompt block helpers."""

from __future__ import annotations

from app.tasks.autonomous.exec_modules._prompt_blocks import build_steps_block


class TestBuildStepsBlock:
    """Tests for rendering task steps into prompt context."""

    def test_renders_verify_commands_inline(self) -> None:
        steps = [
            {
                "step_number": 2,
                "description": "Quality gate: run checks",
                "spec": {"verify_commands": ["dt --quick", "dt pytest backend/tests/test_models.py -q"]},
            }
        ]

        block = build_steps_block(steps)

        assert "2. Quality gate: run checks" in block
        assert "Verification commands:" in block
        assert "`dt --quick`" in block
        assert "`dt pytest backend/tests/test_models.py -q`" in block

    def test_omits_verify_commands_section_when_absent(self) -> None:
        steps = [{"step_number": 1, "description": "Refactor the module"}]

        block = build_steps_block(steps)

        assert block == "Steps to complete:\n1. Refactor the module"

    def test_ignores_null_spec(self) -> None:
        steps = [
            {
                "step_number": 1,
                "description": "Verify structural issues resolved",
                "spec": None,
            }
        ]

        block = build_steps_block(steps)

        assert block == "Steps to complete:\n1. Verify structural issues resolved"
