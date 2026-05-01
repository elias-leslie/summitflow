"""Mockup image generation from design analysis."""

from __future__ import annotations

import base64
from pathlib import Path

from ....constants import GEMINI_IMAGE
from ....logging_config import get_logger
from ...agent_hub_client import get_sync_client
from ..prompts import build_mockup_image_prompt

logger = get_logger(__name__)


class MockupImageGenerationError(RuntimeError):
    """Image provider failed while generating a visual mockup."""


def _failure_message(exc: Exception) -> str:
    message = str(exc).strip() or type(exc).__name__
    if "rate limit" in message.lower():
        return f"Image provider rate limit: {message}"
    return f"Image generation failed: {message}"


def generate_mockup_image(
    project_id: str,
    screenshot_path: Path,
    recommendations: str,
    output_path: Path,
    page_url: str,
    *,
    raise_on_failure: bool = False,
) -> str | None:
    """Generate a mockup image showing the improved design.

    Uses Gemini Image to generate a visual mockup based on the
    current screenshot and the improvement recommendations.

    Args:
        screenshot_path: Path to the current page screenshot
        recommendations: Design analysis and recommendations text
        output_path: Path to save the generated mockup image
        page_url: URL of the page being analyzed

    Returns:
        Path to the generated mockup image, or None if generation failed
    """
    try:
        prompt = build_mockup_image_prompt(recommendations, page_url)

        # Call Gemini Image via Agent Hub
        client = get_sync_client()
        response = client.generate_image(
            prompt=prompt,
            project_id=project_id,
            purpose="mockup_generation",
            model=GEMINI_IMAGE,
            size="1920x1080",
        )

        # Decode and save image
        image_bytes = base64.b64decode(response.image_base64)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(image_bytes)

        logger.info(
            "mockup_image_generated",
            output_path=str(output_path),
            size_bytes=len(image_bytes),
        )

        return str(output_path)

    except Exception as e:
        message = _failure_message(e)
        if raise_on_failure:
            raise MockupImageGenerationError(message) from e
        logger.warning("mockup_image_generation_failed", error=message)
        return None


__all__ = ["MockupImageGenerationError", "generate_mockup_image"]
