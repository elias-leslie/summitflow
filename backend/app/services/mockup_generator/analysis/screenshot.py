"""Screenshot capture utilities for design analysis."""

from __future__ import annotations

import asyncio
import shlex
from pathlib import Path

from ....logging_config import get_logger

logger = get_logger(__name__)


def _build_screenshot_command(
    url: str,
    output_path: Path,
    width: int,
    height: int,
    full_page: bool,
) -> str:
    """Build the agent-browser command chain for capturing a screenshot."""
    full_flag = "--full" if full_page else ""
    return (
        f"agent-browser open {shlex.quote(url)} && "
        f"agent-browser set viewport {width} {height} && "
        f"agent-browser wait --load networkidle && "
        f"agent-browser screenshot {shlex.quote(str(output_path))} {full_flag} ; "
        f"agent-browser close"
    )


async def _close_browser_after_timeout() -> None:
    """Attempt to close the browser after a screenshot timeout."""
    try:
        close_proc = await asyncio.create_subprocess_shell(
            "agent-browser close",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(close_proc.communicate(), timeout=5)
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
        cmd = _build_screenshot_command(url, output_path, width, height, full_page)
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        finally:
            if proc.returncode is None:
                proc.kill()
                await proc.communicate()

        if proc.returncode != 0:
            error_msg = stderr.decode().strip() or stdout.decode().strip()
            return False, f"Screenshot failed: {error_msg[:200]}"

        if not output_path.exists():
            return False, "Screenshot file not created"

        return True, None

    except TimeoutError:
        await _close_browser_after_timeout()
        return False, "Screenshot operation timed out"
    except Exception as e:
        logger.error("screenshot_capture_failed", url=url, error=str(e))
        return False, str(e)


__all__ = ["capture_page_screenshot"]
