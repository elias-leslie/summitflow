"""Tests for the frontend design critic."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch


@patch("app.tasks.autonomous.exec_modules.design_critic.analyze_screenshot_with_prompt")
@patch("app.tasks.autonomous.exec_modules.design_critic.get_prompt_template")
@patch("app.tasks.autonomous.exec_modules.design_critic.gather_design_standards_context")
def test_run_design_critic_uses_designer_agent_and_returns_structured_result(
    mock_design_context: MagicMock,
    mock_get_prompt_template: MagicMock,
    mock_analyze: MagicMock,
    tmp_path: Path,
) -> None:
    from app.tasks.autonomous.exec_modules.design_critic import run_design_critic

    screenshot_path = tmp_path / "ui.png"
    screenshot_path.write_bytes(b"png")
    mock_design_context.return_value = "# Design Standards\n\n- Keep hierarchy clear"
    mock_get_prompt_template.return_value = (
        "Review {page_url}\n{design_standards}\n{design_criteria}\n{risk_notes}"
    )
    mock_analyze.return_value = (
        """
        {
          "passed": true,
          "summary": "Clear hierarchy with a few polish opportunities.",
          "overall_score": 8.4,
          "scores": {
            "originality": 8,
            "visual_cohesion": 9,
            "craft": 8,
            "usability": 9
          },
          "findings": ["Tighten spacing between the title and primary action."]
        }
        """,
        None,
    )

    result = run_design_critic(
        "summitflow",
        "http://192.168.8.244:3001/app",
        screenshot_path,
        {
            "design_criteria": {"rubric": ["originality", "craft"]},
            "risk_notes": ["Check dashboard visual balance"],
        },
    )

    assert result == {
        "passed": True,
        "summary": "Clear hierarchy with a few polish opportunities.",
        "scores": {
            "originality": 8.0,
            "visual_cohesion": 9.0,
            "craft": 8.0,
            "usability": 9.0,
        },
        "overall_score": 8.4,
        "findings": ["Tighten spacing between the title and primary action."],
    }
    mock_get_prompt_template.assert_called_once_with("frontend-design-critic")
    assert mock_analyze.call_args.kwargs["agent_slug"] == "designer"
