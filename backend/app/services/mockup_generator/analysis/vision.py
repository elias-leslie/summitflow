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

# Media type constants
_MEDIA_TYPE_PNG = "image/png"
_MEDIA_TYPE_JPEG = "image/jpeg"
_MEDIA_TYPE_WEBP = "image/webp"

# Agent Hub call constants
_PROJECT_ID = "summitflow"
_PURPOSE = "design_analysis"
_TEMPERATURE = 0.3
_ROLE_USER = "user"

# Issue counting patterns
_ISSUE_MARKER = "**Issue**:"
_LIST_MARKER = "- "


def _get_media_type(path: Path) -> str:
    """Return the MIME media type for the given image path."""
    suffix = path.suffix.lower()
    if suffix in (".jpg", ".jpeg"):
        return _MEDIA_TYPE_JPEG
    if suffix == ".webp":
        return _MEDIA_TYPE_WEBP
    return _MEDIA_TYPE_PNG


def _encode_image(path: Path) -> tuple[str, str]:
    """Read and base64-encode an image file.

    Returns:
        Tuple of (base64_encoded_string, media_type)
    """
    image_bytes = path.read_bytes()
    image_base64 = base64.b64encode(image_bytes).decode()
    media_type = _get_media_type(path)
    return image_base64, media_type


def _build_message(image_base64: str, media_type: str, prompt: str) -> MessageInput:
    """Build an Agent Hub MessageInput with image and text content."""
    image_content = ImageContent.from_base64(image_base64, media_type)
    text_content = TextContent(text=prompt)
    return MessageInput(
        role=_ROLE_USER,
        content=[image_content, text_content],
    )


def _call_vision_model(message: MessageInput) -> str:
    """Send a message to Gemini Pro vision and return the response text."""
    client = get_sync_client()
    response = client.complete(
        model=GEMINI_PRO,
        messages=[message],
        project_id=_PROJECT_ID,
        purpose=_PURPOSE,
        temperature=_TEMPERATURE,
    )
    return response.content


def _count_issues(recommendations: str) -> int:
    """Estimate the number of issues from markdown-formatted recommendations."""
    issues_count = recommendations.count(_ISSUE_MARKER)
    if issues_count == 0:
        issues_count = recommendations.count(_LIST_MARKER) // 2
    return issues_count


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
        image_base64, media_type = _encode_image(screenshot_path)
        prompt = build_design_analysis_prompt(design_rules, page_url)
        message = _build_message(image_base64, media_type, prompt)
        recommendations = _call_vision_model(message)
        issues_count = _count_issues(recommendations)
        return recommendations, issues_count, None

    except Exception as e:
        logger.error("vision_analysis_failed", error=str(e))
        return None, 0, str(e)


__all__ = ["analyze_screenshot_with_vision"]
