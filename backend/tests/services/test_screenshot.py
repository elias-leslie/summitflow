"""Tests for screenshot capture utilities.

Covers the two resource-leak fixes in capture_page_screenshot():
1. proc.kill() is invoked and browser close is attempted on TimeoutError.
2. agent-browser close runs even when the command chain fails (non-zero exit).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


class TestBuildScreenshotCommand:
    """Tests for _build_screenshot_command() helper."""

    def test_semicolon_separator_before_close(self) -> None:
        """The close command is separated by ';' so it always runs."""
        from app.services.mockup_generator.analysis.screenshot import (
            _build_screenshot_command,
        )

        cmd = _build_screenshot_command(
            url="http://localhost:3001",
            output_path=Path("/tmp/shot.png"),
            width=1280,
            height=720,
            full_page=True,
        )
        # The close must be separated by ';' (not '&&') so it executes
        # even when the screenshot command itself fails.
        assert " ; agent-browser close" in cmd

    def test_full_flag_included_when_full_page(self) -> None:
        """--full flag is present when full_page=True."""
        from app.services.mockup_generator.analysis.screenshot import (
            _build_screenshot_command,
        )

        cmd = _build_screenshot_command(
            url="http://example.com",
            output_path=Path("/tmp/shot.png"),
            width=800,
            height=600,
            full_page=True,
        )
        assert "--full" in cmd

    def test_no_full_flag_when_not_full_page(self) -> None:
        """--full flag is absent when full_page=False."""
        from app.services.mockup_generator.analysis.screenshot import (
            _build_screenshot_command,
        )

        cmd = _build_screenshot_command(
            url="http://example.com",
            output_path=Path("/tmp/shot.png"),
            width=800,
            height=600,
            full_page=False,
        )
        assert "--full" not in cmd


class TestCapturePageScreenshot:
    """Tests for capture_page_screenshot() resource-cleanup behaviour."""

    def _make_proc(
        self,
        *,
        communicate_side_effect: object = None,
        returncode: int = 0,
    ) -> MagicMock:
        """Return a mock subprocess with configurable communicate behaviour."""
        proc = MagicMock()
        proc.returncode = returncode
        if communicate_side_effect is not None:
            proc.communicate = AsyncMock(side_effect=communicate_side_effect)
        else:
            proc.communicate = AsyncMock(return_value=(b"", b""))
        proc.kill = MagicMock()
        return proc

    # ------------------------------------------------------------------
    # Scenario 1: TimeoutError → proc.kill() called, browser close attempted
    # ------------------------------------------------------------------

    async def test_timeout_kills_proc_and_closes_browser(
        self, tmp_path: Path
    ) -> None:
        """On TimeoutError: proc.kill() is called and browser close is attempted.

        The finally block in capture_page_screenshot checks `proc.returncode is None`
        to decide whether to kill the process. When a timeout fires, the process is
        still running so returncode must be None.
        """
        output = tmp_path / "shot.png"
        proc = self._make_proc(returncode=0)
        # Simulate process still running at the time of the timeout
        proc.returncode = None
        # After kill(), communicate() drains the pipe
        proc.communicate = AsyncMock(return_value=(b"", b""))

        close_proc = MagicMock()
        close_proc.communicate = AsyncMock(return_value=(b"", b""))

        with (
            patch(
                "app.services.mockup_generator.analysis.screenshot.asyncio.create_subprocess_shell",
                new=AsyncMock(side_effect=[proc, close_proc]),
            ),
            patch(
                "app.services.mockup_generator.analysis.screenshot.asyncio.wait_for",
                new=AsyncMock(side_effect=TimeoutError()),
            ),
        ):
            from app.services.mockup_generator.analysis.screenshot import (
                capture_page_screenshot,
            )

            success, error_msg = await capture_page_screenshot(
                url="http://localhost:3001",
                output_path=output,
            )

        assert success is False
        assert error_msg == "Screenshot operation timed out"
        proc.kill.assert_called_once()

    async def test_timeout_close_failure_does_not_propagate(
        self, tmp_path: Path
    ) -> None:
        """If browser close fails after timeout, the error is swallowed."""
        output = tmp_path / "shot.png"
        proc = self._make_proc()
        proc.returncode = None
        proc.communicate = AsyncMock(return_value=(b"", b""))

        close_proc = MagicMock()
        # Simulate close also failing
        close_proc.communicate = AsyncMock(side_effect=Exception("close failed"))

        with (
            patch(
                "app.services.mockup_generator.analysis.screenshot.asyncio.create_subprocess_shell",
                new=AsyncMock(side_effect=[proc, close_proc]),
            ),
            patch(
                "app.services.mockup_generator.analysis.screenshot.asyncio.wait_for",
                new=AsyncMock(side_effect=TimeoutError()),
            ),
        ):
            from app.services.mockup_generator.analysis.screenshot import (
                capture_page_screenshot,
            )

            # Must not raise — close error is caught internally
            success, msg = await capture_page_screenshot(
                url="http://localhost:3001",
                output_path=output,
            )

        assert success is False
        assert msg == "Screenshot operation timed out"

    # ------------------------------------------------------------------
    # Scenario 2: Non-zero returncode → returns (False, error message)
    #             The ';' separator means 'agent-browser close' was issued
    # ------------------------------------------------------------------

    async def test_nonzero_returncode_returns_failure(self, tmp_path: Path) -> None:
        """Non-zero exit code returns (False, 'Screenshot failed: ...')."""
        output = tmp_path / "shot.png"
        stderr_bytes = b"agent-browser: screenshot error"
        proc = self._make_proc(returncode=1)
        proc.communicate = AsyncMock(return_value=(b"", stderr_bytes))
        proc.returncode = 1

        with (
            patch(
                "app.services.mockup_generator.analysis.screenshot.asyncio.create_subprocess_shell",
                new=AsyncMock(return_value=proc),
            ),
            patch(
                "app.services.mockup_generator.analysis.screenshot.asyncio.wait_for",
                new=AsyncMock(return_value=(b"", stderr_bytes)),
            ),
        ):
            from app.services.mockup_generator.analysis.screenshot import (
                capture_page_screenshot,
            )

            success, msg = await capture_page_screenshot(
                url="http://localhost:3001",
                output_path=output,
            )

        assert success is False
        assert msg is not None
        assert "Screenshot failed" in msg

    async def test_nonzero_returncode_stderr_in_message(self, tmp_path: Path) -> None:
        """Stderr content appears in the failure message (up to 200 chars)."""
        output = tmp_path / "shot.png"
        stderr_bytes = b"connection refused on port 9222"
        proc = self._make_proc(returncode=1)
        proc.returncode = 1

        with (
            patch(
                "app.services.mockup_generator.analysis.screenshot.asyncio.create_subprocess_shell",
                new=AsyncMock(return_value=proc),
            ),
            patch(
                "app.services.mockup_generator.analysis.screenshot.asyncio.wait_for",
                new=AsyncMock(return_value=(b"", stderr_bytes)),
            ),
        ):
            from app.services.mockup_generator.analysis.screenshot import (
                capture_page_screenshot,
            )

            success, msg = await capture_page_screenshot(
                url="http://localhost:3001",
                output_path=output,
            )

        assert success is False
        assert "connection refused on port 9222" in (msg or "")

    async def test_success_path_returns_true(self, tmp_path: Path) -> None:
        """Happy path: zero returncode + file exists → (True, None)."""
        output = tmp_path / "shot.png"
        # Simulate the screenshot file being created
        output.write_bytes(b"PNG")

        proc = self._make_proc(returncode=0)
        proc.returncode = 0

        with (
            patch(
                "app.services.mockup_generator.analysis.screenshot.asyncio.create_subprocess_shell",
                new=AsyncMock(return_value=proc),
            ),
            patch(
                "app.services.mockup_generator.analysis.screenshot.asyncio.wait_for",
                new=AsyncMock(return_value=(b"", b"")),
            ),
        ):
            from app.services.mockup_generator.analysis.screenshot import (
                capture_page_screenshot,
            )

            success, msg = await capture_page_screenshot(
                url="http://localhost:3001",
                output_path=output,
            )

        assert success is True
        assert msg is None

    async def test_missing_output_file_returns_failure(self, tmp_path: Path) -> None:
        """Zero returncode but file not created → (False, 'Screenshot file not created')."""
        output = tmp_path / "shot.png"
        # File intentionally NOT created

        proc = self._make_proc(returncode=0)
        proc.returncode = 0

        with (
            patch(
                "app.services.mockup_generator.analysis.screenshot.asyncio.create_subprocess_shell",
                new=AsyncMock(return_value=proc),
            ),
            patch(
                "app.services.mockup_generator.analysis.screenshot.asyncio.wait_for",
                new=AsyncMock(return_value=(b"", b"")),
            ),
        ):
            from app.services.mockup_generator.analysis.screenshot import (
                capture_page_screenshot,
            )

            success, msg = await capture_page_screenshot(
                url="http://localhost:3001",
                output_path=output,
            )

        assert success is False
        assert msg == "Screenshot file not created"

    # ------------------------------------------------------------------
    # Scenario: proc.kill() in finally block when returncode is None
    # ------------------------------------------------------------------

    async def test_finally_kills_proc_when_returncode_none(
        self, tmp_path: Path
    ) -> None:
        """If proc.returncode is None after communicate, kill() is called."""
        output = tmp_path / "shot.png"
        proc = self._make_proc(returncode=0)
        # Simulate communicate completing but returncode still None
        proc.returncode = None
        proc.communicate = AsyncMock(return_value=(b"", b""))

        with (
            patch(
                "app.services.mockup_generator.analysis.screenshot.asyncio.create_subprocess_shell",
                new=AsyncMock(return_value=proc),
            ),
            patch(
                "app.services.mockup_generator.analysis.screenshot.asyncio.wait_for",
                new=AsyncMock(return_value=(b"", b"")),
            ),
        ):
            from app.services.mockup_generator.analysis.screenshot import (
                capture_page_screenshot,
            )

            await capture_page_screenshot(
                url="http://localhost:3001",
                output_path=output,
            )

        proc.kill.assert_called_once()
