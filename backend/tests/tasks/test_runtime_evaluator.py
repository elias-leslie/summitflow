"""Tests for contract-driven runtime evaluation."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


@patch("app.tasks.autonomous.exec_modules.runtime_evaluator.run_design_critic")
@patch("app.tasks.autonomous.exec_modules.runtime_evaluator.capture_page_screenshot", new_callable=AsyncMock)
@patch("app.tasks.autonomous.exec_modules.runtime_evaluator.httpx.request")
@patch("app.tasks.autonomous.exec_modules.runtime_evaluator.get_project_config")
@patch("app.tasks.autonomous.exec_modules.runtime_evaluator.get_task_spirit")
def test_run_runtime_evaluator_uses_host_ip_urls_and_design_critic(
    mock_spirit: MagicMock,
    mock_project_config: MagicMock,
    mock_http_request: MagicMock,
    mock_capture_screenshot: AsyncMock,
    mock_design_critic: MagicMock,
    tmp_path: Path,
) -> None:
    from app.tasks.autonomous.exec_modules.runtime_evaluator import run_runtime_evaluator

    screenshot_path = tmp_path / "shot.png"
    screenshot_path.write_bytes(b"png")
    mock_spirit.return_value = {
        "context": {
            "execution_contract": {
                "mode": "runtime_eval_plus_design",
                "target_urls": ["/app/dashboard"],
                "user_flows": [
                    {
                        "title": "Open dashboard",
                        "actions": ["Visit /app/dashboard"],
                        "expected_outcomes": ["Dashboard content renders"],
                    }
                ],
                "api_checks": [{"method": "GET", "path": "/health", "expected_status": 200}],
                "design_criteria": {"rubric": ["originality", "craft"]},
                "evidence_requirements": ["screenshot"],
            }
        }
    }
    mock_project_config.return_value = {
        "frontend_port": 3001,
        "backend_port": 8001,
        "base_url": "http://localhost:3001",
    }
    mock_capture_screenshot.return_value = (True, None)
    mock_http_request.return_value = MagicMock(status_code=200, text='{"ok":true}', headers={"content-type": "application/json"})
    mock_design_critic.return_value = {
        "passed": True,
        "overall_score": 8.5,
        "findings": [],
        "scores": {"originality": 8, "visual_cohesion": 9, "craft": 8, "usability": 9},
    }

    with (
        patch("app.tasks.autonomous.exec_modules.runtime_evaluator._check_browser_health", return_value=(True, "ok")),
        patch("app.tasks.autonomous.exec_modules.runtime_evaluator._get_runtime_host", return_value="192.168.8.244"),
        patch("app.tasks.autonomous.exec_modules.runtime_evaluator._make_screenshot_path", return_value=screenshot_path),
        patch("app.tasks.autonomous.exec_modules.runtime_evaluator._evaluate_user_flow_with_screenshot", return_value={"passed": True, "summary": "flow pass", "evidence": [str(screenshot_path)]}),
    ):
        result = run_runtime_evaluator("task-1", "summitflow")

    assert result.passed
    assert result.mode == "runtime_eval_plus_design"
    assert result.design_result is not None
    mock_capture_screenshot.assert_awaited_once_with("http://192.168.8.244:3001/app/dashboard", screenshot_path)
    mock_http_request.assert_called_once()
    assert mock_http_request.call_args.args[1] == "http://192.168.8.244:8001/api/health"
    mock_design_critic.assert_called_once()


@patch("app.tasks.autonomous.exec_modules.runtime_evaluator.capture_page_screenshot", new_callable=AsyncMock)
@patch("app.tasks.autonomous.exec_modules.runtime_evaluator.httpx.request")
@patch("app.tasks.autonomous.exec_modules.runtime_evaluator.get_project_config")
@patch("app.tasks.autonomous.exec_modules.runtime_evaluator.get_task_spirit")
def test_run_runtime_evaluator_supports_running_event_loop(
    mock_spirit: MagicMock,
    mock_project_config: MagicMock,
    mock_http_request: MagicMock,
    mock_capture_screenshot: AsyncMock,
    tmp_path: Path,
) -> None:
    from app.tasks.autonomous.exec_modules.runtime_evaluator import run_runtime_evaluator

    screenshot_path = tmp_path / "loop-shot.png"
    screenshot_path.write_bytes(b"png")
    mock_spirit.return_value = {
        "context": {
            "execution_contract": {
                "mode": "runtime_eval",
                "target_urls": ["/app"],
                "user_flows": [
                    {
                        "title": "Open app shell",
                        "actions": ["Visit /app"],
                        "expected_outcomes": ["Application chrome renders"],
                    }
                ],
                "api_checks": [{"method": "GET", "path": "/health", "expected_status": 200}],
                "evidence_requirements": ["screenshot"],
            }
        }
    }
    mock_project_config.return_value = {
        "frontend_port": 3001,
        "backend_port": 8001,
        "base_url": "http://localhost:3001",
    }
    mock_capture_screenshot.return_value = (True, None)
    mock_http_request.return_value = MagicMock(status_code=200, text='{"ok":true}', headers={"content-type": "application/json"})

    async def _run_inside_loop() -> object:
        with (
            patch("app.tasks.autonomous.exec_modules.runtime_evaluator._check_browser_health", return_value=(True, "ok")),
            patch("app.tasks.autonomous.exec_modules.runtime_evaluator._get_runtime_host", return_value="192.168.8.244"),
            patch("app.tasks.autonomous.exec_modules.runtime_evaluator._make_screenshot_path", return_value=screenshot_path),
            patch("app.tasks.autonomous.exec_modules.runtime_evaluator._evaluate_user_flow_with_screenshot", return_value={"passed": True, "summary": "flow pass", "evidence": [str(screenshot_path)]}),
        ):
            return run_runtime_evaluator("task-1", "summitflow")

    result = asyncio.run(_run_inside_loop())

    assert result.passed
    mock_capture_screenshot.assert_awaited_once_with("http://192.168.8.244:3001/app", screenshot_path)
