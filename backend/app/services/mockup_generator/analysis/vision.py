"""Vision-based design analysis using Gemini Pro."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from agent_hub.models import ImageContent, MessageInput, TextContent

from ....constants import GEMINI_PRO
from ....logging_config import get_logger
from ...agent_hub_client import get_sync_client
from ..prompts import build_design_analysis_prompt

logger = get_logger(__name__)


def analyze_screenshot_with_vision(
    screenshot_path: Path,
    design_rules: list[dict[str, Any]],
    page_url: str,
) -> tuple[str | None, int, str | None]:
    """Analyze screenshot using Gemini Pro vision via Agent Hub.

    Args:
        screenshot_path: Path to screenshot file
        design_rules: Design rules to check against
        page_url: URL being analyzed

    Returns:
        Tuple of (recommendations, issues_count, error)
    """
    try:
        # Read and encode screenshot
        image_bytes = screenshot_path.read_bytes()
        image_base64 = base64.b64encode(image_bytes).decode()

        # Determine media type
        suffix = screenshot_path.suffix.lower()
        media_type = "image/png"
        if suffix in (".jpg", ".jpeg"):
            media_type = "image/jpeg"
        elif suffix == ".webp":
            media_type = "image/webp"

        # Build prompt
        prompt = build_design_analysis_prompt(design_rules, page_url)

        # Create message with image and text content blocks
        image_content = ImageContent.from_base64(image_base64, media_type)
        text_content = TextContent(text=prompt)
        message = MessageInput(
            role="user",
            content=[image_content, text_content],
        )

        # Call Gemini Pro vision via Agent Hub
        client = get_sync_client()
        response = client.complete(
            model=GEMINI_PRO,
            messages=[message],
            project_id="summitflow",
            purpose="design_analysis",
            temperature=0.3,
        )

        recommendations = response.content

        # Count issues (rough estimate from markdown)
        issues_count = recommendations.count("**Issue**:")
        if issues_count == 0:
            issues_count = recommendations.count("- ") // 2

        return recommendations, issues_count, None

    except Exception as e:
        logger.error("vision_analysis_failed", error=str(e))
        return None, 0, str(e)


__all__ = ["analyze_screenshot_with_vision"]
