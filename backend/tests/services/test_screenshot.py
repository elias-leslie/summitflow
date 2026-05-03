"""Tests for screenshot capture utilities."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, patch


def _completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["st", "browser"], returncode, stdout=stdout, stderr=stderr)


class TestScreenshotCommands:
    def test_full_flag_included_when_full_page(self) -> None:
        from app.services.mockup_generator.analysis.screenshot import _screenshot_commands

        commands = _screenshot_commands("http://example.com", Path("/tmp/shot.png"), 800, 600, True)

        assert commands[-1] == ["st", "browser", "screenshot", "/tmp/shot.png", "--full"]

    def test_no_full_flag_when_not_full_page(self) -> None:
        from app.services.mockup_generator.analysis.screenshot import _screenshot_commands

        commands = _screenshot_commands("http://example.com", Path("/tmp/shot.png"), 800, 600, False)

        assert commands[-1] == ["st", "browser", "screenshot", "/tmp/shot.png"]


class TestCapturePageScreenshot:
    async def test_success_path_returns_true(self, tmp_path: Path) -> None:
        from app.services.mockup_generator.analysis.screenshot import capture_page_screenshot

        output = tmp_path / "shot.png"
        output.write_bytes(b"PNG")
        run = AsyncMock(return_value=_completed())

        with patch("app.services.mockup_generator.analysis.screenshot._run_browser_command", run):
            success, msg = await capture_page_screenshot("http://localhost:3001", output)

        assert success
        assert msg is None
        assert run.await_count == 5
        assert run.await_args_list[-1].args[0] == ["st", "browser", "close"]

    async def test_timeout_closes_browser_and_returns_timeout(self, tmp_path: Path) -> None:
        from app.services.mockup_generator.analysis.screenshot import capture_page_screenshot

        output = tmp_path / "shot.png"
        run = AsyncMock(
            side_effect=[
                subprocess.TimeoutExpired(cmd=["st", "browser"], timeout=60),
                _completed(),
            ]
        )

        with patch("app.services.mockup_generator.analysis.screenshot._run_browser_command", run):
            success, msg = await capture_page_screenshot("http://localhost:3001", output)

        assert not success
        assert msg == "Screenshot operation timed out"
        assert run.await_args_list[-1].args[0] == ["st", "browser", "close"]

    async def test_timeout_close_failure_does_not_propagate(self, tmp_path: Path) -> None:
        from app.services.mockup_generator.analysis.screenshot import capture_page_screenshot

        output = tmp_path / "shot.png"
        run = AsyncMock(
            side_effect=[
                subprocess.TimeoutExpired(cmd=["st", "browser"], timeout=60),
                Exception("close failed"),
            ]
        )

        with patch("app.services.mockup_generator.analysis.screenshot._run_browser_command", run):
            success, msg = await capture_page_screenshot("http://localhost:3001", output)

        assert not success
        assert msg == "Screenshot operation timed out"

    async def test_nonzero_returncode_returns_failure(self, tmp_path: Path) -> None:
        from app.services.mockup_generator.analysis.screenshot import capture_page_screenshot

        output = tmp_path / "shot.png"
        run = AsyncMock(side_effect=[_completed(1, stderr="agent-browser: screenshot error"), _completed()])

        with patch("app.services.mockup_generator.analysis.screenshot._run_browser_command", run):
            success, msg = await capture_page_screenshot("http://localhost:3001", output)

        assert not success
        assert msg == "Screenshot failed: agent-browser: screenshot error"
        assert run.await_args_list[-1].args[0] == ["st", "browser", "close"]

    async def test_missing_output_file_returns_failure(self, tmp_path: Path) -> None:
        from app.services.mockup_generator.analysis.screenshot import capture_page_screenshot

        output = tmp_path / "shot.png"
        run = AsyncMock(return_value=_completed())

        with patch("app.services.mockup_generator.analysis.screenshot._run_browser_command", run):
            success, msg = await capture_page_screenshot("http://localhost:3001", output)

        assert not success
        assert msg == "Screenshot file not created"
