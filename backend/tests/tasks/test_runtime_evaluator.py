"""Tests for contract-driven runtime evaluation."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

from app.tasks.autonomous.exec_modules._runtime_eval_helpers import RuntimeEvaluationResult


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
        patch("app.tasks.autonomous.exec_modules.runtime_evaluator._get_runtime_host", return_value="192.0.2.44"),
        patch("app.tasks.autonomous.exec_modules.runtime_evaluator._make_screenshot_path", return_value=screenshot_path),
        patch("app.tasks.autonomous.exec_modules.runtime_evaluator._evaluate_user_flow_with_screenshot", return_value={"passed": True, "summary": "flow pass", "evidence": [str(screenshot_path)]}),
        patch("app.tasks.autonomous.exec_modules.runtime_evaluator._probe_frontend_target", return_value={"ok": True, "status_code": 200, "error": None}),
    ):
        result = run_runtime_evaluator("task-1", "summitflow")

    assert result.passed
    assert result.mode == "runtime_eval_plus_design"
    assert result.design_result is not None
    mock_capture_screenshot.assert_awaited_once_with("http://192.0.2.44:3001/app/dashboard", screenshot_path)
    mock_http_request.assert_called_once()
    assert mock_http_request.call_args.args[1] == "http://192.0.2.44:8001/api/health"
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

    async def _run_inside_loop() -> RuntimeEvaluationResult:
        with (
            patch("app.tasks.autonomous.exec_modules.runtime_evaluator._check_browser_health", return_value=(True, "ok")),
            patch("app.tasks.autonomous.exec_modules.runtime_evaluator._get_runtime_host", return_value="192.0.2.44"),
            patch("app.tasks.autonomous.exec_modules.runtime_evaluator._make_screenshot_path", return_value=screenshot_path),
            patch("app.tasks.autonomous.exec_modules.runtime_evaluator._evaluate_user_flow_with_screenshot", return_value={"passed": True, "summary": "flow pass", "evidence": [str(screenshot_path)]}),
            patch("app.tasks.autonomous.exec_modules.runtime_evaluator._probe_frontend_target", return_value={"ok": True, "status_code": 200, "error": None}),
        ):
            return run_runtime_evaluator("task-1", "summitflow")

    result = asyncio.run(_run_inside_loop())

    assert result.passed
    mock_capture_screenshot.assert_awaited_once_with("http://192.0.2.44:3001/app", screenshot_path)


def test_capture_runtime_page_retries_transient_browser_failure_when_frontend_is_reachable(tmp_path: Path) -> None:
    from app.tasks.autonomous.exec_modules.runtime_evaluator import _capture_runtime_page

    screenshot_path = tmp_path / "retry-shot.png"

    with (
        patch(
            "app.tasks.autonomous.exec_modules.runtime_evaluator._probe_frontend_target",
            return_value={"ok": True, "status_code": 200, "error": None},
        ) as mock_probe,
        patch(
            "app.tasks.autonomous.exec_modules.runtime_evaluator._capture_page_screenshot_sync",
            side_effect=[(False, "Screenshot failed: net::ERR_CONNECTION_REFUSED"), (True, None)],
        ) as mock_capture,
        patch("app.tasks.autonomous.exec_modules.runtime_evaluator.time.sleep") as mock_sleep,
    ):
        success, error, details = _capture_runtime_page(
            "http://192.0.2.44:3001/",
            screenshot_path,
            "chrome UP; lightpanda UP",
        )

    assert success is True
    assert error is None
    assert details["resolved_target"] == "http://192.0.2.44:3001/"
    assert details["attempt"] == 2
    assert details["probe"]["status_code"] == 200
    assert mock_probe.call_count == 2
    assert mock_capture.call_count == 2
    mock_sleep.assert_called_once_with(0.5)


@patch("app.tasks.autonomous.exec_modules.runtime_evaluator.capture_page_screenshot", new_callable=AsyncMock)
@patch("app.tasks.autonomous.exec_modules.runtime_evaluator.httpx.request")
@patch("app.tasks.autonomous.exec_modules.runtime_evaluator.get_project_config")
@patch("app.tasks.autonomous.exec_modules.runtime_evaluator.get_task_spirit")
def test_run_runtime_evaluator_reports_probe_details_when_browser_fails_but_frontend_is_reachable(
    mock_spirit: MagicMock,
    mock_project_config: MagicMock,
    mock_http_request: MagicMock,
    mock_capture_screenshot: AsyncMock,
    tmp_path: Path,
) -> None:
    from app.tasks.autonomous.exec_modules.runtime_evaluator import run_runtime_evaluator

    screenshot_path = tmp_path / "fail-shot.png"
    mock_spirit.return_value = {
        "context": {
            "execution_contract": {
                "mode": "runtime_eval",
                "target_urls": ["/"],
                "api_checks": [{"method": "GET", "path": "/health", "expected_status": 200}],
            }
        }
    }
    mock_project_config.return_value = {
        "frontend_port": 3001,
        "backend_port": 8001,
        "base_url": "http://localhost:3001",
    }
    mock_http_request.return_value = MagicMock(status_code=200, text='{"ok":true}', headers={"content-type": "application/json"})
    mock_capture_screenshot.return_value = (False, "unused")

    with (
        patch("app.tasks.autonomous.exec_modules.runtime_evaluator._check_browser_health", return_value=(True, "chrome UP; lightpanda UP")),
        patch("app.tasks.autonomous.exec_modules.runtime_evaluator._get_runtime_host", return_value="192.0.2.44"),
        patch("app.tasks.autonomous.exec_modules.runtime_evaluator._make_screenshot_path", return_value=screenshot_path),
        patch(
            "app.tasks.autonomous.exec_modules.runtime_evaluator._probe_frontend_target",
            return_value={"ok": True, "status_code": 200, "error": None},
        ),
        patch(
            "app.tasks.autonomous.exec_modules.runtime_evaluator._capture_page_screenshot_sync",
            side_effect=[
                (False, "Screenshot failed: net::ERR_CONNECTION_REFUSED"),
                (False, "Screenshot failed: net::ERR_CONNECTION_REFUSED"),
                (False, "Screenshot failed: net::ERR_CONNECTION_REFUSED"),
            ],
        ),
        patch("app.tasks.autonomous.exec_modules.runtime_evaluator.time.sleep") as mock_sleep,
    ):
        result = run_runtime_evaluator("task-2", "summitflow")

    assert result.passed is False
    browser_criterion = result.criteria[0]
    assert browser_criterion["category"] == "browser"
    assert "resolved target http://192.0.2.44:3001/" in browser_criterion["summary"]
    assert "attempt 3/3" in browser_criterion["summary"]
    assert "direct GET http://192.0.2.44:3001/ -> 200" in browser_criterion["summary"]
    assert "browser health: chrome UP; lightpanda UP" in browser_criterion["summary"]
    assert browser_criterion["details"]["probe"]["status_code"] == 200
    assert browser_criterion["details"]["attempts"] == 3
    assert mock_sleep.mock_calls == [call(0.5), call(1.0)]
