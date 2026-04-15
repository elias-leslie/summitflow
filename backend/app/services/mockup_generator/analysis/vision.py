"""Vision-based design analysis via Agent Hub vision agents."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from agent_hub.models import ImageContent, MessageInput, TextContent

from ....logging_config import get_logger
from ...agent_hub_client import get_sync_client
from ..prompts import build_design_analysis_prompt

logger = get_logger(__name__)

# Media type constants
_MEDIA_TYPE_PNG = "image/png"
_MEDIA_TYPE_JPEG = "image/jpeg"
_MEDIA_TYPE_WEBP = "image/webp"

_PURPOSE = "design_analysis"
_TEMPERATURE = 0.3
_ROLE_USER = "user"
_DEFAULT_VISION_AGENT_SLUG = "site-checker"
_DESIGN_VISION_AGENT_SLUG = "designer"

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


def _call_vision_model(
    project_id: str,
    message: MessageInput,
    *,
    agent_slug: str,
) -> str:
    """Send a message through the configured vision agent and return the response text."""
    client = get_sync_client()
    response = client.complete(
        agent_slug=agent_slug,
        messages=[message],
        project_id=project_id,
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


def analyze_screenshot_with_prompt(
    project_id: str,
    screenshot_path: Path,
    prompt: str,
    *,
    agent_slug: str = _DEFAULT_VISION_AGENT_SLUG,
) -> tuple[str | None, str | None]:
    """Run a custom image prompt against a screenshot."""
    try:
        image_base64, media_type = _encode_image(screenshot_path)
        message = _build_message(image_base64, media_type, prompt)
        return _call_vision_model(project_id, message, agent_slug=agent_slug), None
    except Exception as e:
        logger.error("vision_prompt_failed", error=str(e))
        return None, str(e)


def analyze_screenshot_with_vision(
    project_id: str,
    screenshot_path: Path,
    design_rules: list[dict[str, Any]],
    page_url: str,
) -> tuple[str | None, int, str | None]:
    """Analyze screenshot via Agent Hub using the configured vision agent.

    Args:
        screenshot_path: Path to screenshot file
        design_rules: Design rules to check against
        page_url: URL being analyzed

    Returns:
        Tuple of (recommendations, issues_count, error)
    """
    try:
        prompt = build_design_analysis_prompt(design_rules, page_url)
        recommendations, error = analyze_screenshot_with_prompt(
            project_id,
            screenshot_path,
            prompt,
            agent_slug=_DESIGN_VISION_AGENT_SLUG,
        )
        if error or recommendations is None:
            return None, 0, error or "Vision prompt failed"
        issues_count = _count_issues(recommendations)
        return recommendations, issues_count, None

    except Exception as e:
        logger.error("vision_analysis_failed", error=str(e))
        return None, 0, str(e)


__all__ = ["analyze_screenshot_with_prompt", "analyze_screenshot_with_vision"]
