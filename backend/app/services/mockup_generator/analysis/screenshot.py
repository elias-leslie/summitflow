"""Screenshot capture utilities for design analysis."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ....logging_config import get_logger
from ....utils import safe_subprocess

logger = get_logger(__name__)
_BROWSER_CMD = ("st", "browser")


def _screenshot_commands(
    url: str,
    output_path: Path,
    width: int,
    height: int,
    full_page: bool,
) -> list[list[str]]:
    """Build browser CLI commands for capturing a screenshot."""
    screenshot = [*_BROWSER_CMD, "screenshot", str(output_path)]
    if full_page:
        screenshot.append("--full")
    return [
        [*_BROWSER_CMD, "open", url],
        [*_BROWSER_CMD, "set", "viewport", str(width), str(height)],
        [*_BROWSER_CMD, "wait", "--load", "networkidle"],
        screenshot,
    ]


async def _run_browser_command(command: list[str], timeout: float = 15) -> subprocess.CompletedProcess[str]:
    return await safe_subprocess.run_async(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


async def _close_browser_after_timeout() -> None:
    """Attempt to close the browser after a screenshot timeout."""
    try:
        await _run_browser_command([*_BROWSER_CMD, "close"], timeout=5)
    except Exception:
        logger.debug("Failed to close browser after screenshot timeout", exc_info=True)


async def capture_page_screenshot(
    url: str,
    output_path: Path,
    *,
    width: int = 1280,
    height: int = 720,
    full_page: bool = True,
) -> tuple[bool, str | None]:
    """Capture a screenshot of a URL using agent-browser.

    Args:
        url: URL to capture
        output_path: Path to save screenshot
        width: Viewport width
        height: Viewport height
        full_page: Whether to capture full page

    Returns:
        Tuple of (success, error_message)
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        for command in _screenshot_commands(url, output_path, width, height, full_page):
            result = await _run_browser_command(command, timeout=60)
            if result.returncode != 0:
                error_msg = (result.stderr or result.stdout).strip()
                return False, f"Screenshot failed: {error_msg[:200]}"
        if not output_path.exists():
            return False, "Screenshot file not created"
        return True, None
    except subprocess.TimeoutExpired:
        return False, "Screenshot operation timed out"
    except Exception as e:
        logger.error("screenshot_capture_failed", url=url, error=str(e))
        return False, str(e)
    finally:
        await _close_browser_after_timeout()


__all__ = ["capture_page_screenshot"]
