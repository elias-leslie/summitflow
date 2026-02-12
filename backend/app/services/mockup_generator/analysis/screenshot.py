"""Screenshot capture utilities for design analysis."""

from __future__ import annotations

import asyncio
import shlex
from pathlib import Path

from ....logging_config import get_logger

logger = get_logger(__name__)


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
        # Build command chain for agent-browser
        full_flag = "--full" if full_page else ""
        cmd = (
            f"agent-browser open {shlex.quote(url)} && "
            f"agent-browser set viewport {width} {height} && "
            f"agent-browser wait --load networkidle && "
            f"agent-browser screenshot {shlex.quote(str(output_path))} {full_flag} && "
            f"agent-browser close"
        )

        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)

        if proc.returncode != 0:
            error_msg = stderr.decode().strip() or stdout.decode().strip()
            return False, f"Screenshot failed: {error_msg[:200]}"

        if not output_path.exists():
            return False, "Screenshot file not created"

        return True, None

    except TimeoutError:
        # Try to close browser if still open
        try:
            close_proc = await asyncio.create_subprocess_shell(
                "agent-browser close",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(close_proc.communicate(), timeout=5)
        except Exception:
            pass
        return False, "Screenshot operation timed out"
    except Exception as e:
        logger.error("screenshot_capture_failed", url=url, error=str(e))
        return False, str(e)


__all__ = ["capture_page_screenshot"]
